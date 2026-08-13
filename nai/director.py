"""NovelAI Director client and ZIP PNG extraction."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import mimetypes
import random
import re
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image, UnidentifiedImageError

from generated_gallery import register_generated, _group_key
from local_secrets import (
    PREFIX as SECRET_PREFIX,
    SecretProtectionUnavailable,
    protect_secret,
    unprotect_secret,
)
from atomic_io import atomic_write_text
from nai_char import build_generate_payload, prompt_snapshot_from_comment
from nai_prompt_profiles import apply_prompt_profile_to_comment
from usage_ledger import record_usage
from nai.constants import (
    PROVIDER_NOVELAI,
    PROVIDER_UNKNOWN,
    PROVIDER_XIANYUN,
)
from nai.errors import GenerationProviderError
from nai.facade import api


def novelai_director_status() -> dict[str, Any]:
    """Report local Director readiness without contacting the paid provider."""

    entries = [
        entry
        for entry in api._enabled_token_entries()
        if api._provider_key(str(entry.get("provider") or "")) == PROVIDER_NOVELAI
    ]
    return {
        "available": bool(entries),
        "slot_count": len(entries),
        "verified": False,
        "verified_slot_count": 0,
        "provider": PROVIDER_NOVELAI,
        "endpoint": f"{api.IMAGE_API_BASE}/ai/augment-image",
        "slots": [api._public_token_entry(entry) for entry in entries],
        "message": (
            "NovelAI Director slot configured"
            if entries
            else "NovelAI token is not configured for Director"
        ),
    }



async def call_nai_director(
    *,
    request: dict[str, Any],
    provenance: dict[str, Any] | None = None,
    token_id: str = "",
) -> dict[str, Any]:
    """Call NovelAI Director once with one fixed slot and bounded ZIP handling.

    Director requests can be billable.  A request that reached the provider is
    never failed over to another slot and is never automatically retried.
    """

    candidates = [
        entry
        for entry in api._candidate_token_entries(
            api._select_token_entry(token_id) if token_id else None
        )
        if api._provider_key(str(entry.get("provider") or "")) == PROVIDER_NOVELAI
    ]
    if not candidates:
        return {
            "ok": False,
            "error": "missing_token",
            "message": "NovelAI token is not configured for Director",
            "outputs": [],
            "retry_safe": True,
            "billing_uncertain": False,
        }

    entry = candidates[0]
    slot_id = str(entry.get("id") or "")
    slot_label = str(entry.get("label") or slot_id)
    lock = api._lock_for_token(slot_id)
    started_request = False
    async with lock:
        wait = api._cooldown_wait(slot_id, entry)
        if wait > 0:
            await asyncio.sleep(wait)
        api._set_active_job(
            slot_id,
            {
                "token_id": slot_id,
                "token_label": slot_label,
                "provider": PROVIDER_NOVELAI,
                "status": "running",
                "message": f"{slot_label} running NovelAI Director",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "work_id": None,
                "kind": "director",
            },
        )
        try:
            timeout = api.httpx.Timeout(240.0, connect=20.0)
            async with api.httpx.AsyncClient(timeout=timeout) as client:
                started_request = True
                async with client.stream(
                    "POST",
                    f"{api.IMAGE_API_BASE}/ai/augment-image",
                    headers=api._auth_headers(str(entry.get("token") or "")),
                    json=dict(request or {}),
                ) as response:
                    status = int(response.status_code)
                    content_length_raw = str(
                        (response.headers or {}).get("content-length") or ""
                    ).strip()
                    if content_length_raw:
                        try:
                            content_length = int(content_length_raw)
                        except ValueError:
                            content_length = 0
                        if content_length > api.DIRECTOR_RESPONSE_MAX_BYTES:
                            message = (
                                "NovelAI Director response exceeds the safe response limit"
                            )
                            api._record_token_failure(entry, message)
                            return {
                                "ok": False,
                                "error": "response_too_large",
                                "message": message,
                                "outputs": [],
                                "retry_safe": False,
                                "billing_uncertain": True,
                                "token_id": slot_id,
                                "token_label": slot_label,
                            }

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > api.DIRECTOR_RESPONSE_MAX_BYTES:
                            message = (
                                "NovelAI Director response exceeds the safe response limit"
                            )
                            api._record_token_failure(entry, message)
                            return {
                                "ok": False,
                                "error": "response_too_large",
                                "message": message,
                                "outputs": [],
                                "retry_safe": False,
                                "billing_uncertain": True,
                                "token_id": slot_id,
                                "token_label": slot_label,
                            }

                    if status >= 400:
                        text = bytes(body).decode("utf-8", errors="replace")[:500]
                        message = f"NAI Director API error {status}: {text}"
                        api._record_token_failure(entry, message)
                        definite_rejection = 400 <= status < 500
                        return {
                            "ok": False,
                            "error": (
                                "director_rejected"
                                if definite_rejection
                                else "director_failed"
                            ),
                            "message": message,
                            "outputs": [],
                            "retry_safe": definite_rejection,
                            "billing_uncertain": not definite_rejection,
                            "token_id": slot_id,
                            "token_label": slot_label,
                        }

            outputs = api._extract_pngs_from_zip(bytes(body))
            api._clear_token_failure(entry)
            return {
                "ok": True,
                "message": "NovelAI Director completed",
                "outputs": outputs,
                "usage": {
                    "anlas_spent": None,
                    "cost_source": "unknown",
                },
                "provenance": copy.deepcopy(provenance or {}),
                "token_id": slot_id,
                "token_label": slot_label,
                "provider": PROVIDER_NOVELAI,
                "retry_safe": False,
                "billing_uncertain": False,
            }
        except Exception as exc:
            message = f"NovelAI Director request failed: {exc}"
            api._record_token_failure(entry, message)
            return {
                "ok": False,
                "error": "director_failed",
                "message": message,
                "outputs": [],
                "retry_safe": False,
                "billing_uncertain": bool(started_request),
                "token_id": slot_id,
                "token_label": slot_label,
            }
        finally:
            if started_request:
                api._LAST_GEN_AT_BY_TOKEN[slot_id] = time.time()
            api._clear_active_job(slot_id)



def _extract_pngs_from_zip(data: bytes) -> list[dict[str, Any]]:
    """Extract every bounded, structurally valid PNG from a Director response."""

    outputs: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = [
                info
                for info in zf.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".png")
            ]
            if not infos:
                raise ValueError("NovelAI response zip did not contain a PNG")
            if len(infos) > api.DIRECTOR_ZIP_MAX_ENTRIES:
                raise ValueError("NovelAI Director response contains too many PNG entries")
            total_size = sum(max(0, int(info.file_size)) for info in infos)
            if total_size > api.DIRECTOR_RESPONSE_MAX_BYTES:
                raise ValueError("NovelAI Director PNG output exceeds the safe response limit")

            for info in infos:
                if int(info.file_size) > api.DIRECTOR_OUTPUT_MAX_BYTES:
                    raise ValueError("NovelAI Director PNG exceeds the per-output limit")
                raw = zf.read(info)
                if (
                    len(raw) > api.DIRECTOR_OUTPUT_MAX_BYTES
                    or not raw.startswith(b"\x89PNG\r\n\x1a\n")
                ):
                    raise ValueError(f"invalid PNG in Director response: {info.filename}")
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format != "PNG":
                            raise ValueError(
                                f"invalid PNG in Director response: {info.filename}"
                            )
                        width, height = image.size
                        image.verify()
                    if (
                        width <= 0
                        or height <= 0
                        or width * height > api.DIRECTOR_OUTPUT_MAX_PIXELS
                    ):
                        raise ValueError(
                            f"invalid PNG dimensions in Director response: {info.filename}"
                        )
                except (UnidentifiedImageError, OSError, SyntaxError) as exc:
                    raise ValueError(
                        f"invalid PNG in Director response: {info.filename}"
                    ) from exc
                outputs.append(
                    {
                        "archive_name": Path(info.filename).name,
                        "bytes": raw,
                        "width": int(width),
                        "height": int(height),
                    }
                )
    except zipfile.BadZipFile as exc:
        raise ValueError("NovelAI Director response is not a valid ZIP") from exc
    return outputs



def _extract_png_from_zip(data: bytes) -> bytes:
    """Extract one provider image while retaining the legacy generation contract.

    Director responses use ``_extract_pngs_from_zip`` and receive full Pillow
    verification.  The regular generation endpoint historically accepted valid
    PNG-framed payloads from NovelAI even when ancillary chunk checksums were
    non-canonical, so keep that compatibility path bounded but signature-based.
    """

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = [
                info
                for info in zf.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".png")
            ]
            if not infos:
                raise ValueError("NovelAI response zip did not contain a PNG")
            info = infos[0]
            if int(info.file_size) > api.DIRECTOR_OUTPUT_MAX_BYTES:
                raise ValueError("NovelAI PNG exceeds the safe response limit")
            raw = zf.read(info)
            if (
                len(raw) > api.DIRECTOR_OUTPUT_MAX_BYTES
                or not raw.startswith(b"\x89PNG\r\n\x1a\n")
            ):
                raise ValueError("NovelAI response did not contain a valid PNG payload")
            return raw
    except zipfile.BadZipFile as exc:
        raise ValueError("NovelAI response is not a valid ZIP") from exc

