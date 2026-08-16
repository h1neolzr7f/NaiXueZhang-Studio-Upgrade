"""Butler batch ops implementation."""

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


def _build_generation_comment(args: dict[str, Any]) -> dict[str, Any]:
    work_id = int(args.get("work_id") or 0)
    gallery_id = api._gallery_id(args.get("gallery_id"))
    if args.get("remix_recipe"):
        from butler.remix import prepare_remix_draft

        prepared = prepare_remix_draft(
            {
                **args,
                "generation": dict(args.get("generation") or api._studio_generation_settings(args)),
            }
        )
        return copy.deepcopy((prepared.get("draft") or {}).get("comment") or {})
    source = (
        api.import_from_work(work_id, int(args.get("page_index") or 0), gallery_id)
        if work_id else {}
    )
    comment = copy.deepcopy(source.get("comment") or {})
    texts = copy.deepcopy(source.get("texts") or {})
    prompt = str(args.get("prompt") or texts.get("prompt") or texts.get("base_caption") or "").strip()
    if not prompt:
        raise ValueError("没有可用于生图的 Prompt")
    uc = str(args.get("uc") if args.get("uc") is not None else texts.get("uc") or "").strip()
    comment["prompt"] = prompt
    comment["uc"] = uc
    v4_prompt = copy.deepcopy(comment.get("v4_prompt") or {})
    caption = copy.deepcopy(v4_prompt.get("caption") or {})
    caption["base_caption"] = prompt
    v4_prompt["caption"] = caption
    comment["v4_prompt"] = v4_prompt
    defaults = api.studio_config().get("defaults") or {}
    source_params = source.get("params") or {}
    for key in ("width", "height", "steps", "scale", "sampler"):
        comment[key] = args.get(key, source_params.get(key, defaults.get(key)))
    comment["seed"] = args.get("seed", source_params.get("seed"))
    return comment



def workflow_status() -> dict[str, Any]:
    with api._WORKFLOW_LOCK:
        return copy.deepcopy(api._WORKFLOW)



def _set_workflow(**updates: Any) -> None:
    with api._WORKFLOW_LOCK:
        api._WORKFLOW.update(updates)



def _begin_workflow(kind: str, message: str) -> str:
    with api._WORKFLOW_LOCK:
        if api._WORKFLOW.get("status") == "running":
            raise ValueError("已有管家后台任务正在运行")
        workflow_id = secrets.token_hex(6)
        api._WORKFLOW.clear()
        api._WORKFLOW.update(
            {
                "id": workflow_id,
                "kind": kind,
                "status": "running",
                "phase": "starting",
                "message": message,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": "",
                "result": None,
            }
        )
        return workflow_id



def _spawn_workflow(coro: Any) -> None:
    task = asyncio.create_task(coro)
    api._WORKFLOW_TASKS.add(task)
    task.add_done_callback(api._WORKFLOW_TASKS.discard)



def _batch_targets(args: dict[str, Any]) -> list[dict[str, Any]]:
    if args.get("remix_recipe"):
        from butler.remix import build_remix_targets

        refs = copy.deepcopy(args.get("work_refs") or [
            {"gallery_id": args.get("gallery_id") or "site", "work_id": work_id}
            for work_id in args["work_ids"]
        ])
        transform = (args.get("remix_recipe") or {}).get("transform") or {}
        for ref in refs:
            parsed = api.WorkRef.parse(ref["work_id"], ref.get("gallery_id"))
            if parsed.gallery_id != "site" and transform.get("enabled"):
                raise ValueError("手动换角依赖网站图库的 NovelAI v4 角色槽；法典/Q群作品可用于普通批量生成，但不能直接执行同质量换角")
            if args.get("all_pages"):
                detail = api._require_work(int(parsed.work_id), parsed.gallery_id)
                images = detail.get("images") or []
                pages = sorted({
                    int(image.get("page_index", index))
                    for index, image in enumerate(images)
                    if isinstance(image, dict)
                })
                if not pages:
                    count = int((detail.get("work") or {}).get("image_count") or 0)
                    pages = list(range(max(1, count)))
                ref["page_indexes"] = pages
            else:
                ref["page_indexes"] = [int(args.get("page_index") or 0)]
            ref["gallery_id"] = parsed.gallery_id
            ref["work_id"] = int(parsed.work_id)
        targets = build_remix_targets({**args, "work_refs": refs})
        source_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        for target in targets:
            gallery_id = str(target.get("gallery_id") or "site")
            if gallery_id == "site":
                continue
            cache_key = (
                gallery_id,
                int(target["work_id"]),
                int(target.get("page_index") or 0),
            )
            if cache_key not in source_cache:
                source_cache[cache_key] = api.import_from_work(
                    cache_key[1], cache_key[2], cache_key[0]
                )
            target["patched_comment"] = copy.deepcopy(
                source_cache[cache_key].get("comment") or {}
            )
        if len(targets) > 200:
            raise ValueError("展开全部页面后超过 200 张，请减少作品数或每页份数")
        return targets
    targets: list[dict[str, Any]] = []
    generation = dict(args.get("generation") or {})
    copies = int(args.get("copies_per_work") or 1)
    seed = generation.get("seed")
    offset = 0
    refs = args.get("work_refs") or [
        {"gallery_id": args.get("gallery_id") or "site", "work_id": work_id}
        for work_id in args["work_ids"]
    ]
    for raw_ref in refs:
        ref = api.WorkRef.parse(raw_ref["work_id"], raw_ref.get("gallery_id"))
        work_id = int(ref.work_id)
        source_args = {
            **generation,
            "gallery_id": ref.gallery_id,
            "work_id": work_id,
            "page_index": 0,
        }
        base_comment = api._build_generation_comment(source_args)
        for _ in range(copies):
            comment = copy.deepcopy(base_comment)
            if seed is not None:
                comment["seed"] = int(seed) + offset
            targets.append(
                {
                    "gallery_id": ref.gallery_id,
                    "work_id": work_id,
                    "page_index": 0,
                    "patched_comment": comment,
                }
            )
            offset += 1
    return targets



