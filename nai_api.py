"""Local NovelAI proxy: token pool, status, and image generation.

Implementation lives in the :mod:`nai` package. This module remains the
patch-compatible facade used by tests and callers (`import nai_api`,
`patch.object(nai_api, ...)`).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from typing import Any

import httpx

from paths import DeferredDataPath, data_dir
from usage_ledger import record_usage
from nai.constants import (
    API_BASE,
    DIRECTOR_OUTPUT_MAX_BYTES,
    DIRECTOR_OUTPUT_MAX_PIXELS,
    DIRECTOR_RESPONSE_MAX_BYTES,
    DIRECTOR_ZIP_MAX_ENTRIES,
    IMAGE_API_BASE,
    PROVIDER_NOVELAI,
    PROVIDER_UNKNOWN,
    PROVIDER_XIANYUN,
    XIANYUN_API_BASE,
    _COOLDOWN_SEC,
    _NAI_TRANSIENT_TTL_SEC,
    _TOKEN_ENTRIES_CACHE_TTL,
    _TOKEN_FAILURE_LIMIT,
    _TOKEN_FAILURE_TTL_SEC,
    _TRANSIENT_PROVIDER_TTL_SEC,
    _XIANYUN_COOLDOWN_SEC,
    _XIANYUN_POLL_INTERVAL_SEC,
    _XIANYUN_TIMEOUT_SEC,
)
from nai.errors import GenerationProviderError

DATA_DIR = DeferredDataPath(lambda: data_dir())
TOKEN_PATH = DeferredDataPath(lambda: data_dir() / "nai_token.local.json")
GENERATED_DIR = DeferredDataPath(lambda: data_dir() / "generated")

_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}
_LAST_GEN_AT_BY_TOKEN: dict[str, float] = {}
# Slots currently inside generate (prevents wait_for_slot=False from blocking).
_ACTIVE_GEN_SLOTS: set[str] = set()
_ACTIVE_GEN_SLOTS_GUARD = threading.Lock()
_TOKEN_CURSOR = 0
_TOKEN_STATE_LOCK = threading.Lock()
_FILENAME_LOCK = threading.Lock()
_RESERVED_FILENAMES: set[str] = set()
_TOKEN_ENTRIES_CACHE: list[dict[str, Any]] | None = None
_TOKEN_ENTRIES_CACHE_AT: float = 0.0
_TOKEN_FAILURES: dict[str, dict[str, Any]] = {}
_TOKEN_VALIDATIONS: dict[str, dict[str, Any]] = {}
_ACTIVE_JOBS: dict[str, dict[str, Any]] = {}
_JOB: dict[str, Any] = {
    "status": "idle",
    "message": "",
    "active": [],
    "active_count": 0,
}

from nai.tokens import (
    _auth_headers,
    _candidate_token_entries,
    _check_one_token_entry,
    _clear_token_failure,
    _curl_config_quote,
    _curl_request_for_token_check,
    _disable_token_entry,
    _enabled_token_entries,
    _encrypt_token_payload,
    _exception_message,
    _guess_provider,
    _invalidate_token_cache,
    _is_token_temporarily_disabled,
    _legacy_save_provider,
    _mask_token,
    _next_token_entry,
    _normalize_token_entries,
    _parse_token_line,
    _parse_token_text,
    _probe_provider,
    _provider_key,
    _provider_label,
    _public_token_entry,
    _read_token_file,
    _record_token_failure,
    _remove_token_entry,
    _select_token_entry,
    _slot_cooldown_sec,
    _token_check_request,
    _token_disabled_until,
    _token_id,
    _write_token_entries,
    _xianyun_headers,
    add_token_entry,
    check_token_pool,
    delete_token_entry,
    generation_concurrency,
    generation_concurrency_for_batch,
    get_subscription,
    list_generation_slots,
    save_token,
    token_status,
)
from nai.jobs import (
    _clear_active_job,
    _cooldown_wait,
    _lock_for_token,
    _pick_available_token,
    _release_generated_filename,
    _reserve_generated_filename,
    _set_active_job,
    queue_status,
)
from nai.xianyun import (
    _as_list,
    _clean_none_values,
    _collect_xianyun_vibe_candidates,
    _first_present,
    _normalize_xianyun_vibe_config,
    _read_image_reference,
    _truthy_config,
    _xianyun_body_from_payload,
    _xianyun_raw_extra,
    _xianyun_vibe_payload,
)
from nai.generate import (
    _download_image_url,
    _generate_image_with_entry,
    _generate_novelai_png,
    _generate_xianyun_png,
    _raise_pre_request_transport_error,
    _retry_after_seconds,
    generate_image,
)
from nai.director import (
    _extract_png_from_zip,
    _extract_pngs_from_zip,
    call_nai_director,
    novelai_director_status,
)

__all__ = [
    "API_BASE",
    "DATA_DIR",
    "DIRECTOR_OUTPUT_MAX_BYTES",
    "DIRECTOR_OUTPUT_MAX_PIXELS",
    "DIRECTOR_RESPONSE_MAX_BYTES",
    "DIRECTOR_ZIP_MAX_ENTRIES",
    "GENERATED_DIR",
    "GenerationProviderError",
    "IMAGE_API_BASE",
    "PROVIDER_NOVELAI",
    "PROVIDER_UNKNOWN",
    "PROVIDER_XIANYUN",
    "TOKEN_PATH",
    "XIANYUN_API_BASE",
    "add_token_entry",
    "call_nai_director",
    "check_token_pool",
    "delete_token_entry",
    "generate_image",
    "generation_concurrency",
    "generation_concurrency_for_batch",
    "get_subscription",
    "list_generation_slots",
    "novelai_director_status",
    "queue_status",
    "save_token",
    "token_status",
]
