"""Butler text ops implementation."""

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


def _clean_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]



def public_error(value: Any) -> str:
    text = api._clean_text(value, limit=800)
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    text = re.sub(
        r"(?i)(api[_-]?key|refresh[_-]?token|authorization)\s*[:=]\s*[^\s,;}]+",
        r"\1=[REDACTED]",
        text,
    )
    return text



def normalize_image_attachment(value: Any) -> dict[str, Any] | None:
    """Validate an ephemeral browser image without writing it to disk or SQLite."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise ValueError("图片附件格式不正确")
    data_url = str(value.get("data_url") or "").strip()
    match = re.fullmatch(
        r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)",
        data_url,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("仅支持 PNG、JPEG 或 WebP 图片")
    mime = match.group(1).lower()
    encoded = re.sub(r"\s+", "", match.group(2))
    if len(encoded) > ((api.MAX_IMAGE_BYTES + 2) // 3) * 4 + 4:
        raise ValueError("图片太大，请压缩到 6MB 以内")
    try:
        binary = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("图片数据损坏，请重新选择") from exc
    if not binary or len(binary) > api.MAX_IMAGE_BYTES:
        raise ValueError("图片太大，请压缩到 6MB 以内")
    signatures = {
        "image/png": binary.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": binary.startswith(b"\xff\xd8\xff"),
        "image/webp": binary.startswith(b"RIFF") and binary[8:12] == b"WEBP",
    }
    if not signatures.get(mime, False):
        raise ValueError("图片内容与文件格式不一致")
    raw_name = str(value.get("name") or "图片").replace("\\", "/").rsplit("/", 1)[-1]
    name = api._clean_text(raw_name, limit=120) or "图片"
    return {
        "name": name,
        "mime": mime,
        "size_bytes": len(binary),
        "data_url": f"data:{mime};base64,{encoded}",
    }



def _int_value(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} 必须在 {minimum}..{maximum} 之间")
    return parsed



def _float_value(
    value: Any,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} 必须在 {minimum}..{maximum} 之间")
    return parsed



def _work_ids(value: Any) -> list[int]:
    raw = value if isinstance(value, list) else [value]
    ids: list[int] = []
    for item in raw[:20]:
        parsed = api._int_value(item, name="work_id", minimum=1, maximum=2**63 - 1)
        if parsed and parsed not in ids:
            ids.append(parsed)
    if not ids:
        raise ValueError("需要至少一个有效作品 ID")
    return ids



def _gallery_id(value: Any = None) -> str:
    """Strictly validate a public gallery identifier without silent fallback."""
    return api.WorkRef.parse(1, str(value or "site")).gallery_id

