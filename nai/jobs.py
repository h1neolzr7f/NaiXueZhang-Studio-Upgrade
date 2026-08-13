"""Generation queue, slot locks, and output filename reservation."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from nai.constants import PROVIDER_NOVELAI
from nai.facade import api


def queue_status() -> dict[str, Any]:
    with api._TOKEN_STATE_LOCK:
        job = dict(api._JOB)
        job["active"] = list(api._ACTIVE_JOBS.values())
        job["active_count"] = len(api._ACTIVE_JOBS)
        if api._ACTIVE_JOBS:
            job["status"] = "running"
        return job



def _lock_for_token(token_id: str) -> asyncio.Lock:
    lock = api._TOKEN_LOCKS.get(token_id)
    if lock is None:
        lock = asyncio.Lock()
        api._TOKEN_LOCKS[token_id] = lock
    return lock



def _cooldown_wait(token_id: str, entry: dict[str, Any] | None = None) -> float:
    last = float(api._LAST_GEN_AT_BY_TOKEN.get(token_id) or 0.0)
    cooldown = api._slot_cooldown_sec(entry or {})
    return max(0.0, cooldown - (time.time() - last))



def _pick_available_token() -> tuple[dict[str, Any] | None, str, float, str]:
    entries = api._enabled_token_entries()
    if not entries:
        raise ValueError("NovelAI token is not configured")
    best_cooldown: tuple[dict[str, Any], float] | None = None
    best_disabled_wait = 0.0
    start = api._TOKEN_CURSOR % len(entries)
    for offset in range(len(entries)):
        idx = (start + offset) % len(entries)
        entry = entries[idx]
        token_id = str(entry["id"])
        disabled_until = api._token_disabled_until(token_id)
        if disabled_until > time.time():
            disabled_wait = max(0.0, disabled_until - time.time())
            if best_disabled_wait <= 0 or disabled_wait < best_disabled_wait:
                best_disabled_wait = disabled_wait
            continue
        if api._lock_for_token(token_id).locked():
            continue
        wait = api._cooldown_wait(token_id, entry)
        if wait <= 0:
            api._TOKEN_CURSOR = (idx + 1) % len(entries)
            return entry, "", 0.0, api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
        if best_cooldown is None or wait < best_cooldown[1]:
            best_cooldown = (entry, wait)
    if best_cooldown is not None:
        return None, "cooldown", best_cooldown[1], api._provider_key(str(best_cooldown[0].get("provider") or PROVIDER_NOVELAI))
    if best_disabled_wait > 0:
        return None, "cooldown", best_disabled_wait, PROVIDER_NOVELAI
    return None, "busy", 0.0, PROVIDER_NOVELAI



def _set_active_job(token_id: str, payload: dict[str, Any]) -> None:
    with api._TOKEN_STATE_LOCK:
        api._ACTIVE_JOBS[token_id] = dict(payload)
        api._JOB.update(
            {
                "status": "running",
                "message": str(payload.get("message") or "Requesting NovelAI..."),
                "started_at": payload.get("started_at") or datetime.now().isoformat(timespec="seconds"),
                "work_id": payload.get("work_id"),
                "active": list(api._ACTIVE_JOBS.values()),
                "active_count": len(api._ACTIVE_JOBS),
            }
        )



def _clear_active_job(token_id: str, *, result: dict[str, Any] | None = None, error: str = "") -> None:
    with api._TOKEN_STATE_LOCK:
        api._ACTIVE_JOBS.pop(token_id, None)
        if result:
            api._JOB["last_result"] = result
        if error:
            api._JOB["last_error"] = error
            api._JOB["error_at"] = datetime.now().isoformat(timespec="seconds")
        api._JOB["active"] = list(api._ACTIVE_JOBS.values())
        api._JOB["active_count"] = len(api._ACTIVE_JOBS)
        if api._ACTIVE_JOBS:
            active = next(iter(api._ACTIVE_JOBS.values()))
            api._JOB["status"] = "running"
            api._JOB["message"] = str(active.get("message") or "Requesting NovelAI...")
            api._JOB["work_id"] = active.get("work_id")
        elif error:
            api._JOB["status"] = "error"
            api._JOB["message"] = error
            api._JOB["work_id"] = None
        else:
            api._JOB["status"] = "idle"
            api._JOB["message"] = "idle"
            api._JOB["work_id"] = None



def _reserve_generated_filename(work_id: int | None) -> str:
    suffix = f"_{work_id}" if work_id else ""
    with api._FILENAME_LOCK:
        start = datetime.now()
        for offset in range(180):
            ts = (start + timedelta(seconds=offset)).strftime("%Y%m%d_%H%M%S")
            filename = f"{ts}{suffix}.png"
            if filename in api._RESERVED_FILENAMES:
                continue
            if (api.GENERATED_DIR / filename).exists():
                continue
            api._RESERVED_FILENAMES.add(filename)
            return filename
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000)}{suffix}.png"



def _release_generated_filename(filename: str) -> None:
    name = str(filename or "").strip()
    if not name:
        return
    with api._FILENAME_LOCK:
        api._RESERVED_FILENAMES.discard(name)

