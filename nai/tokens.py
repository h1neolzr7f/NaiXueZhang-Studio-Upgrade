"""Token pool, persistence, probes, and subscription."""

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


def _curl_config_quote(value: Any) -> str:
    text = str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'



def _curl_request_for_token_check(
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    json_body: dict[str, Any] | None = None,
    timeout_sec: float = 10.0,
    proxy: str = "",
) -> tuple[int, str]:
    exe = api.shutil.which("curl.exe") or api.shutil.which("curl")
    if not exe:
        raise FileNotFoundError("curl executable not found")
    marker = "\n__AITAG_HTTP_STATUS__:"
    config = [
        f"url = {api._curl_config_quote(url)}",
        f"request = {api._curl_config_quote(method.upper())}",
    ]
    for key, value in headers.items():
        config.append(f"header = {api._curl_config_quote(f'{key}: {value}')}")
    cmd = [
        exe,
        "--config",
        "-",
        "--silent",
        "--show-error",
        "--max-time",
        str(max(1.0, float(timeout_sec))),
        "--write-out",
        f"{marker}%{{http_code}}",
    ]
    if str(proxy or "").strip():
        cmd.extend(["--proxy", str(proxy).strip()])
    if json_body is not None:
        cmd.extend(["--data-raw", json.dumps(json_body, ensure_ascii=False)])
    completed = api.subprocess.run(
        cmd,
        input="\n".join(config) + "\n",
        text=True,
        capture_output=True,
        timeout=max(2.0, float(timeout_sec) + 2.0),
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "curl request failed").strip())
    output = completed.stdout or ""
    if marker not in output:
        raise RuntimeError("curl response missing HTTP status")
    body, status_text = output.rsplit(marker, 1)
    try:
        status = int(status_text.strip()[:3])
    except ValueError as exc:
        raise RuntimeError(f"curl response invalid HTTP status: {status_text[:20]}") from exc
    return status, body



def _token_check_request(
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    json_body: dict[str, Any] | None = None,
    timeout_sec: float = 10.0,
    proxy: str = "",
) -> tuple[int, str]:
    try:
        return api._curl_request_for_token_check(
            method,
            url,
            headers,
            json_body=json_body,
            timeout_sec=timeout_sec,
            proxy=proxy,
        )
    except FileNotFoundError:
        pass
    timeout = api.httpx.Timeout(timeout_sec, connect=min(4.0, timeout_sec))
    with api.httpx.Client(timeout=timeout, proxy=str(proxy or "").strip() or None) as client:
        resp = client.request(method, url, headers=headers, json=json_body)
    return resp.status_code, resp.text



def _read_token_file() -> dict[str, Any]:
    if not api.TOKEN_PATH.exists():
        return {}
    try:
        data = json.loads(api.TOKEN_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return {}
        migrated = False
        decoded = copy.deepcopy(data)
        if decoded.get("token"):
            raw = str(decoded["token"])
            decoded["token"] = unprotect_secret(raw)
            if raw and not raw.startswith(SECRET_PREFIX):
                try:
                    data["token"] = protect_secret(raw)
                    migrated = True
                except SecretProtectionUnavailable:
                    pass
        for index, entry in enumerate(decoded.get("tokens") or []):
            if not isinstance(entry, dict) or not entry.get("token"):
                continue
            raw = str(entry["token"])
            entry["token"] = unprotect_secret(raw)
            if raw and not raw.startswith(SECRET_PREFIX):
                try:
                    data["tokens"][index]["token"] = protect_secret(raw)
                    migrated = True
                except SecretProtectionUnavailable:
                    pass
        if migrated:
            encrypted = api._encrypt_token_payload(data)
            atomic_write_text(api.TOKEN_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2) + "\n")
        return decoded
    except Exception:
        return {}



def _provider_key(provider: str) -> str:
    raw = str(provider or "").strip().lower().replace("-", "_")
    if raw in {"xy", "idlecloud", "xianyun_api"}:
        return PROVIDER_XIANYUN
    if raw == PROVIDER_XIANYUN:
        return PROVIDER_XIANYUN
    if raw == PROVIDER_UNKNOWN:
        return PROVIDER_UNKNOWN
    return PROVIDER_NOVELAI



def _provider_label(provider: str) -> str:
    key = api._provider_key(provider)
    if key == PROVIDER_XIANYUN:
        return "Xianyun"
    if key == PROVIDER_UNKNOWN:
        return "Unknown"
    return "NAI"