def _preview_remix_action(action: dict[str, Any]) -> dict[str, Any] | None:
    """Run the manual transform pipeline without contacting a generation provider."""
    args = action.get("arguments") or {}
    recipe = args.get("remix_recipe") or {}
    transform = recipe.get("transform") or {}
    style = recipe.get("style") or {}
    style_reference = style.get("reference") or {}
    if action.get("tool") not in {"batch_generate", "batch_generate_and_prepare_pixiv"}:
        return None
    if not transform.get("enabled") and not style:
        return None
    from nai_char import batch_preview

    preview = batch_preview({"targets": api._batch_targets(args), "recipe": recipe})
    items = list(preview.get("items") or [])
    ready = sum(
        1
        for item in items
        if item.get("ok")
        and (not transform.get("enabled") or item.get("transform_applied"))
        and (not style or item.get("style_applied"))
    )
    total = int(preview.get("total") or 0)
    if ready <= 0:
        first_error = next(
            (str(item.get("message") or "") for item in preview.get("items") or [] if not item.get("ok")),
            "没有页面可完成再创作",
        )
        label = "换角/换画风" if transform.get("enabled") and style else (
            "换角" if transform.get("enabled") else "换画风"
        )
        raise ValueError(f"{label}预检未通过：{first_error}")
    return {
        "kind": "character_remix" if transform.get("enabled") else "style_remix",
        "ready": ready,
        "total": total,
        "skipped": max(0, total - ready),
        "preset_id": str(transform.get("preset_id") or ""),
        "preset_label": str(
            transform.get("preset_label")
            or "、".join(
                str(item.get("preset_label") or item.get("preset_id") or "").strip()
                for item in (transform.get("replacements") or [])
                if isinstance(item, dict)
                and str(item.get("preset_label") or item.get("preset_id") or "").strip()
            )
            or ""
        ),
        "reference_id": str((transform.get("reference") or {}).get("reference_id") or ""),
        "reference_label": str((transform.get("reference") or {}).get("label") or ""),
        "reference_source": str((transform.get("reference") or {}).get("source") or ""),
        "mode": str(transform.get("mode") or ""),
        "target": transform.get("target_char_index", "auto"),
        "style_preset_id": str(style.get("preset_id") or ""),
        "style_preset_label": str(style.get("preset_label") or ""),
        "style_reference_id": str(style_reference.get("style_id") or ""),
        "style_reference_label": str(style_reference.get("label") or ""),
        "style_reference_source": str(style_reference.get("source") or ""),
        "style_mode": str(style.get("mode") or ""),
        "items": [
            {
                "gallery_id": str(item.get("gallery_id") or "site"),
                "work_id": item.get("work_id"),
                "page_index": item.get("page_index"),
                "ok": bool(item.get("ok")),
                "skipped": bool(item.get("skipped")),
                "message": str(item.get("message") or "")[:160],
                "summary": str(item.get("summary") or "")[:160],
                "transform_applied": bool(item.get("transform_applied")),
                "style_applied": bool(item.get("style_applied")),
            }
            for item in items[:20]
        ],
    }



