"""Butler cards implementation."""

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


def _thumb_url(item: dict[str, Any], gallery_id: str = "site") -> str:
    raw = api._clean_text(item.get("thumb_path"), limit=500).replace("\\", "/").lstrip("/")
    if not raw:
        return ""
    prefixes = ("data/images/", "images/", "data/gallery/codex/", "data/gallery/qqgroup/")
    for prefix in prefixes:
        if raw.startswith(prefix):
            raw = raw.removeprefix(prefix)
            break
    return f"{api.get_spec(gallery_id).asset_base_url}{raw}"



def _tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            loaded = json.loads(str(value or "[]"))
            raw = loaded if isinstance(loaded, list) else []
        except (TypeError, json.JSONDecodeError):
            raw = []
    return [api._clean_text(item, limit=80) for item in raw[:8] if api._clean_text(item, limit=80)]



def _work_card(item: dict[str, Any], gallery_id: str = "site") -> dict[str, Any]:
    gid = api._gallery_id(gallery_id)
    work_id = int(item.get("id") or item.get("work_id") or 0)
    return {
        "gallery_id": gid,
        "work_id": work_id,
        "title": api._clean_text(item.get("title") or item.get("caption") or f"作品 {work_id}", limit=180),
        "caption": api._clean_text(item.get("caption"), limit=280),
        "tags": api._tags(item.get("tags")),
        "image_count": int(item.get("image_count") or 0),
        "views": int(item.get("total_view") or 0),
        "bookmarks": int(item.get("total_bookmarks") or 0),
        "thumb": api._thumb_url(item, gid),
        "url": f"/i/{work_id}?gallery={gid}",
    }



def _require_work(work_id: int, gallery_id: str = "site") -> dict[str, Any]:
    gid = api._gallery_id(gallery_id)
    db = api.get_db(gid)
    if gid == "site" and api.GALLERY_LOCAL_ONLY and api.GALLERY_SCOPE and not db.work_in_scope(work_id, api.GALLERY_SCOPE):
        raise ValueError(f"作品 {work_id} 不在当前本地图库范围内")
    detail = db.get_work_detail(work_id)
    if not detail:
        raise ValueError(f"{gid} 图库中的作品 {work_id} 不存在")
    return detail



def _prepare_studio(args: dict[str, Any]) -> dict[str, Any]:
    work_id = int(args.get("work_id") or 0)
    gallery_id = api._gallery_id(args.get("gallery_id"))
    page_index = int(args.get("page_index") or 0)
    source: dict[str, Any] = {}
    if work_id:
        api._require_work(work_id, gallery_id)
        source = api.import_from_work(work_id, page_index, gallery_id)
    texts = copy.deepcopy(source.get("texts") or {})
    if args.get("prompt"):
        texts["prompt"] = args["prompt"]
        texts["base_caption"] = args["prompt"]
    if args.get("uc"):
        texts["uc"] = args["uc"]
    texts.setdefault("prompt", texts.get("base_caption") or "")
    texts.setdefault("base_caption", texts.get("prompt") or "")
    texts.setdefault("uc", "")
    texts.setdefault("char_captions", [])

    defaults = api.studio_config().get("defaults") or {}
    params = {**defaults, **(source.get("params") or {})}
    for key in ("width", "height", "steps", "scale", "sampler", "seed"):
        if key in args:
            params[key] = args[key]
    params["batch"] = int(args.get("batch_count") or 1)
    return {
        "ok": True,
        "tool": "prepare_studio",
        "title": source.get("title") or ("独立 Prompt 草稿" if not work_id else f"作品 {work_id}"),
        "thumb": source.get("thumb") or "",
        "draft": {
            "galleryId": gallery_id,
            "workId": work_id,
            "pageIndex": page_index,
            "texts": texts,
            "params": params,
            "refs": {"vibe": "", "char": "", "strength": "0.6"},
        },
        "studio_url": f"/studio?butler=1&gallery={gallery_id}",
    }



def _prepare_character_reference(args: dict[str, Any]) -> dict[str, Any]:
    """Prepare the same local Studio Draft used by the manual reference page."""

    catalog = api.get_reference_catalog()
    item = catalog.get(str(args["reference_id"]))
    if item is None:
        raise ValueError("指定的 NAI 角色资料不存在")
    work_id = int(args.get("work_id") or 0)
    gallery_id = api._gallery_id(args.get("gallery_id"))
    page_index = int(args.get("page_index") or 0)
    source: dict[str, Any] = {}
    if work_id:
        api._require_work(work_id, gallery_id)
        source = api.import_from_work(work_id, page_index, gallery_id)
    comment = copy.deepcopy(source.get("comment") or {})

    prompt = api._clean_text(args.get("prompt"), limit=8000)
    if prompt:
        comment["prompt"] = prompt
        v4 = comment.setdefault("v4_prompt", {})
        if not isinstance(v4, dict):
            v4 = {}
            comment["v4_prompt"] = v4
        caption = v4.setdefault("caption", {})
        if not isinstance(caption, dict):
            caption = {}
            v4["caption"] = caption
        caption["base_caption"] = prompt
    if args.get("uc"):
        comment["uc"] = api._clean_text(args.get("uc"), limit=4000)
    for key in ("width", "height", "steps", "scale", "sampler", "seed"):
        if args.get(key) is not None:
            comment[key] = args[key]
    comment["model"] = str(args.get("model") or "nai-diffusion-4-5-full")

    patched, card = api.apply_anima_character_to_comment(
        comment,
        item["raw"],
        slot_index=int(args.get("slot_index") or 0),
        model=comment["model"],
    )
    title = str(source.get("title") or f"{card.get('label') or '角色'} · NAI 角色草稿")
    draft = api.build_studio_draft(
        patched,
        work_id=work_id,
        page_index=page_index,
        title=title,
        thumb=str(source.get("thumb") or item.get("thumb_url") or item.get("image_url") or ""),
        batch_count=int(args.get("batch_count") or 1),
    )
    draft["galleryId"] = gallery_id
    draft["reference"] = {
        "referenceId": item["reference_id"],
        "source": item["source"],
        "sourceId": item["source_id"],
        "label": item["label"],
        "slotIndex": int(args.get("slot_index") or 0),
    }
    return {
        "ok": True,
        "tool": "prepare_character_reference",
        "title": title,
        "thumb": draft.get("thumb") or "",
        "draft": draft,
        "reference": {
            "reference_id": item["reference_id"],
            "label": item["label"],
            "source": item["source"],
            "source_id": item["source_id"],
            "copyright": item["copyright"],
            "character_caption": card["character_caption"],
            "slot_index": int(args.get("slot_index") or 0),
            "provenance": item["provenance"],
        },
        "provider": "local",
        "generation_calls": 0,
        "studio_url": "/studio?butler=1&reference=1",
        "message": f"{item['label']} 已放入第 {int(args.get('slot_index') or 0) + 1} 个 NAI 角色槽，草稿已就绪",
    }

