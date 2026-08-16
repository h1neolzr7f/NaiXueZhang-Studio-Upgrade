"""NovelAI and 闲云 image generation."""

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


async def _download_image_url(client: api.httpx.AsyncClient, image_url: str) -> bytes:
    from network_safety import validate_image_download_url

    safe_url = validate_image_download_url(image_url)
    resp = await client.get(
        safe_url,
        headers={
            "User-Agent": api._xianyun_headers("placeholder")["User-Agent"],
            "Referer": "https://nai3.idlecloud.cc/",
        },
        follow_redirects=False,
    )
    resp.raise_for_status()
    return resp.content



def _retry_after_seconds(response: api.httpx.Response) -> float:
    raw = str((response.headers or {}).get("Retry-After") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0



def _raise_pre_request_transport_error(exc: BaseException) -> None:
    raise GenerationProviderError(
        f"TLS/connect failed before request was sent: {exc}",
        retry_safe=True,
        billing_uncertain=False,
        request_attempted=False,
        error_code="connect_failed",
    ) from exc



async def _generate_novelai_png(
    client: api.httpx.AsyncClient,
    token_entry: dict[str, Any],
    body: dict[str, Any],
) -> bytes:
    try:
        resp = await client.post(
            f"{api.IMAGE_API_BASE}/ai/generate-image",
            headers=api._auth_headers(str(token_entry.get("token") or "")),
            json=body,
        )
    except (api.httpx.ConnectError, api.httpx.ConnectTimeout, api.httpx.PoolTimeout) as exc:
        api._raise_pre_request_transport_error(exc)
    except api.httpx.TimeoutException as exc:
        raise GenerationProviderError(
            f"NAI request timed out after send: {exc}",
            retry_safe=False,
            billing_uncertain=True,
            request_attempted=True,
            error_code="billing_uncertain",
        ) from exc
    if resp.status_code == 401:
        raise GenerationProviderError(
            "Token invalid or expired",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=True,
            error_code="provider_unavailable",
        )
    if resp.status_code == 429:
        wait = api._retry_after_seconds(resp)
        raise GenerationProviderError(
            "Request too frequent; please retry later",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=False,
            wait=wait,
            error_code="rate_limited",
        )
    if resp.status_code >= 500:
        raise GenerationProviderError(
            f"NAI API error {resp.status_code}: {resp.text[:500]}",
            retry_safe=False,
            billing_uncertain=True,
            request_attempted=True,
            error_code="http_5xx",
        )
    if resp.status_code >= 400:
        text = resp.text[:500]
        raise GenerationProviderError(
            f"NAI API error {resp.status_code}: {text}",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=True,
            error_code="generate_failed",
        )
    return api._extract_png_from_zip(resp.content)



async def _generate_xianyun_png(
    client: api.httpx.AsyncClient,
    token_entry: dict[str, Any],
    payload_info: dict[str, Any],
    body: dict[str, Any],
    *,
    patched_comment: dict[str, Any] | None = None,
    slot_id: str,
    slot_label: str,
    work_id: int | None,
) -> bytes:
    api_base = str(token_entry.get("api_base") or api.XIANYUN_API_BASE).rstrip("/")
    req_body = api._clean_none_values(api._xianyun_body_from_payload(payload_info, body, patched_comment))
    try:
        submit = await client.post(
            f"{api_base}/generate_image",
            headers=api._xianyun_headers(str(token_entry.get("token") or "")),
            json=req_body,
        )
    except (api.httpx.ConnectError, api.httpx.ConnectTimeout, api.httpx.PoolTimeout) as exc:
        api._raise_pre_request_transport_error(exc)
    except api.httpx.TimeoutException as exc:
        raise GenerationProviderError(
            f"Xianyun request timed out after send: {exc}",
            retry_safe=False,
            billing_uncertain=True,
            request_attempted=True,
            error_code="billing_uncertain",
        ) from exc
    if submit.status_code == 401:
        raise GenerationProviderError(
            "Xianyun API key invalid or expired",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=True,
            error_code="provider_unavailable",
        )
    if submit.status_code == 403:
        raise GenerationProviderError(
            f"Xianyun account forbidden or banned: {submit.text[:300]}",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=True,
            error_code="generate_failed",
        )
    if submit.status_code == 429:
        wait = api._retry_after_seconds(submit)
        raise GenerationProviderError(
            f"Xianyun request too frequent: {submit.text[:300]}",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=False,
            wait=wait,
            error_code="rate_limited",
        )
    if submit.status_code >= 500:
        raise GenerationProviderError(
            f"Xianyun API error {submit.status_code}: {submit.text[:500]}",
            retry_safe=False,
            billing_uncertain=True,
            request_attempted=True,
            error_code="http_5xx",
        )
    if submit.status_code >= 400:
        raise GenerationProviderError(
            f"Xianyun API error {submit.status_code}: {submit.text[:500]}",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=True,
            error_code="generate_failed",
        )
    data = submit.json()
    job_id = str(data.get("job_id") or "")
    if not job_id:
        raise ValueError(f"Xianyun response missing job_id: {str(data)[:300]}")

    deadline = time.time() + api._XIANYUN_TIMEOUT_SEC
    queue_position = data.get("queue_position")
    while time.time() < deadline:
        api._set_active_job(
            slot_id,
            {
                "token_id": slot_id,
                "token_label": slot_label,
                "provider": PROVIDER_XIANYUN,
                "status": "queued" if queue_position else "running",
                "message": f"{slot_label} Xianyun job {job_id[:8]} polling",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "work_id": work_id,
                "remote_job_id": job_id,
                "queue_position": queue_position,
            },
        )
        await asyncio.sleep(api._XIANYUN_POLL_INTERVAL_SEC)
        poll = await client.get(
            f"{api_base}/get_result/{quote(job_id, safe='')}",
            headers=api._xianyun_headers(str(token_entry.get("token") or "")),
        )
        if poll.status_code == 429:
            await asyncio.sleep(api._XIANYUN_POLL_INTERVAL_SEC)
            continue
        if poll.status_code >= 400:
            raise GenerationProviderError(
                f"Xianyun result error {poll.status_code}: {poll.text[:500]}",
                retry_safe=False,
                billing_uncertain=True,
            )
        result = poll.json()
        status = str(result.get("status") or "")
        queue_position = result.get("queue_position")
        if status == "completed":
            if result.get("image_base64"):
                raw = str(result["image_base64"])
                if "," in raw and raw.lower().startswith("data:image"):
                    raw = raw.split(",", 1)[1]
                return base64.b64decode(raw)
            image_url = str(result.get("image_url") or "")
            if not image_url:
                raise ValueError(f"Xianyun completed without image_url: {str(result)[:300]}")
            return await api._download_image_url(client, image_url)
        if status == "failed":
            raise GenerationProviderError(
                f"Xianyun generation failed: {str(result)[:500]}",
                retry_safe=False,
                billing_uncertain=True,
            )
    raise TimeoutError("Xianyun generation timed out")



async def generate_image(
    patched_comment: dict[str, Any],
    *,
    work_id: int | None = None,
    source_gallery_id: str = "site",
    force_free: bool = True,
    prompt_profile: str = "native",
    token_id: str = "",
    wait_for_slot: bool = False,
    generation_series_id: str = "",
    source_title: str = "",
    source_thumb: str = "",
    remote_work_id: str = "",
    paid_authorized: bool = False,
) -> dict[str, Any]:
    if api._JOB.get("status") == "error":
        api._JOB.update({"status": "idle", "message": "idle"})

    profiled_comment, profile_info = apply_prompt_profile_to_comment(
        patched_comment,
        prompt_profile,
    )
    payload_info = build_generate_payload(profiled_comment, force_free=force_free)
    if not payload_info.get("free_eligible") and not paid_authorized:
        return {
            "ok": False,
            "error": "authorization_required",
            "message": "非免费请求需要有效的一次性服务端授权票据",
            "request_attempted": False,
            "retry_safe": True,
            "billing_uncertain": False,
            "free_eligible": False,
        }

    try:
        if token_id:
            token_entry = api._select_token_entry(token_id)
        elif wait_for_slot:
            token_entry = api._next_token_entry()
        else:
            token_entry, blocked_reason, wait, _provider = api._pick_available_token()
            if token_entry is None:
                if blocked_reason == "cooldown":
                    return {
                        "ok": False,
                        "error": "cooldown",
                        "message": f"NAI token pool cooling down; retry in {round(wait, 1)}s",
                        "queue": api.queue_status(),
                        "provider": _provider,
                        "wait": wait,
                    }
                return {
                    "ok": False,
                    "error": "busy",
                    "message": "No idle NAI token slot; please wait",
                    "queue": api.queue_status(),
                    "provider": _provider,
                }
    except ValueError as exc:
        return {
            "ok": False,
            "error": "missing_token",
            "message": str(exc),
            "queue": api.queue_status(),
        }

    params = {
        k: v
        for k, v in (payload_info["parameters"] or {}).items()
        if v is not None
    }
    body = {
        "input": payload_info["input"],
        "model": payload_info["model"],
        "action": payload_info["action"],
        "parameters": params,
        # 本项目只使用 NovelAI 会员号（Opus/Scroll/Tablet）。会员免费标准
        # 由 build_generate_payload 的尺寸/步数裁剪保证（≤1024×1024、≤28 steps
        # 单张生成不扣 Anlas）。因此始终走订阅通道（use_new_shared_trial=false）：
        # shared trial 是给未订阅账号的，且不完整支持 v4 char_caption，
        # 会导致发色/角色特征在生成时丢失。
        "use_new_shared_trial": False,
    }

    last_failure: dict[str, Any] | None = None
    for attempt_entry in api._candidate_token_entries(token_entry):
        token_entry = attempt_entry
        slot_id = str(token_entry.get("id") or "")
        slot_label = str(token_entry.get("label") or slot_id)
        provider = api._provider_key(str(token_entry.get("provider") or PROVIDER_NOVELAI))
        with api._ACTIVE_GEN_SLOTS_GUARD:
            busy = slot_id in api._ACTIVE_GEN_SLOTS
            if busy and not wait_for_slot:
                last_failure = {
                    "ok": False,
                    "error": "busy",
                    "message": f"{slot_label} is busy",
                    "queue": api.queue_status(),
                }
                continue
            api._ACTIVE_GEN_SLOTS.add(slot_id)
        try:
            result = await api._generate_image_with_entry(
                token_entry,
                profiled_comment,
                profile_info,
                payload_info,
                body,
                work_id=work_id,
                source_gallery_id=source_gallery_id,
                wait_for_slot=wait_for_slot,
                generation_series_id=generation_series_id,
                source_title=source_title,
                source_thumb=source_thumb,
                remote_work_id=remote_work_id,
            )
        finally:
            with api._ACTIVE_GEN_SLOTS_GUARD:
                api._ACTIVE_GEN_SLOTS.discard(slot_id)
        if result.get("ok"):
            usage = result.get("usage")
            if not isinstance(usage, dict):
                usage = {
                    "anlas_spent": None,
                    "cost_source": "unknown",
                }
                result["usage"] = usage
            api.record_usage(
                kind="image_generation",
                provider=str(result.get("provider") or provider),
                model=str(result.get("model") or payload_info.get("model") or ""),
                images=1,
                anlas_spent=usage.get("anlas_spent"),
                cost_source=str(usage.get("cost_source") or "unknown"),
            )
            return result
        last_failure = result
        if not result.get("provider"):
            result["provider"] = provider
        # Paid POST: only fail over when the request was not billable
        # (invalid token / pre-request TLS). HTTP 5xx must not hop slots.
        if (
            result.get("retry_safe")
            and not result.get("billing_uncertain")
            and result.get("error") == "provider_unavailable"
        ):
            continue
        return result

    return last_failure or {
        "ok": False,
        "error": "missing_token",
        "message": "No usable generation provider is available",
        "queue": api.queue_status(),
    }



async def _generate_image_with_entry(
    token_entry: dict[str, Any],
    profiled_comment: dict[str, Any],
    profile_info: dict[str, Any],
    payload_info: dict[str, Any],
    body: dict[str, Any],
    *,
    work_id: int | None,
    source_gallery_id: str = "site",
    wait_for_slot: bool,
    generation_series_id: str = "",
    source_title: str = "",
    source_thumb: str = "",
    remote_work_id: str = "",
) -> dict[str, Any]:
    slot_id = str(token_entry.get("id") or "")
    slot_label = str(token_entry.get("label") or slot_id)
    provider = api._provider_key(str(token_entry.get("provider") or PROVIDER_NOVELAI))
    lock = api._lock_for_token(slot_id)
    request_started = False
    async with lock:
        wait = api._cooldown_wait(slot_id, token_entry)
        if wait > 0 and not wait_for_slot:
            return {
                "ok": False,
                "error": "cooldown",
                "message": f"{slot_label} cooling down; retry in {round(wait, 1)}s",
                "queue": api.queue_status(),
                "provider": provider,
                "wait": wait,
            }
        if wait > 0:
            api._set_active_job(
                slot_id,
                {
                    "token_id": slot_id,
                    "token_label": slot_label,
                    "provider": provider,
                    "status": "cooldown",
                    "message": f"{slot_label} cooldown {round(wait, 1)}s",
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                    "work_id": work_id,
                },
            )
            await asyncio.sleep(wait)

        api._set_active_job(
            slot_id,
            {
                "token_id": slot_id,
                "token_label": slot_label,
                "provider": provider,
                "status": "running",
                "message": f"{slot_label} requesting {api._provider_label(provider)}...",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "work_id": work_id,
            },
        )
        try:
            client_kwargs: dict[str, Any] = {"timeout": 300.0}
            if token_entry.get("proxy"):
                client_kwargs["proxy"] = str(token_entry.get("proxy") or "")
            async with api.httpx.AsyncClient(**client_kwargs) as client:
                if provider == PROVIDER_XIANYUN:
                    png_bytes = await api._generate_xianyun_png(
                        client,
                        token_entry,
                        payload_info,
                        body,
                        patched_comment=profiled_comment,
                        slot_id=slot_id,
                        slot_label=slot_label,
                        work_id=work_id,
                    )
                else:
                    png_bytes = await api._generate_novelai_png(client, token_entry, body)
            api.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            filename = api._reserve_generated_filename(work_id)
            out_path = api.GENERATED_DIR / filename
            try:
                from atomic_io import atomic_write_bytes

                atomic_write_bytes(out_path, png_bytes)
            except Exception:
                out_path.write_bytes(png_bytes)
            finally:
                api._release_generated_filename(filename)
            register_warning = ""
            try:
                aitag_meta = (
                    profiled_comment.get("_aitag_source")
                    if isinstance(profiled_comment, dict)
                    else None
                )
                if not isinstance(aitag_meta, dict):
                    aitag_meta = {}
                title = str(
                    source_title or aitag_meta.get("title") or ""
                ).strip()
                thumb = str(
                    source_thumb or aitag_meta.get("thumb") or ""
                ).strip()
                remote_id = str(
                    remote_work_id or aitag_meta.get("work_id") or work_id or ""
                ).strip()
                register_generated(
                    filename,
                    work_id=work_id,
                    source_gallery_id=source_gallery_id,
                    model=str(payload_info.get("model") or ""),
                    width=payload_info.get("width"),
                    height=payload_info.get("height"),
                    steps=payload_info.get("steps"),
                    free_eligible=payload_info.get("free_eligible"),
                    prompt_snapshot={
                        **prompt_snapshot_from_comment(profiled_comment),
                        "prompt_profile": profile_info,
                        "generation_provider": provider,
                    },
                    generation_series_id=generation_series_id,
                    source_title=title,
                    source_thumb=thumb,
                    remote_work_id=remote_id,
                )
            except Exception as exc:
                register_warning = f"metadata registration failed: {exc}"

            try:
                from post_pipeline import load_config as load_pipe_config
                from post_pipeline import schedule_auto_pipeline

                schedule_auto_pipeline(filename)
                pipe_cfg = load_pipe_config()
                pipeline_queued = bool(pipe_cfg.get("auto_after_generate"))
            except Exception:
                pipeline_queued = False

            api._LAST_GEN_AT_BY_TOKEN[slot_id] = time.time()
            # Must match register_generated / generated_gallery._group_key
            # (non-site galleries use gallery:{id}:{base}).
            group_id = _group_key(
                work_id,
                source_gallery_id=str(source_gallery_id or "site"),
                generation_series_id=str(generation_series_id or "").strip(),
            )
            result = {
                "ok": True,
                "message": "Image generated",
                "image_url": f"/data/generated/{filename}",
                "filename": filename,
                "group_id": group_id,
                "gallery_url": f"/generated?g={group_id}",
                "free_eligible": payload_info.get("free_eligible"),
                "resized_for_free": payload_info.get("resized_for_free"),
                "width": payload_info.get("width"),
                "height": payload_info.get("height"),
                "steps": payload_info.get("steps"),
                "model": payload_info.get("model"),
                "provider": provider,
                "source_gallery_id": str(source_gallery_id or "site"),
                "prompt_profile": profile_info,
                "token_id": slot_id,
                "token_label": slot_label,
                "pool_concurrency": api.generation_concurrency(),
                "usage": {
                    "anlas_spent": None,
                    "cost_source": "unknown",
                },
                "request_attempted": True,
                "retry_safe": False,
                "billing_uncertain": False,
            }
            if pipeline_queued:
                result["pipeline_queued"] = True
                result["pipeline_message"] = "Post pipeline queued"
            if register_warning:
                result["register_warning"] = register_warning
            api._clear_token_failure(token_entry)
            api._clear_active_job(slot_id, result=result)
            return result
        except Exception as exc:
            message = api._exception_message(exc)
            failed_provider = api._record_token_failure(token_entry, message)
            api._clear_active_job(slot_id, error=message)
            wait = 0.0
            error_code = ""
            if isinstance(exc, GenerationProviderError):
                retry_safe = exc.retry_safe
                billing_uncertain = exc.billing_uncertain
                request_started = bool(exc.request_attempted)
                wait = float(exc.wait or 0.0)
                error_code = str(exc.error_code or "")
            elif isinstance(
                exc,
                (api.httpx.ConnectError, api.httpx.ConnectTimeout, api.httpx.PoolTimeout),
            ):
                retry_safe = True
                billing_uncertain = False
                request_started = False
                error_code = "connect_failed"
            else:
                retry_safe = False
                billing_uncertain = True
                request_started = True
                error_code = "billing_uncertain"
            if not error_code:
                error_code = (
                    "billing_uncertain"
                    if billing_uncertain
                    else "provider_unavailable" if failed_provider else "generate_failed"
                )
            result = {
                "ok": False,
                "error": error_code,
                "message": message,
                "token_id": slot_id,
                "token_label": slot_label,
                "provider": provider,
                "fallback_available": bool(failed_provider and retry_safe and not billing_uncertain),
                "request_attempted": bool(request_started),
                "retry_safe": bool(retry_safe),
                "billing_uncertain": bool(billing_uncertain),
                "queue": api.queue_status(),
            }
            if wait > 0:
                result["wait"] = wait
            return result
        finally:
            # 安全清理：如果 slot 仍然在 _ACTIVE_JOBS 中（return 前未清除），
            # 说明是异常退出或中途返回遗漏了清理。正常路径已在 _clear_active_job 中移除。
            if slot_id in api._ACTIVE_JOBS:
                api._clear_active_job(slot_id)

