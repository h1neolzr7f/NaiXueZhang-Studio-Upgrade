"""Butler audit implementation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import json
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nai_prompt_optimizer import ai_status
from pixiv_launch import chat_json
from product_ops import build_product_health
from gallery_catalog import get_db, get_spec
from gallery_guard import EMPTY_GALLERY_CRAWL_MSG, main_gallery_empty
from server_shared import (
    CONFIG,
    CRAWLER_WATCHDOG,
    DATA_DIR,
    DB,
    GALLERY_LOCAL_ONLY,
    GALLERY_SCOPE,
    ROOT,
)
from studio_service import build_studio_draft, import_from_work, list_queue_for_studio, studio_config
from nai_anima_adapter import apply_anima_character_to_comment
from knowledge_catalog import get_knowledge_catalog
from reference_catalog import get_reference_catalog
from work_refs import WorkRef
from butler_gallery_operations import (
    CONFIRM_OPERATIONS as GALLERY_CONFIRM_OPERATIONS,
    READ_OPERATIONS as GALLERY_READ_OPERATIONS,
    catalogue as gallery_operation_catalogue,
    confirmation_summary as gallery_confirmation_summary,
    execute_confirmed as execute_gallery_confirmed,
    execute_read as execute_gallery_read,
    handles as handles_gallery_operation,
    normalize as normalize_gallery_operation,
    resolve_work_selection,
)
from butler.service_api import api


def _audit_summary(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "work_id", "work_ids", "group_id", "group_ids", "image_id", "image_ids",
        "page_index", "all_pages", "all_missing", "only_missing", "width", "height",
        "steps", "scale", "sampler", "seed", "batch_count", "copies_per_work",
        "target", "phase", "crawler_phase", "search_sort", "search_time_range",
        "search_max_pages", "limit", "restart", "reset_search", "task_id", "action",
    ):
        if key in args:
            summary[key] = args[key]
    if isinstance(args.get("generation"), dict):
        summary["generation"] = {
            key: value
            for key, value in args["generation"].items()
            if key in {"width", "height", "steps", "scale", "sampler", "seed"}
        }
    if isinstance(args.get("remix_recipe"), dict):
        recipe = args["remix_recipe"]
        transform = recipe.get("transform") or {}
        style = recipe.get("style") or {}
        style_reference = style.get("reference") or {}
        summary["remix"] = {
            "character": bool(transform.get("enabled")),
            "preset_id": str(transform.get("preset_id") or ""),
            "preset_label": str(transform.get("preset_label") or ""),
            "mode": str(transform.get("mode") or ""),
            "target": transform.get("target_char_index", "auto"),
            "preserve_action": bool(transform.get("preserve_action", False)),
            "style": bool(style),
            "style_preset_id": str(style.get("preset_id") or ""),
            "style_preset_label": str(style.get("preset_label") or ""),
            "style_reference_id": str(style_reference.get("style_id") or ""),
            "style_reference_label": str(style_reference.get("label") or ""),
            "style_reference_source": str(style_reference.get("source") or ""),
            "style_mode": str(style.get("mode") or ""),
            "sanitize": bool((recipe.get("sanitize") or {}).get("enabled")),
            "prompt_profile": str(recipe.get("prompt_profile") or "native"),
        }
    if args.get("prompt"):
        summary["prompt_chars"] = len(str(args["prompt"]))
    if args.get("uc"):
        summary["uc_chars"] = len(str(args["uc"]))
    if args.get("note"):
        summary["note_chars"] = len(str(args["note"]))
    return summary



def _write_audit(tool: str, status: str, args: dict[str, Any], *, detail: str = "") -> None:
    row = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "tool": tool,
        "risk": api._TOOL_BY_NAME.get(tool, {}).get("risk", "unknown"),
        "status": status,
        "summary": api._audit_summary(tool, args),
        "detail": api.public_error(detail)[:240],
    }
    with api._AUDIT_LOCK:
        api.AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with api.AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")



def recent_audit(limit: int = 12) -> list[dict[str, Any]]:
    count = max(1, min(int(limit), 40))
    if not api.AUDIT_PATH.exists():
        return []
    try:
        lines = api.AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-count:]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows



def _prune_pending() -> None:
    now = api.time.time()
    expired = [key for key, item in api._PENDING.items() if float(item["expires_at"]) <= now]
    for key in expired:
        api._PENDING.pop(key, None)



def _style_display_label(style: dict[str, Any]) -> str:
    """Return the human-facing style identity for previews and reports."""

    reference = style.get("reference") or {}
    return str(
        reference.get("label")
        or style.get("preset_label")
        or reference.get("tag")
        or style.get("preset_id")
        or ""
    ).strip()



def _confirmation_summary(action: dict[str, Any]) -> str:
    tool = action["tool"]
    args = action["arguments"]
    if tool == "add_to_queue":
        return f"把 {len(args['work_ids'])} 个作品加入待生成：{', '.join(map(str, args['work_ids']))}"
    if tool == "remove_from_queue":
        return f"把 {len(args['work_ids'])} 个作品移出待生成：{', '.join(map(str, args['work_ids']))}"
    if tool == "clear_queue":
        return "清空整个待生成队列"
    if tool == "batch_director":
        recipe = args.get("recipe") or {}
        tool_labels = {
            "remove_background": "移除背景",
            "line_art": "提取线稿",
            "sketch": "生成草图",
            "colorize": "智能上色",
            "emotion": "修改表情",
            "declutter": "画面清理",
        }
        source_count = len(args.get("sources") or [])
        output_count = source_count * int(recipe.get("outputs_per_source") or 1)
        label = tool_labels.get(str(recipe.get("tool") or ""), "导演处理")
        return (
            f"对 {source_count} 张精确选定图片执行“{label}”，预计交付 {output_count} 张结果；"
            "实际调用可能产生 Anlas，失败项不会自动重试"
        )
    if tool in {"batch_generate", "batch_generate_and_prepare_pixiv"}:
        total = len(api._batch_targets(args))
        tail = "，完成后自动准备投稿" if tool == "batch_generate_and_prepare_pixiv" else ""
        recipe = args.get("remix_recipe") or {}
        transform = recipe.get("transform") or {}
        style = recipe.get("style") or {}
        reference = transform.get("reference") or {}
        multi_labels = [
            str(item.get("preset_label") or item.get("preset_id") or "").strip()
            for item in (transform.get("replacements") or [])
            if isinstance(item, dict)
            and str(item.get("preset_label") or item.get("preset_id") or "").strip()
        ]
        label = str(
            reference.get("label")
            or transform.get("preset_label")
            or transform.get("preset_id")
            or "、".join(multi_labels)
            or ""
        ).strip()
        style_label = api._style_display_label(style)
        remix_parts: list[str] = []
        if transform.get("enabled"):
            remix_parts.append(f"换成角色“{label}”" if label else "执行换角")
        if style:
            remix_parts.append(f"换成“{style_label}”" if style_label else "执行换画风")
        remix = f"，{'并'.join(remix_parts)}" if remix_parts else ""
        pages = "，覆盖全部页面" if args.get("all_pages") else f"，第 {int(args.get('page_index') or 0) + 1} 页"
        return f"按 {len(args['work_ids'])} 个作品批量生成 {total} 张{remix}{pages}{tail}"
    if tool == "prepare_pixiv_submission":
        return f"为 {len(args['group_ids'])} 个生成系列补齐后处理与投稿文案，停在上传前"
    if tool in api.GALLERY_CONFIRM_OPERATIONS:
        return api.gallery_confirmation_summary(tool, args)
    source = f"作品 {args['work_id']}" if args.get("work_id") else "独立 Prompt"
    params = [f"{args.get('batch_count', 1)} 张"]
    if args.get("width") and args.get("height"):
        params.append(f"{args['width']}×{args['height']}")
    if args.get("steps"):
        params.append(f"steps {args['steps']}")
    if args.get("scale") is not None:
        params.append(f"scale {args['scale']}")
    remix = "，应用换角/换画风配方" if args.get("remix_recipe") else ""
    return f"用{source}执行生图（{'，'.join(params)}{remix}）"



def _production_work_order(action: dict[str, Any]) -> dict[str, Any] | None:
    tool = str(action.get("tool") or "")
    if tool not in api._PRODUCTION_TOOLS:
        return None
    args = action.get("arguments") or {}
    work_ids = args.get("work_ids") if isinstance(args.get("work_ids"), list) else []
    work_id = args.get("work_id")
    if work_id in (None, "", 0) and work_ids:
        work_id = work_ids[0]
    copies = args.get("copies_per_work") or args.get("batch_count") or 1
    try:
        copies_n = int(copies or 1)
    except (TypeError, ValueError):
        copies_n = 1
    recipe = args.get("remix_recipe") or {}
    transform = recipe.get("transform") or {}
    style = recipe.get("style") or {}
    change: dict[str, Any] = {"copies": max(1, copies_n)}
    if isinstance(transform, dict) and (transform.get("enabled") or transform.get("preset_id") or transform.get("reference")):
        reference = transform.get("reference") or {}
        change["character"] = str(
            reference.get("label")
            or transform.get("preset_label")
            or transform.get("preset_id")
            or ""
        ).strip() or True
    if isinstance(style, dict) and style:
        change["style"] = api._style_display_label(style) or True
    return {
        "source": {
            "gallery_id": args.get("gallery_id") or "site",
            "work_id": work_id,
            "page": int(args.get("page_index") or 0),
            "provider": "novelai",
        },
        "change": change,
        "cost": {"anlas_estimate": "unknown"},
        "retry_policy": "no-5xx-retry",
    }



def _stage_confirmation(action: dict[str, Any]) -> dict[str, Any]:
    confirmation_id = secrets.token_urlsafe(24)
    now = api.time.time()
    with api._PENDING_LOCK:
        api._prune_pending()
        api._PENDING[confirmation_id] = {
            "action": action,
            "created_at": now,
            "expires_at": now + api.CONFIRM_TTL_SECONDS,
        }
    api._write_audit(action["tool"], "pending", action["arguments"])
    payload = {
        "confirmation_id": confirmation_id,
        "tool": action["tool"],
        "label": action["label"],
        "risk": action["risk"],
        "summary": api._confirmation_summary(action),
        "expires_in": api.CONFIRM_TTL_SECONDS,
        "lane": (
            "production"
            if action["tool"] in api._PRODUCTION_TOOLS
            else "repair"
            if action["tool"] in api._REPAIR_TOOLS
            else "confirm"
        ),
    }
    work_order = api._production_work_order(action)
    if work_order:
        payload["work_order"] = work_order
    return payload