def _token_id(token: str, provider: str = PROVIDER_NOVELAI) -> str:
    prefix = "xianyun" if api._provider_key(provider) == PROVIDER_XIANYUN else "nai"
    digest = hashlib.sha1(f"{prefix}:{str(token or '')}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"



def _mask_token(token: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    if len(raw) <= 10:
        return "*" * len(raw)
    # 只保留类型前缀（如 pst-），不回显尾部，避免拼接爆破
    prefix = raw[:4] if re.match(r"^[A-Za-z0-9\-_]{4}", raw) else ""
    return f"{prefix}{'*' * 8}"



def _parse_token_text(raw: str) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith(("[", "{")):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]

    seen: set[str] = set()
    tokens: list[Any] = []
    splitter = r"[\n;]+" if "{" in text else r"[\n,;]+"
    for part in re.split(splitter, text):
        token = part.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens



def _guess_provider(token: str) -> str:
    raw = str(token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw.split(None, 1)[1].strip()
    if raw.startswith("pst-"):
        return PROVIDER_NOVELAI
    if raw.lower().startswith(("xianyun:", "xy:", "idlecloud:")):
        return PROVIDER_XIANYUN
    if re.fullmatch(r"[A-Za-z0-9_-]{32,}", raw):
        return PROVIDER_XIANYUN
    return PROVIDER_UNKNOWN



def _legacy_save_provider(provider: str, token: str) -> str:
    """Bulk save keeps legacy bare NovelAI tokens usable without slow probing.

    `add_token_entry` is the strict path and still probes/rejects unknown
    providers. `save_token` is the backwards-compatible bulk paste path used by
    old installs and tests: short opaque tokens such as `token-alpha` used to be
    treated as NovelAI slots. Long bare keys are still classified as Xianyun by
    `_guess_provider`.
    """
    key = api._provider_key(str(provider or PROVIDER_UNKNOWN))
    if key != PROVIDER_UNKNOWN:
        return key
    guessed = api._guess_provider(token)
    if guessed != PROVIDER_UNKNOWN:
        return guessed
    return PROVIDER_NOVELAI



def _parse_token_line(raw: Any, idx: int) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        token = str(raw.get("token") or raw.get("api_key") or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(None, 1)[1].strip()
        provider = api._provider_key(str(raw.get("provider") or raw.get("type") or api._guess_provider(token)))
        label = str(raw.get("label") or f"{api._provider_label(provider)} #{idx + 1}").strip()
        if not token:
            return None
        return {
            "id": str(raw.get("id") or api._token_id(token, provider)).strip(),
            "label": label,
            "provider": provider,
            "token": token,
            "enabled": raw.get("enabled") is not False,
            "api_base": str(raw.get("api_base") or raw.get("base_url") or "").strip(),
            "proxy": str(raw.get("proxy") or "").strip(),
        }

    text = str(raw or "").strip()
    if not text:
        return None
    provider = ""
    label = ""
    token = text
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            obj = {}
        if isinstance(obj, dict):
            token = str(obj.get("token") or obj.get("api_key") or "").strip()
            provider = api._provider_key(str(obj.get("provider") or obj.get("type") or api._guess_provider(token)))
            label = str(obj.get("label") or "").strip()
            api_base = str(obj.get("api_base") or obj.get("base_url") or "").strip()
            proxy = str(obj.get("proxy") or "").strip()
        else:
            api_base = ""
            proxy = ""
    else:
        api_base = ""
        proxy = ""
        match = re.match(r"^(?P<prefix>xianyun|xy|idlecloud|novelai|nai)\s*:\s*(?P<token>.+)$", text, re.I)
        if match:
            provider = api._provider_key(match.group("prefix"))
            token = match.group("token").strip()
        else:
            provider = api._guess_provider(token)
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1].strip()
    if not token:
        return None
    provider = api._provider_key(provider or api._guess_provider(token))
    label = label or f"{api._provider_label(provider)} #{idx + 1}"
    return {
        "id": api._token_id(token, provider),
        "label": label,
        "provider": provider,
        "token": token,
        "enabled": True,
        "api_base": api_base,
        "proxy": proxy,
    }



def _normalize_token_entries(data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = data if isinstance(data, dict) else api._read_token_file()
    raw_entries: list[Any] = []
    if isinstance(data.get("tokens"), list):
        raw_entries.extend(data.get("tokens") or [])
    elif data.get("token"):
        raw_entries.append(
            {
                "token": data.get("token"),
                "label": data.get("label") or "NAI #1",
                "enabled": True,
                "updated_at": data.get("updated_at", ""),
            }
        )

    seen: set[str] = set()
    entries: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_entries):
        if isinstance(raw, dict):
            token = str(raw.get("token") or "").strip()
            if token.lower().startswith("bearer "):
                token = token.split(None, 1)[1].strip()
            provider = api._provider_key(str(raw.get("provider") or api._guess_provider(token)))
            label = (
                str(raw.get("label") or f"{api._provider_label(provider)} #{idx + 1}").strip()
                or f"{api._provider_label(provider)} #{idx + 1}"
            )
            enabled = raw.get("enabled") is not False
            updated_at = str(raw.get("updated_at") or data.get("updated_at") or "")
            entry_id = str(raw.get("id") or api._token_id(token, provider)).strip()
            api_base = str(raw.get("api_base") or raw.get("base_url") or "").strip()
            proxy = str(raw.get("proxy") or "").strip()
        else:
            parsed = api._parse_token_line(str(raw or ""), idx)
            if not parsed:
                continue
            token = str(parsed.get("token") or "").strip()
            provider = api._provider_key(str(parsed.get("provider") or api._guess_provider(token)))
            label = str(parsed.get("label") or f"{api._provider_label(provider)} #{idx + 1}")
            enabled = True
            updated_at = str(data.get("updated_at") or "")
            entry_id = str(parsed.get("id") or api._token_id(token, provider))
            api_base = str(parsed.get("api_base") or "").strip()
            proxy = str(parsed.get("proxy") or "").strip()
        dedupe_key = f"{provider}:{token}"
        if not token or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(
            {
                "id": entry_id or api._token_id(token, provider),
                "label": label,
                "provider": provider,
                "token": token,
                "enabled": enabled,
                "updated_at": updated_at,
                "masked": api._mask_token(token),
                "api_base": api_base,
                "proxy": proxy,
                "disabled_at": str(raw.get("disabled_at") or ""),
                "disabled_reason": str(raw.get("disabled_reason") or ""),
            }
        )
    return entries



def _invalidate_token_cache() -> None:
    """在保存 token 后使缓存失效。"""
    api._TOKEN_ENTRIES_CACHE = None
    api._TOKEN_ENTRIES_CACHE_AT = 0.0



def _disable_token_entry(entry: dict[str, Any], reason: str) -> None:
    token_id = str(entry.get("id") or "")
    token_value = str(entry.get("token") or "")
    if not token_id and not token_value:
        return
    data = api._read_token_file()
    raw_entries = data.get("tokens")
    if not isinstance(raw_entries, list):
        return
    changed = False
    now = datetime.now().isoformat(timespec="seconds")
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        raw_token = str(raw.get("token") or raw.get("api_key") or "").strip()
        raw_provider = api._provider_key(str(raw.get("provider") or raw.get("type") or api._guess_provider(raw_token)))
        raw_id = str(raw.get("id") or api._token_id(raw_token, raw_provider)).strip()
        if (token_id and raw_id == token_id) or (token_value and raw_token == token_value):
            raw["enabled"] = False
            raw["disabled_at"] = now
            raw["disabled_reason"] = str(reason or "provider disabled")[:500]
            changed = True
    if not changed:
        return
    data["tokens"] = raw_entries
    data["updated_at"] = now
    encrypted = api._encrypt_token_payload(data)
    atomic_write_text(api.TOKEN_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2) + "\n")
    api._invalidate_token_cache()



def _remove_token_entry(entry: dict[str, Any], reason: str) -> bool:
    token_id = str(entry.get("id") or "")
    token_value = str(entry.get("token") or "")
    if not token_id and not token_value:
        return False
    data = api._read_token_file()
    raw_entries = data.get("tokens")
    if not isinstance(raw_entries, list):
        return False
    kept: list[Any] = []
    removed = False
    for raw in raw_entries:
        if not isinstance(raw, dict):
            kept.append(raw)
            continue
        raw_token = str(raw.get("token") or raw.get("api_key") or "").strip()
        raw_provider = api._provider_key(str(raw.get("provider") or raw.get("type") or api._guess_provider(raw_token)))
        raw_id = str(raw.get("id") or api._token_id(raw_token, raw_provider)).strip()
        if (token_id and raw_id == token_id) or (token_value and raw_token == token_value):
            removed = True
            continue
        kept.append(raw)
    if not removed:
        return False
    now = datetime.now().isoformat(timespec="seconds")
    last_removed = {
        "id": token_id,
        "label": str(entry.get("label") or ""),
        "provider": api._provider_key(str(entry.get("provider") or "")),
        "removed_at": now,
        "reason": str(reason or "token unusable")[:500],
    }
    api._write_token_entries([raw for raw in kept if isinstance(raw, dict)], last_removed=last_removed)
    return True



def _encrypt_token_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy and encrypt every token field so plaintext credentials never
    hit disk. protect_secret is idempotent (dpapi:v1: prefix is kept)."""
    import copy as _copy

    out = _copy.deepcopy(payload)
    for key in ("token", "api_key"):
        value = out.get(key)
        if isinstance(value, str) and value:
            out[key] = protect_secret(value)
    for entry in out.get("tokens") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("token", "api_key"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                entry[key] = protect_secret(value)
    removed = out.get("last_removed_token")
    if isinstance(removed, dict):
        for key in ("token", "api_key"):
            value = removed.get(key)
            if isinstance(value, str) and value:
                removed[key] = protect_secret(value)
    return out



def _write_token_entries(
    entries: list[dict[str, Any]],
    *,
    last_removed: dict[str, Any] | None = None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "token": str((entries[0] if entries else {}).get("token") or ""),
        "tokens": entries,
        "updated_at": now,
    }
    if last_removed:
        payload["last_removed_token"] = last_removed
    encrypted = api._encrypt_token_payload(payload)
    atomic_write_text(api.TOKEN_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2) + "\n")
    api._invalidate_token_cache()



def _enabled_token_entries() -> list[dict[str, Any]]:
    now = time.time()
    if api._TOKEN_ENTRIES_CACHE is not None and now - api._TOKEN_ENTRIES_CACHE_AT < api._TOKEN_ENTRIES_CACHE_TTL:
        return list(api._TOKEN_ENTRIES_CACHE)
    entries = [
        entry for entry in api._normalize_token_entries()
        if entry.get("enabled") and api._provider_key(str(entry.get("provider", ""))) != PROVIDER_UNKNOWN
    ]
    api._TOKEN_ENTRIES_CACHE = entries
    api._TOKEN_ENTRIES_CACHE_AT = now
    return list(entries)



def _token_disabled_until(token_id: str) -> float:
    state = api._TOKEN_FAILURES.get(str(token_id) or "")
    if not state:
        return 0.0
    until = float(state.get("disabled_until") or 0.0)
    if until and until <= time.time():
        api._TOKEN_FAILURES.pop(str(token_id), None)
        return 0.0
    return until



def _is_token_temporarily_disabled(entry: dict[str, Any]) -> bool:
    return api._token_disabled_until(str(entry.get("id") or "")) > time.time()



def _record_token_failure(entry: dict[str, Any], message: str) -> bool:
    token_id = str(entry.get("id") or "")
    if not token_id:
        return False
    provider = api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
    text = str(message or "").lower()
    if provider == PROVIDER_NOVELAI and (
        "not enough anlas" in text
        or "out of trial image generations" in text
        or ("402" in text and "trial" in text)
    ):
        now = time.time()
        api._TOKEN_FAILURES[token_id] = {
            "count": 1,
            "reason": "quota_exhausted",
            "last_error": str(message or ""),
            "last_at": now,
            "disabled_until": now + api._TOKEN_FAILURE_TTL_SEC,
        }
        validation = dict(api._TOKEN_VALIDATIONS.get(token_id) or {})
        validation["quota_exhausted"] = True
        api._TOKEN_VALIDATIONS[token_id] = validation
        return True
    # Phrase-only matches — never bare status codes or bare "banned"/"suspended"
    # (those match too much unrelated provider text).
    permanent_parts = (
        "token invalid",
        "api key invalid",
        "invalid or expired",
        "unauthorized",
        "forbidden",
        "permission denied",
        "account disabled",
        "account banned",
        "account suspended",
        "or banned",
        "insufficient balance",
        "no balance",
        "quota exceeded",
        "recaptcha",
        "status code 401",
        "status code 403",
        "http 401",
        "http 403",
        "error 401",
        "error 403",
    )
    permanent_failure = any(part in text for part in permanent_parts)
    if permanent_failure:
        api._remove_token_entry(entry, message)
        api._TOKEN_FAILURES.pop(token_id, None)
        return True
    xianyun_disabled = (
        provider == PROVIDER_XIANYUN
        and any(
            part in text
            for part in (
                "api key invalid",
                "invalid or expired",
                "unauthorized",
                "forbidden",
                "permission denied",
                "account disabled",
                "account banned",
                "account suspended",
                "or banned",
                "封禁",
                "禁用",
                "停用",
                "冻结",
                "余额不足",
                "insufficient balance",
                "no balance",
                "quota exceeded",
                "status code 403",
                "http 403",
                "error 403",
            )
        )
    )
    if xianyun_disabled:
        api._remove_token_entry(entry, message)
        api._TOKEN_FAILURES.pop(token_id, None)
        return True

    transient_failure = any(
        part in text
        for part in (
            "request too frequent",
            "too frequent",
            "retry later",
            "429",
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "temporarily unavailable",
            "timeout",
            "timed out",
        )
    )
    if transient_failure:
        now = time.time()
        ttl = (
            api._TRANSIENT_PROVIDER_TTL_SEC
            if provider == PROVIDER_XIANYUN
            else api._NAI_TRANSIENT_TTL_SEC
        )
        state = api._TOKEN_FAILURES.get(token_id) or {"count": 0}
        state["count"] = int(state.get("count") or 0) + 1
        state["last_error"] = str(message or "")
        state["last_at"] = now
        state["disabled_until"] = now + ttl
        api._TOKEN_FAILURES[token_id] = state
        api._LAST_GEN_AT_BY_TOKEN[token_id] = now
        return True

    hard_failure = any(
        part in text
        for part in (
            "token invalid",
            "invalid or expired",
            "expired",
            "recaptcha token is required",
            "recaptcha",
            "401",
        )
    )
    if provider == PROVIDER_NOVELAI and "trial generation" in text:
        hard_failure = True
    if not hard_failure:
        return False
    now = time.time()
    state = api._TOKEN_FAILURES.get(token_id) or {"count": 0}
    state["count"] = int(state.get("count") or 0) + 1
    state["last_error"] = str(message or "")
    state["last_at"] = now
    if state["count"] >= api._TOKEN_FAILURE_LIMIT:
        state["disabled_until"] = now + api._TOKEN_FAILURE_TTL_SEC
    api._TOKEN_FAILURES[token_id] = state
    return True



def _clear_token_failure(entry: dict[str, Any]) -> None:
    token_id = str(entry.get("id") or "")
    if token_id:
        api._TOKEN_FAILURES.pop(token_id, None)



def _exception_message(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__



def _candidate_token_entries(preferred: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    entries = api._enabled_token_entries()
    live_ids = {str(entry.get("id") or "") for entry in entries}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(entry: dict[str, Any] | None) -> None:
        if not entry:
            return
        token_id = str(entry.get("id") or "")
        if not token_id or token_id in seen:
            return
        if token_id not in live_ids:
            return
        if api._is_token_temporarily_disabled(entry):
            return
        seen.add(token_id)
        out.append(entry)

    def safe_rank(entry: dict[str, Any]) -> int:
        provider = api._provider_key(str(entry.get("provider") or ""))
        if provider == PROVIDER_XIANYUN:
            return 2
        validation = api._TOKEN_VALIDATIONS.get(str(entry.get("id") or "")) or {}
        if int(validation.get("tier") or 0) == 0:
            return 0
        if validation.get("is_opus"):
            return 1
        if validation:
            return 99
        return 1

    ordered = sorted(entries, key=safe_rank)
    if preferred and safe_rank(preferred) < 99:
        add(preferred)
    for entry in ordered:
        if safe_rank(entry) < 99:
            add(entry)
    return out



def _public_token_entry(entry: dict[str, Any]) -> dict[str, Any]:
    # api_base/proxy 属于本机网络布局信息，不回显原值，只暴露是否已配置
    return {
        "id": entry.get("id", ""),
        "label": entry.get("label", ""),
        "provider": api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI)),
        "enabled": bool(entry.get("enabled")),
        "masked": entry.get("masked", ""),
        "updated_at": entry.get("updated_at", ""),
        "api_base": "",
        "proxy": "",
        "has_api_base": bool(str(entry.get("api_base") or "").strip()),
        "has_proxy": bool(str(entry.get("proxy") or "").strip()),
        "disabled_at": entry.get("disabled_at", ""),
        "disabled_reason": entry.get("disabled_reason", ""),
    }



def _probe_provider(token: str, api_base: str = "", timeout: float = 8.0) -> str:
    """通过 API 探测 token 的实际 provider。"""
    raw = str(token or "").strip()
    if not raw:
        return PROVIDER_UNKNOWN
    # 先尝试 NAI 订阅接口
    try:
        import api.httpx
        headers = {"Authorization": f"Bearer {raw}"}
        r = api.httpx.get("https://api.novelai.net/user/subscription", headers=headers, timeout=timeout)
        if r.status_code == 200:
            return PROVIDER_NOVELAI
    except Exception:
        pass
    # 再尝试闲云提交接口
    try:
        import api.httpx
        test_base = (api_base or api.XIANYUN_API_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {raw}", "Content-Type": "application/json"}
        r = api.httpx.post(f"{test_base}/generate_image", headers=headers, json={}, timeout=timeout)
        if r.status_code in {400, 422} or (r.status_code != 404 and r.status_code < 500):
            return PROVIDER_XIANYUN
    except Exception:
        pass
    return PROVIDER_UNKNOWN



def save_token(token: str, default_provider: str = "") -> dict[str, Any]:
    """Save multi-line tokens. Optional default_provider forces unknown bare keys."""
    raw_tokens = api._parse_token_text(token)
    parsed_entries = [
        parsed
        for idx, value in enumerate(raw_tokens)
        if (parsed := api._parse_token_line(value, idx))
    ]
    if not parsed_entries:
        raise ValueError("token cannot be empty")
    force_provider = api._provider_key(str(default_provider or "").strip()) if default_provider else ""
    if force_provider == PROVIDER_UNKNOWN:
        force_provider = ""
    api.DATA_DIR.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now().isoformat(timespec="seconds")
    # Inherit proxy/api_base from the previous config when the incoming line
    # does not carry them, so UI saves never wipe per-token network settings.
    old_entries = api._normalize_token_entries()
    old_settings = {
        f"{api._provider_key(str(e.get('provider') or ''))}:{str(e.get('token') or '')}": e
        for e in old_entries
    }
    entries = []
    seen: set[str] = set()
    provider_counts: dict[str, int] = {}
    for entry in parsed_entries:
        raw_provider = str(entry.get("provider") or PROVIDER_UNKNOWN)
        value = str(entry.get("token") or "").strip()
        if force_provider and api._provider_key(raw_provider) == PROVIDER_UNKNOWN:
            provider = force_provider
        else:
            provider = api._legacy_save_provider(raw_provider, value)
        dedupe_key = f"{provider}:{value}"
        if not value or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        old_entry = old_settings.get(dedupe_key) or {}
        entries.append(
            {
                "id": api._token_id(value, provider),
                "label": entry.get("label") or f"{api._provider_label(provider)} #{provider_counts[provider]}",
                "provider": provider,
                "token": value,
                "enabled": entry.get("enabled") is not False,
                "updated_at": updated_at,
                "api_base": str(entry.get("api_base") or old_entry.get("api_base") or "").strip(),
                "proxy": str(entry.get("proxy") or old_entry.get("proxy") or "").strip(),
            }
        )
    if not entries:
        raise ValueError("token cannot be empty")
    payload = {
        "token": entries[0]["token"],
        "tokens": entries,
        "updated_at": updated_at,
    }
    encrypted = api._encrypt_token_payload(payload)
    atomic_write_text(api.TOKEN_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2) + "\n")
    api._invalidate_token_cache()
    return {
        "ok": True,
        "has_token": True,
        "updated_at": updated_at,
        "token_count": len(entries),
        "enabled_count": len(entries),
        "concurrency": len(entries),
        "providers": dict(provider_counts),
    }



def add_token_entry(payload: dict[str, Any]) -> dict[str, Any]:
    raw_token = str(payload.get("token") or payload.get("api_key") or "").strip()
    parsed_line = api._parse_token_line(raw_token, 0)
    if parsed_line and api._provider_key(str(parsed_line.get("provider") or "")) != PROVIDER_UNKNOWN:
        payload = {**payload, **parsed_line}
    parsed = api._parse_token_line(
        {
            "token": payload.get("token") or payload.get("api_key") or "",
            "provider": payload.get("provider") or payload.get("type") or "",
            "label": payload.get("label") or "",
            "api_base": payload.get("api_base") or payload.get("base_url") or "",
            "proxy": payload.get("proxy") or "",
        },
        0,
    )
    if not parsed:
        raise ValueError("token cannot be empty")
    provider = api._provider_key(str(parsed.get("provider") or PROVIDER_UNKNOWN))
    value = str(parsed.get("token") or "").strip()
    if provider == PROVIDER_UNKNOWN:
        probed = api._probe_provider(value, api_base=str(parsed.get("api_base") or ""))
        if probed != PROVIDER_UNKNOWN:
            provider = probed
    if provider == PROVIDER_UNKNOWN:
        raise ValueError("provider is required: choose novelai or xianyun")
    from network_safety import validate_outbound_proxy, validate_provider_api_base

    api_base = validate_provider_api_base(str(parsed.get("api_base") or ""))
    proxy = validate_outbound_proxy(str(parsed.get("proxy") or ""))
    entries = api._normalize_token_entries()
    dedupe_key = f"{provider}:{value}"
    if any(f"{api._provider_key(str(e.get('provider') or ''))}:{e.get('token')}" == dedupe_key for e in entries):
        raise ValueError("token already exists in pool")
    updated_at = datetime.now().isoformat(timespec="seconds")
    provider_count = sum(1 for e in entries if api._provider_key(str(e.get("provider") or "")) == provider) + 1
    entries.append(
        {
            "id": api._token_id(value, provider),
            "label": str(parsed.get("label") or f"{api._provider_label(provider)} #{provider_count}").strip(),
            "provider": provider,
            "token": value,
            "enabled": True,
            "updated_at": updated_at,
            "api_base": api_base,
            "proxy": proxy,
        }
    )
    api._write_token_entries(entries)
    return {"ok": True, "message": "token added", **api.token_status()}



def delete_token_entry(token_id: str) -> dict[str, Any]:
    tid = str(token_id or "").strip()
    if not tid:
        raise ValueError("token_id is required")
    entries = api._normalize_token_entries()
    kept = [entry for entry in entries if str(entry.get("id") or "") != tid]
    if len(kept) == len(entries):
        raise ValueError("token not found")
    api._write_token_entries(kept)
    api._TOKEN_FAILURES.pop(tid, None)
    return {"ok": True, "message": "token deleted", **api.token_status()}



def _check_one_token_entry(entry: dict[str, Any], *, remove_bad: bool = True) -> dict[str, Any]:
    provider = api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
    token_id = str(entry.get("id") or "")
    result = {
        **api._public_token_entry(entry),
        "ok": False,
        "checked": True,
        "removed": False,
        "message": "",
    }
    if provider == PROVIDER_XIANYUN:
        api_base = str(entry.get("api_base") or api.XIANYUN_API_BASE).rstrip("/")
        try:
            status, text = api._token_check_request(
                "POST",
                f"{api_base}/generate_image",
                api._xianyun_headers(str(entry.get("token") or "")),
                json_body={},
                timeout_sec=10.0,
            )
            if status in {401, 403}:
                msg = f"Xianyun token check failed {status}: {text[:200]}"
                if remove_bad:
                    result["removed"] = api._remove_token_entry(entry, msg)
                result["message"] = msg
                return result
            if status in {400, 422}:
                result["ok"] = True
                result["message"] = "Xianyun token accepted; generation endpoint reached parameter validation"
                return result
            if status >= 500:
                result["message"] = f"Xianyun check inconclusive {status}: {text[:200]}"
                return result
            result["ok"] = True
            result["message"] = "Xianyun token accepted by generation endpoint"
            return result
        except Exception as exc:
            result["message"] = f"Xianyun check inconclusive: {exc}"
            return result

    try:
        status, text = api._token_check_request(
            "GET",
            f"{api.API_BASE}/user/subscription",
            api._auth_headers(str(entry.get("token") or "")),
            timeout_sec=12.0,
            proxy=str(entry.get("proxy") or ""),
        )
        if status == 200:
            data = json.loads(text or "{}")
            tier = int(data.get("tier") or 0)
            result.update(
                {
                    "ok": True,
                    "tier": tier,
                    "is_opus": tier >= 3 or "opus" in str(data.get("activeSubscription", "")).lower(),
                    "message": "NovelAI token OK",
                }
            )
            return result
        if status == 400:
            # pst- persistent tokens are rejected by the account API (api.novelai.net);
            # validate against the image API instead.
            img_status, img_text = api._token_check_request(
                "GET",
                f"{api.IMAGE_API_BASE}/user/data",
                api._auth_headers(str(entry.get("token") or "")),
                timeout_sec=12.0,
                proxy=str(entry.get("proxy") or ""),
            )
            if img_status == 200:
                img = json.loads(img_text or "{}")
                sub = img.get("subscription") or {}
                tier = int(sub.get("tier") or 0)
                result.update(
                    {
                        "ok": True,
                        "tier": tier,
                        "is_opus": tier >= 3 or "opus" in str(sub.get("activeSubscription", "")).lower(),
                        "account_status_available": False,
                        "message": f"NovelAI persistent token OK (image API, tier={tier})",
                    }
                )
                return result
            if img_status in {401, 403}:
                msg = f"NAI token check failed {img_status}: {img_text[:200]}"
                if remove_bad:
                    result["removed"] = api._remove_token_entry(entry, msg)
                result["message"] = msg
                return result
            info_status, info_text = api._token_check_request(
                "GET",
                f"{api.API_BASE}/user/information",
                api._auth_headers(str(entry.get("token") or "")),
                timeout_sec=12.0,
                proxy=str(entry.get("proxy") or ""),
            )
            if info_status == 200:
                info = json.loads(info_text or "{}")
                result.update(
                    {
                        "ok": True,
                        "tier": 0,
                        "plan": "paper",
                        "is_opus": False,
                        "free_confirmed": True,
                        "account_status_available": True,
                        "email_verified": bool(info.get("emailVerified")),
                        "message": "NovelAI Paper account verified",
                    }
                )
                return result
            result.update(
                {
                    "account_status_available": False,
                    "removed": False,
                    "message": (
                        "NovelAI persistent generation token preserved; "
                        "account status endpoint is unavailable"
                    ),
                }
            )
            return result
        msg = f"NAI token check failed {status}: {text[:200]}"
        if status in {400, 401, 403} and remove_bad:
            result["removed"] = api._remove_token_entry(entry, msg)
        result["message"] = msg
        return result
    except Exception as exc:
        result["message"] = f"NovelAI check failed: {exc}"
        return result



def check_token_pool(token_id: str = "", *, remove_bad: bool = True) -> dict[str, Any]:
    entries = api._normalize_token_entries()
    if token_id:
        entries = [entry for entry in entries if str(entry.get("id") or "") == str(token_id)]
        if not entries:
            raise ValueError("token not found")
    results = [api._check_one_token_entry(entry, remove_bad=remove_bad) for entry in entries]
    for entry, result in zip(entries, results):
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        validation = dict(api._TOKEN_VALIDATIONS.get(entry_id) or {})
        validation.update(
            {
                "ok": bool(result.get("ok")),
                "tier": result.get("tier"),
                "is_opus": bool(result.get("is_opus")),
                "free_confirmed": bool(result.get("free_confirmed")),
                "quota_exhausted": False if result.get("ok") else bool(
                    validation.get("quota_exhausted")
                ),
            }
        )
        api._TOKEN_VALIDATIONS[entry_id] = validation
        if result.get("ok"):
            api._TOKEN_FAILURES.pop(entry_id, None)
    return {"ok": True, "results": results, **api.token_status()}



def token_status() -> dict[str, Any]:
    data = api._read_token_file()
    entries = api._normalize_token_entries(data)
    enabled = [entry for entry in entries if entry.get("enabled")]
    providers: dict[str, int] = {}
    for entry in enabled:
        provider = api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
        providers[provider] = providers.get(provider, 0) + 1
    return {
        "has_token": bool(enabled),
        "token_count": len(entries),
        "enabled_count": len(enabled),
        "concurrency": len(enabled),
        "providers": providers,
        "tokens": [api._public_token_entry(entry) for entry in entries],
        "updated_at": data.get("updated_at", ""),
    }



def list_generation_slots() -> list[dict[str, Any]]:
    return [api._public_token_entry(entry) for entry in api._enabled_token_entries()]



def generation_concurrency() -> int:
    return len(api._candidate_token_entries())



def generation_concurrency_for_batch(target_count: Any = 1, **_kwargs: Any) -> int:
    try:
        count = max(0, int(target_count))
    except (TypeError, ValueError):
        count = len(target_count or []) if isinstance(target_count, list) else 1
    return min(count, api.generation_concurrency())



def _slot_cooldown_sec(entry: dict[str, Any]) -> float:
    """Cooldown per provider.

    NAI keeps a fixed 3s cooldown for stability regardless of slot count
    (user preference: 稳一点).  Xianyun is a slow relay and keeps its own
    longer cooldown; the two providers stay separated.
    """
    provider = api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
    if provider == PROVIDER_XIANYUN:
        return api._XIANYUN_COOLDOWN_SEC
    return api._COOLDOWN_SEC



def _select_token_entry(token_id: str = "") -> dict[str, Any]:
    entries = api._enabled_token_entries()
    if not entries:
        raise ValueError("NovelAI token is not configured")
    if token_id:
        for entry in entries:
            if str(entry.get("id") or "") == str(token_id):
                return entry
        raise ValueError(f"NovelAI token slot is missing or disabled: {token_id}")
    return entries[0]



def _next_token_entry() -> dict[str, Any]:
    entries = api._candidate_token_entries()
    if not entries:
        raise ValueError("NovelAI token is not configured")
    idx = api._TOKEN_CURSOR % len(entries)
    api._TOKEN_CURSOR = (idx + 1) % len(entries)
    return entries[idx]



def _auth_headers(token: str) -> dict[str, str]:
    token = str(token or "").strip()
    if not token:
        raise ValueError("NovelAI token is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://novelai.net/",
    }



def _xianyun_headers(token: str) -> dict[str, str]:
    token = str(token or "").strip()
    if not token:
        raise ValueError("Xianyun API key is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://nai3.idlecloud.cc",
        "Referer": "https://nai3.idlecloud.cc/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }



def get_subscription(token_id: str = "") -> dict[str, Any]:
    entry = api._select_token_entry(token_id)
    provider = api._provider_key(str(entry.get("provider") or PROVIDER_NOVELAI))
    if provider == PROVIDER_XIANYUN:
        return {
            "ok": True,
            "tier": None,
            "is_opus": True,
            "anlas_subscription": None,
            "anlas_purchased": None,
            "anlas_total": None,
            "perks": {"provider": PROVIDER_XIANYUN, "membership": True},
            "queue": api.queue_status(),
            "token_id": entry.get("id", ""),
            "token_label": entry.get("label", ""),
            "provider": provider,
        }
    proxy = str(entry.get("proxy") or "").strip()
    with api.httpx.Client(timeout=api.httpx.Timeout(12.0, connect=6.0), proxy=proxy or None) as client:
        resp = client.get(
            f"{api.API_BASE}/user/subscription",
            headers=api._auth_headers(str(entry.get("token") or "")),
        )
        if resp.status_code == 200:
            data = resp.json()
        else:
            # pst- persistent tokens are rejected by the account API; use the
            # image API which carries the same subscription payload.
            image = client.get(
                f"{api.IMAGE_API_BASE}/user/data",
                headers=api._auth_headers(str(entry.get("token") or "")),
            )
            if image.status_code == 200:
                image_payload = image.json()
                data = dict(image_payload.get("subscription") or {})
                steps = image_payload.get("trainingStepsLeft") or {}
                if steps and "trainingAmountLeft" not in data:
                    data["trainingAmountLeft"] = steps
            else:
                info = client.get(
                    f"{api.API_BASE}/user/information",
                    headers=api._auth_headers(str(entry.get("token") or "")),
                )
                if info.status_code == 200:
                    payload = info.json()
                    return {
                        "ok": True,
                        "tier": 0,
                        "plan": "paper",
                        "membership_active": False,
                        "is_opus": False,
                        "email_verified": bool(payload.get("emailVerified")),
                        "free_confirmed": True,
                        "account_status_available": True,
                        "anlas_subscription": None,
                        "anlas_purchased": None,
                        "anlas_total": None,
                        "token_id": entry.get("id", ""),
                        "provider": provider,
                    }
                return {
                    "ok": True,
                    "tier": None,
                    "plan": "unknown",
                    "membership_active": None,
                    "is_opus": False,
                    "generation_token_configured": True,
                    "account_status_available": False,
                    "token_valid": None,
                    "anlas_subscription": None,
                    "anlas_purchased": None,
                    "anlas_total": None,
                    "token_id": entry.get("id", ""),
                    "provider": provider,
                }
    training = data.get("trainingAmountLeft") or data.get("trainingStepsLeft") or {}
    fixed = int(training.get("fixedTrainingStepsLeft") or 0)
    purchased = int(data.get("totalCredits") or data.get("purchasedTrainingSteps") or 0)
    tier = int(data.get("tier") or 0)
    is_opus = tier >= 3 or "opus" in str(data.get("activeSubscription", "")).lower()
    return {
        "ok": True,
        "tier": tier,
        "is_opus": is_opus,
        "anlas_subscription": fixed,
        "anlas_purchased": purchased,
        "anlas_total": fixed + purchased,
        "perks": data.get("perks") or {},
        "queue": api.queue_status(),
        "token_id": entry.get("id", ""),
        "token_label": entry.get("label", ""),
    }