async def _watch_batch_workflow(*, task_id: str, prepare_pixiv: bool, extra: str) -> None:
    from nai_batch import batch_status

    try:
        while True:
            state = batch_status(task_id or None)
            status = str(state.get("status") or "")
            api._set_workflow(
                phase="generating",
                message=str(state.get("message") or "批量生成中…"),
                progress={
                    "done": int(state.get("done") or 0),
                    "total": int(state.get("total") or 0),
                    "ok": int(state.get("ok_count") or 0),
                    "failed": int(state.get("fail_count") or 0),
                },
            )
            if status not in {"running", ""}:
                break
            await asyncio.sleep(1.5)

        if status != "done" or int(state.get("ok_count") or 0) <= 0:
            raise RuntimeError(str(state.get("message") or "批量生成没有成功结果"))
        if not prepare_pixiv:
            api._set_workflow(
                status="done",
                phase="done",
                message="批量生成完成",
                finished_at=datetime.now().isoformat(timespec="seconds"),
                result={
                    "generated": int(state.get("ok_count") or 0),
                    "gallery_url": "/generated",
                },
            )
            return

        image_ids: list[str] = []
        for item in state.get("items") or []:
            if not item.get("ok"):
                continue
            filename = str(item.get("filename") or "").strip()
            if filename:
                image_id = filename.rsplit(".", 1)[0]
                if image_id not in image_ids:
                    image_ids.append(image_id)
        if not image_ids:
            raise RuntimeError("批量生成完成，但没有找到可交接投稿的图片")

        api._set_workflow(
            phase="preparing_pixiv",
            message=f"正在为 {len(image_ids)} 张图片补齐后处理和投稿文案…",
        )
        from pixiv_launch import prepare_submission_package

        prepared = await asyncio.to_thread(
            prepare_submission_package,
            {"image_ids": image_ids, "extra": extra},
        )
        api._set_workflow(
            status="ready",
            phase="ready_for_upload",
            message="批量生成、后处理和投稿文案已全部完成，等待你检查并上传",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=prepared.get("prepared") or prepared,
        )
    except Exception as exc:
        api._set_workflow(
            status="error",
            phase="error",
            message=api.public_error(exc)[:500],
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=None,
        )



async def _prepare_pixiv_workflow(args: dict[str, Any]) -> None:
    try:
        api._set_workflow(phase="preparing_pixiv", message="正在补齐后处理并生成投稿文案…")
        from pixiv_launch import prepare_submission_package

        prepared = await asyncio.to_thread(prepare_submission_package, args)
        api._set_workflow(
            status="ready",
            phase="ready_for_upload",
            message="投稿素材已准备完成，等待你检查并上传",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=prepared.get("prepared") or prepared,
        )
    except Exception as exc:
        api._set_workflow(
            status="error",
            phase="error",
            message=api.public_error(exc)[:500],
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=None,
        )



def _start_batch_workflow(args: dict[str, Any], *, prepare_pixiv: bool) -> dict[str, Any]:
    workflow_id = api._begin_workflow(
        "batch_generate_and_prepare_pixiv" if prepare_pixiv else "batch_generate",
        "正在启动批量生成…",
    )
    from nai_batch import start_batch

    try:
        for ref in args.get("work_refs") or []:
            api._require_work(int(ref["work_id"]), ref.get("gallery_id") or "site")
        targets = api._batch_targets(args)
        recipe = dict(args.get("remix_recipe") or {})
        if not recipe:
            recipe = {
                "transform": {"enabled": False},
                "sanitize": {"enabled": True},
                "prompt_profile": "native",
            }
        from char_swap_config import load_config as load_char_swap_config

        from nai_authorization import ACTION_CHAR_SWAP, compile_batch_authorization, issue_for_preview

        force_free = bool(load_char_swap_config().get("force_free", True))
        issued = issue_for_preview(
            compile_batch_authorization(
                targets,
                recipe,
                force_free=force_free,
                action=ACTION_CHAR_SWAP,
            )
        )
        result = start_batch(
            targets,
            recipe,
            force_free=force_free,
            generate=True,
            preview_only=False,
            authorization_ticket=str(issued.get("ticket") or ""),
            authorization_action=ACTION_CHAR_SWAP,
        )
    except Exception as exc:
        api._set_workflow(
            status="error",
            phase="error",
            message=api.public_error(exc),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        raise
    if not result.get("ok"):
        api._set_workflow(
            status="error",
            phase="error",
            message=str(result.get("message") or "批量生成启动失败"),
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )
        raise ValueError(str(result.get("message") or "批量生成启动失败"))
    api._spawn_workflow(
        api._watch_batch_workflow(
            task_id=str(result.get("task_id") or (result.get("batch") or {}).get("id") or ""),
            prepare_pixiv=prepare_pixiv,
            extra=str(args.get("extra") or ""),
        )
    )
    return {
        "ok": True,
        "tool": "batch_generate_and_prepare_pixiv" if prepare_pixiv else "batch_generate",
        "workflow_id": workflow_id,
        "message": "批量任务已启动；管家会在后台继续处理",
        "batch": {
            "id": (result.get("batch") or {}).get("id"),
            "total": (result.get("batch") or {}).get("total"),
            "status": (result.get("batch") or {}).get("status"),
        },
    }

