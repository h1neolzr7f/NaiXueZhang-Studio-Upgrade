"""Butler config ops implementation."""

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


def _butler_auto_path() -> Path:
    return Path(api.DATA_DIR) / "butler_auto.json"



def _legacy_butler_auto_path() -> Path:
    return Path(api.ROOT) / "data" / "butler_auto.json"



def _auto_config_path() -> Path:
    current = api._butler_auto_path()
    if current.exists():
        return current
    legacy = api._legacy_butler_auto_path()
    try:
        if legacy.exists() and legacy.resolve() != current.resolve():
            return legacy
    except OSError:
        pass
    return current



def _auto_config() -> dict[str, Any]:
    try:
        import json as _json

        path = api._auto_config_path()
        if path.exists():
            value = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
    except (OSError, ValueError):
        pass
    return {}



def _auto_mode_enabled() -> bool:
    return bool(api._auto_config().get("auto_mode"))



def _auto_repair_enabled() -> bool:
    return bool(api._auto_config().get("auto_repair"))



def _main_gallery_empty() -> bool:
    return api.main_gallery_empty(api.DB)



def _enabled_flag(value: Any) -> bool:
    if value in (False, 0, None, ""):
        return False
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(value)



def _crawler_mutation_blocked_when_empty(args: dict[str, Any]) -> bool:
    if not api._main_gallery_empty():
        return False
    extra = [key for key in api._CRAWLER_SETTING_KEYS if key != "enabled" and key in args]
    if extra:
        return True
    return "enabled" in args and api._enabled_flag(args.get("enabled"))



def _save_auto_config(**updates: Any) -> dict[str, Any]:
    import json as _json

    current = api._auto_config()
    current.update(updates)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = api._butler_auto_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return current



def _load_butler_catalog() -> dict[str, Any]:
    candidates = (Path(api.DATA_DIR) / "butler_catalog.json", Path(api.ROOT) / "data" / "butler_catalog.json")
    seen: set[Path] = set()
    last_missing = candidates[0]
    for path in candidates:
        last_missing = path
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except ValueError as exc:
            raise RuntimeError(f"管家目录数据损坏：{path}") from exc
    raise RuntimeError(f"缺少管家目录数据文件：{last_missing}") from None

