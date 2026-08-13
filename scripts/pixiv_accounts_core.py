"""Small, local-only Pixiv credential store for Core releases."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from local_secrets import protect_secret, unprotect_secret
from paths import DeferredDataPath, data_dir


DATA_DIR = DeferredDataPath(lambda: data_dir())
ACCOUNTS_PATH = DeferredDataPath(lambda: data_dir() / "pixiv_accounts.local.json")
ACCOUNTS_BACKUP_PATH = DeferredDataPath(lambda: data_dir() / "pixiv_accounts.local.backup.json")


PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
PIXIV_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
PIXIV_OAUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
PIXIV_USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
PIXIV_APP_OS = "ios"
PIXIV_APP_OS_VERSION = "14.6"
PIXIV_APP_VERSION = "7.13.3"
_LOCK = threading.RLock()
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}


class PixivAuthError(RuntimeError):
    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(str(detail.get("message") or "Pixiv login failed"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_store() -> dict[str, Any]:
    return {"active_id": "", "accounts": []}


def _load() -> dict[str, Any]:
    with _LOCK:
        if not ACCOUNTS_PATH.is_file():
            return _empty_store()
        try:
            stored = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
            if not isinstance(stored, dict):
                return _empty_store()
            result = json.loads(json.dumps(stored))
            for account in result.get("accounts") or []:
                if isinstance(account, dict) and account.get("refresh_token"):
                    account["refresh_token"] = unprotect_secret(str(account["refresh_token"]))
            return result
        except Exception:
            return _empty_store()


def _save(store: dict[str, Any]) -> None:
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        encoded = json.loads(json.dumps(store))
        for account in encoded.get("accounts") or []:
            if isinstance(account, dict) and account.get("refresh_token"):
                account["refresh_token"] = protect_secret(str(account["refresh_token"]))
        payload = json.dumps(encoded, ensure_ascii=False, indent=2) + "\n"
        if ACCOUNTS_PATH.is_file():
            ACCOUNTS_BACKUP_PATH.write_bytes(ACCOUNTS_PATH.read_bytes())
        temporary = ACCOUNTS_PATH.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(ACCOUNTS_PATH)


def _normalize_token(value: str) -> str:
    token = str(value or "").strip().strip('"').strip("'").strip()
    if len(token) < 32 or any(character.isspace() for character in token):
        raise ValueError("refresh_token is incomplete or contains whitespace")
    return token


def _public(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(account.get("id") or ""),
        "label": str(account.get("label") or "Pixiv account"),
        "has_token": bool(account.get("refresh_token")),
        "pixiv_user_id": account.get("pixiv_user_id"),
        "user_name": str(account.get("user_name") or ""),
        "user_account": str(account.get("user_account") or ""),
        "created_at": str(account.get("created_at") or ""),
        "updated_at": str(account.get("updated_at") or ""),
    }


def list_accounts() -> list[dict[str, Any]]:
    return [_public(account) for account in _load().get("accounts") or [] if isinstance(account, dict)]


def get_active_account_id() -> str:
    store = _load()
    accounts = [account for account in store.get("accounts") or [] if isinstance(account, dict)]
    active = str(store.get("active_id") or "")
    if active and any(str(account.get("id")) == active for account in accounts):
        return active
    return str(accounts[0].get("id") or "") if accounts else ""


def get_active_account(*, include_secret: bool = False) -> dict[str, Any] | None:
    active = get_active_account_id()
    for account in _load().get("accounts") or []:
        if isinstance(account, dict) and str(account.get("id")) == active:
            return dict(account) if include_secret else _public(account)
    return None


def _find(account_id: str) -> dict[str, Any] | None:
    for account in _load().get("accounts") or []:
        if isinstance(account, dict) and str(account.get("id")) == str(account_id):
            return account
    return None


def add_account(*, refresh_token: str = "", label: str = "", direction: str = "") -> dict[str, Any]:
    _ = direction
    token = _normalize_token(refresh_token)
    store = _load()
    account_id = f"acc_{uuid.uuid4().hex[:10]}"
    account = {
        "id": account_id,
        "label": str(label or "").strip() or f"Pixiv {len(store.get('accounts') or []) + 1}",
        "refresh_token": token,
        "pixiv_user_id": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    store.setdefault("accounts", []).append(account)
    if not store.get("active_id"):
        store["active_id"] = account_id
    _save(store)
    return {"ok": True, "account": _public(account), "active_id": store["active_id"]}


def update_account_token(account_id: str, refresh_token: str) -> dict[str, Any]:
    token = _normalize_token(refresh_token)
    store = _load()
    for account in store.get("accounts") or []:
        if str(account.get("id")) == str(account_id):
            account["refresh_token"] = token
            account["updated_at"] = _now()
            _save(store)
            _TOKEN_CACHE.pop(str(account_id), None)
            return {"ok": True, "account": _public(account)}
    raise ValueError("Pixiv account not found")


def switch_account(account_id: str) -> dict[str, Any]:
    store = _load()
    if not any(str(account.get("id")) == str(account_id) for account in store.get("accounts") or []):
        raise ValueError("Pixiv account not found")
    store["active_id"] = str(account_id)
    _save(store)
    return {"ok": True, "active_id": str(account_id), "account": get_active_account()}


def remove_account(account_id: str) -> dict[str, Any]:
    store = _load()
    before = list(store.get("accounts") or [])
    accounts = [account for account in before if str(account.get("id")) != str(account_id)]
    if len(accounts) == len(before):
        raise ValueError("Pixiv account not found")
    store["accounts"] = accounts
    if str(store.get("active_id") or "") == str(account_id):
        store["active_id"] = str(accounts[0].get("id") or "") if accounts else ""
    _save(store)
    _TOKEN_CACHE.pop(str(account_id), None)
    return {"ok": True, "active_id": store["active_id"], "accounts": list_accounts()}


def _oauth_headers() -> dict[str, str]:
    client_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    client_hash = hashlib.md5((client_time + PIXIV_HASH_SECRET).encode()).hexdigest()
    return {
        "User-Agent": PIXIV_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "App-OS": PIXIV_APP_OS,
        "App-OS-Version": PIXIV_APP_OS_VERSION,
        "App-Version": PIXIV_APP_VERSION,
        "X-Client-Time": client_time,
        "X-Client-Hash": client_hash,
    }


def pixiv_api_headers(access_token: str) -> dict[str, str]:
    return {
        "App-OS": PIXIV_APP_OS,
        "App-OS-Version": PIXIV_APP_OS_VERSION,
        "App-Version": PIXIV_APP_VERSION,
        "User-Agent": PIXIV_USER_AGENT,
        "Accept-Language": "zh_CN",
        "Authorization": f"Bearer {access_token}",
    }


def _refresh(refresh_token: str) -> dict[str, Any]:
    response = httpx.post(
        PIXIV_OAUTH_URL,
        data={
            "client_id": PIXIV_CLIENT_ID,
            "client_secret": PIXIV_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "get_secure_url": "1",
        },
        headers=_oauth_headers(),
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise PixivAuthError(
            {
                "status_code": response.status_code,
                "message": "Pixiv rejected the refresh token",
                "hint": "Obtain a new refresh_token and try again.",
            }
        )
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Pixiv returned an invalid login response")
    return payload


def ensure_access_token(account_id: str | None = None) -> tuple[str, dict[str, Any]]:
    account_id = str(account_id or get_active_account_id())
    account = _find(account_id)
    if not account:
        raise ValueError("Configure a Pixiv refresh_token first")
    cached = _TOKEN_CACHE.get(account_id) or {}
    if cached.get("access_token") and time.time() < float(cached.get("expires_at") or 0):
        return str(cached["access_token"]), dict(cached.get("user") or {})
    payload = _refresh(_normalize_token(str(account.get("refresh_token") or "")))
    access_token = str(payload["access_token"])
    user = dict(payload.get("user") or {})
    rotated = str(payload.get("refresh_token") or "").strip()
    current_refresh = str(account.get("refresh_token") or "").strip()
    if rotated and rotated != current_refresh:
        update_account_token(account_id, rotated)
    _TOKEN_CACHE[account_id] = {
        "access_token": access_token,
        "expires_at": time.time() + max(60, int(payload.get("expires_in") or 3600) - 120),
        "user": user,
    }
    store = _load()
    for item in store.get("accounts") or []:
        if str(item.get("id")) == account_id:
            item["pixiv_user_id"] = user.get("id")
            item["user_name"] = str(user.get("name") or "")
            item["user_account"] = str(user.get("account") or "")
            item["updated_at"] = _now()
    _save(store)
    return access_token, user


def test_account_auth(account_id: str | None = None) -> dict[str, Any]:
    account_id = str(account_id or get_active_account_id())
    if not account_id:
        return {"ok": False, "message": "No Pixiv account configured"}
    try:
        _TOKEN_CACHE.pop(account_id, None)
        _, user = ensure_access_token(account_id)
        return {"ok": True, "account_id": account_id, "user": user, "message": "Pixiv login is valid"}
    except PixivAuthError as exc:
        return {
            "ok": False,
            "account_id": account_id,
            "message": "Pixiv authentication was rejected",
            "error": {"code": "auth_rejected", "status_code": int(exc.detail.get("status_code") or 0), "hint": "Obtain a new refresh_token and retry."},
        }
    except Exception:
        return {
            "ok": False,
            "account_id": account_id,
            "message": "Pixiv authentication is temporarily unavailable",
            "error": {"code": "auth_unavailable", "hint": "Check network access and the saved refresh_token, then retry."},
        }
