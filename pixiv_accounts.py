"""Pixiv 多账号管理、粉丝/浏览量采集与 AI 运营分析。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
from atomic_io import atomic_write_text
from paths import DeferredDataPath, data_dir as _config_data_dir
from local_secrets import (
    PREFIX as SECRET_PREFIX,
    SecretProtectionUnavailable,
    protect_secret,
    unprotect_secret,
)


DATA_DIR = DeferredDataPath(lambda: _config_data_dir())
ACCOUNTS_PATH = DeferredDataPath(lambda: _config_data_dir() / "pixiv_accounts.local.json")
ACCOUNTS_BACKUP_PATH = DeferredDataPath(lambda: _config_data_dir() / "pixiv_accounts.local.backup.json")
STATS_PATH = DeferredDataPath(lambda: _config_data_dir() / "pixiv_account_stats.json")
ANALYTICS_PATH = DeferredDataPath(lambda: _config_data_dir() / "pixiv_analytics_cache.json")
LEGACY_SECRET_PATH = DeferredDataPath(lambda: _config_data_dir() / "pixiv.local.json")
_CREDENTIAL_LOCK_PATH = DeferredDataPath(lambda: _config_data_dir() / ".pixiv-credentials.lock")

# Pixiv 官方 App OAuth（旧 Android 客户端已失效，须用当前 iOS 凭证）
PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
PIXIV_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
PIXIV_OAUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
PIXIV_API_BASE = "https://app-api.pixiv.net"
PIXIV_USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
PIXIV_APP_OS = "ios"
PIXIV_APP_OS_VERSION = "14.6"
PIXIV_APP_VERSION = "7.13.3"

REFRESH_INTERVAL_HOURS = 6
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_STATS_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_SCHEDULER_STOP = threading.Event()
_SCHEDULER_THREAD: threading.Thread | None = None
_STALE_AI_WARNING_MARKERS = (
    "The supported API model names are deepseek-v4-pro or deepseek-v4-flash",
    "but you passed 明日方舟",
    "but you passed 鏄庢棩鏂硅垷",
)


class PixivAuthError(RuntimeError):
    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        status_code = detail.get("status_code") or 0
        code = detail.get("code")
        message = detail.get("message") or "Pixiv 登录失败"
        code_part = f" (code {code})" if code else ""
        super().__init__(f"Pixiv 登录失败 {status_code}{code_part}: {message}")


@contextmanager
def _credential_process_lock(timeout_sec: float = 30.0):
    """Serialize token rotation across the server and crawler processes."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DATA_DIR / _CREDENTIAL_LOCK_PATH.name
    handle = lock_path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    locked = False
    try:
        while not locked:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for Pixiv credential lock")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

ANALYTICS_SYSTEM = """你是 Pixiv 多账号运营数据顾问，服务对象是使用 NovelAI / Stable Diffusion 等工具发 AI 图的爱好者（不是职业画师）。
根据各账号的粉丝数、浏览量、作品数历史快照与近期上传记录，给出可执行建议。
只返回一个 JSON 对象，不要 Markdown，不要解释。

JSON 字段：
summary（200字内总览）,
trends（字符串数组，3-5条数据趋势观察）,
recommendations（字符串数组，3-6条具体运营建议）,
risks（字符串数组，0-3条风险提醒）,
next_actions（字符串数组，3-5条下一步行动，按优先级排序）

硬规则：
- 结合 AI 发图账号特点：更新节奏、tag 策略、封面选图、简介风格。
- 建议要具体可执行，不要空话。
- 若数据样本不足（少于2个快照），说明样本不足并给冷启动建议。"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_accounts_file() -> dict[str, Any]:
    if not ACCOUNTS_PATH.exists():
        _migrate_legacy_secret()
    if not ACCOUNTS_PATH.exists():
        return {"active_id": "", "accounts": [], "refresh_interval_hours": REFRESH_INTERVAL_HOURS}
    try:
        # Migrate both copies independently. A valid encrypted primary must not
        # leave a plaintext recovery copy behind.
        if ACCOUNTS_BACKUP_PATH.exists():
            _read_accounts_secret_file(ACCOUNTS_BACKUP_PATH)
        data = _read_accounts_secret_file(ACCOUNTS_PATH)
        if isinstance(data, dict) and data.get("accounts"):
            return data
        if (
            isinstance(data, dict)
            and not data.get("accounts")
            and data.get("allow_restore") is not False
            and ACCOUNTS_BACKUP_PATH.exists()
        ):
            backup = json.loads(ACCOUNTS_BACKUP_PATH.read_text(encoding="utf-8"))
            if isinstance(backup, dict) and backup.get("accounts"):
                _save_accounts_file(backup)
                return backup
        return data if isinstance(data, dict) else {"active_id": "", "accounts": []}
    except Exception:
        # 主文件损坏/解密失败时，尝试从备份恢复；两者都失败才返回空。
        try:
            if ACCOUNTS_BACKUP_PATH.exists():
                backup = _read_accounts_secret_file(ACCOUNTS_BACKUP_PATH)
                if isinstance(backup, dict) and isinstance(backup.get("accounts"), list):
                    if backup.get("accounts"):
                        _save_accounts_file(backup)
                    return backup
        except Exception:
            pass
        return {"active_id": "", "accounts": [], "refresh_interval_hours": REFRESH_INTERVAL_HOURS}


def _read_accounts_secret_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    decoded = json.loads(json.dumps(data))
    migrated = False
    for index, account in enumerate(decoded.get("accounts") or []):
        if not isinstance(account, dict) or not account.get("refresh_token"):
            continue
        raw = str(account["refresh_token"])
        account["refresh_token"] = unprotect_secret(raw)
        if raw and not raw.startswith(SECRET_PREFIX):
            try:
                data["accounts"][index]["refresh_token"] = protect_secret(raw)
                migrated = True
            except SecretProtectionUnavailable:
                pass
    if migrated:
        atomic_write_text(
            path,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return decoded


def _encrypt_accounts_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy and encrypt every refresh_token so plaintext credentials
    never hit disk (main file, backup file or temp file)."""
    import copy as _copy

    out = _copy.deepcopy(data)
    for account in out.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        token = account.get("refresh_token")
        if isinstance(token, str) and token:
            account["refresh_token"] = protect_secret(token)
    return out


def _save_accounts_file(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    encrypted = _encrypt_accounts_payload(data)
    if ACCOUNTS_PATH.exists():
        try:
            old = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
            if isinstance(old, dict) and old.get("accounts"):
                atomic_write_text(
                    ACCOUNTS_BACKUP_PATH,
                    json.dumps(old, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception:
            pass
    atomic_write_text(
        ACCOUNTS_PATH,
        json.dumps(encrypted, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _migrate_legacy_secret() -> None:
    if not LEGACY_SECRET_PATH.exists() or ACCOUNTS_PATH.exists():
        return
    try:
        raw = json.loads(LEGACY_SECRET_PATH.read_text(encoding="utf-8"))
        token = str(raw.get("refresh_token") or "").strip()
        if not token:
            return
        acc_id = f"acc_{uuid.uuid4().hex[:10]}"
        _save_accounts_file(
            {
                "active_id": acc_id,
                "refresh_interval_hours": REFRESH_INTERVAL_HOURS,
                "accounts": [
                    {
                        "id": acc_id,
                        "label": "默认账号",
                        "refresh_token": token,
                        "pixiv_user_id": None,
                        "direction": "AI 生成图爱好者，分享 NovelAI 同人插画",
                        "persona": {},
                        "created_at": raw.get("updated_at") or _now_iso(),
                        "updated_at": _now_iso(),
                    }
                ],
            }
        )
        try:
            LEGACY_SECRET_PATH.unlink()
        except OSError:
            pass
    except Exception:
        pass


def _public_account(acc: dict[str, Any]) -> dict[str, Any]:
    has_token = bool(acc.get("refresh_token"))
    mismatch = _account_identity_mismatch(acc)
    persona = acc.get("persona") or {}
    if isinstance(persona, dict):
        warning = str(persona.get("warning") or "")
        if warning and any(marker in warning for marker in _STALE_AI_WARNING_MARKERS):
            persona = {k: v for k, v in persona.items() if k != "warning"}
    return {
        "id": acc.get("id"),
        "label": acc.get("label") or "未命名",
        "pixiv_user_id": acc.get("pixiv_user_id"),
        "direction": acc.get("direction") or "",
        "has_token": has_token,
        "identity_mismatch": mismatch,
        "upload_ready": has_token and not mismatch,
        "persona": persona if isinstance(persona, dict) else {},
        "created_at": acc.get("created_at") or "",
        "updated_at": acc.get("updated_at") or "",
        "user_name": acc.get("user_name") or "",
        "user_account": acc.get("user_account") or "",
    }


def list_accounts() -> list[dict[str, Any]]:
    data = _load_accounts_file()
    return [_public_account(a) for a in data.get("accounts") or [] if isinstance(a, dict)]


def get_active_account_id() -> str:
    data = _load_accounts_file()
    active = str(data.get("active_id") or "").strip()
    accounts = data.get("accounts") or []
    if active and any(a.get("id") == active for a in accounts):
        return active
    if accounts:
        return str(accounts[0].get("id") or "")
    return ""


def get_active_account(*, include_secret: bool = False) -> dict[str, Any] | None:
    data = _load_accounts_file()
    active_id = get_active_account_id()
    for acc in data.get("accounts") or []:
        if acc.get("id") == active_id:
            if include_secret:
                return dict(acc)
            return _public_account(acc)
    return None


def _find_account(account_id: str) -> dict[str, Any] | None:
    for acc in _load_accounts_file().get("accounts") or []:
        if acc.get("id") == account_id:
            return acc
    return None


def _find_account_by_pixiv_uid(pixiv_user_id: Any) -> dict[str, Any] | None:
    uid = _int_or_none(pixiv_user_id)
    if uid is None:
        return None
    for acc in _load_accounts_file().get("accounts") or []:
        if _int_or_none(acc.get("pixiv_user_id")) == uid:
            return acc
    return None


def _account_label(acc: dict[str, Any] | None) -> str:
    if not acc:
        return ""
    return str(acc.get("label") or "").strip()


def _account_identity_mismatch(acc: dict[str, Any] | None) -> bool:
    return False


def _assert_pixiv_uid_available(
    pixiv_user_id: Any,
    *,
    account_id: str,
    label: str = "",
) -> None:
    uid = _int_or_none(pixiv_user_id)
    if uid is None:
        return
    other = _find_account_by_pixiv_uid(uid)
    if other and str(other.get("id") or "") != str(account_id or ""):
        other_label = _account_label(other) or other.get("id")
        who = str(other.get("user_name") or "").strip()
        raise ValueError(
            f"此 Pixiv 账号（{who or uid}）已绑定在「{other_label}」。"
            f"请切换到「{other_label}」上传，"
            f"或为「{label or '当前备注名'}」单独通行密钥登录，不能混用 token。"
        )


def validate_account_for_upload(account_id: str | None = None) -> dict[str, Any]:
    """上传前校验：必须且只能使用一个已登录、身份一致的本地账号。"""
    account_id = str(account_id or "").strip() or get_active_account_id()
    acc = _find_account(account_id) if account_id else None
    if not account_id or not acc:
        raise ValueError("请先登录并高亮当前 Pixiv 账号；上传只会使用当前账号")
    label = _account_label(acc) or account_id
    token = _normalize_refresh_token(str(acc.get("refresh_token") or ""))
    if not token:
        raise ValueError(
            f"账号「{label}」尚未登录。请先在 ① 区选中该账号，单独做通行密钥登录后再上传。"
        )
    if _account_identity_mismatch(acc):
        who = str(acc.get("user_name") or "").strip()
        raise ValueError(
            f"账号「{label}」与当前 Pixiv 登录「{who}」不一致，可能混绑了 token。"
            f"请为「{label}」重新通行密钥登录，不能共用另一个账号的 token。"
        )
    _, user = ensure_access_token(account_id)
    live_uid = _int_or_none(user.get("id"))
    stored_uid = _int_or_none(acc.get("pixiv_user_id"))
    if stored_uid is not None and live_uid is not None and stored_uid != live_uid:
        who = str(user.get("name") or user.get("account") or "").strip()
        raise ValueError(
            f"账号「{label}」绑定的 Pixiv 用户与 token 不符（当前 token 是 {who}）。"
            f"请重新为「{label}」单独登录，不要和另一个号混用。"
        )
    _assert_pixiv_uid_available(live_uid, account_id=account_id, label=label)
    return {
        "ok": True,
        "account_id": account_id,
        "label": label,
        "user": user,
        "pixiv_user_id": live_uid,
    }


def create_account_slot(
    *,
    label: str = "",
    direction: str = "",
    set_active: bool = True,
) -> dict[str, Any]:
    """Create an empty local account slot, then login via browser/passkey/token."""
    data = _load_accounts_file()
    accounts: list[dict[str, Any]] = list(data.get("accounts") or [])
    acc_id = f"acc_{uuid.uuid4().hex[:10]}"
    entry = {
        "id": acc_id,
        "label": str(label or "").strip() or f"新号{len(accounts) + 1}",
        "refresh_token": "",
        "pixiv_user_id": None,
        "direction": str(direction or "").strip()
        or "AI 生成图爱好者，分享 NovelAI 同人插画",
        "persona": {},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    accounts.append(entry)
    data["accounts"] = accounts
    if set_active or not data.get("active_id"):
        data["active_id"] = acc_id
    _save_accounts_file(data)
    return {
        "ok": True,
        "account": _public_account(entry),
        "active_id": data.get("active_id"),
        "message": f"已创建账号槽「{entry['label']}」，请用通行密钥或邮箱登录完成注册配置",
    }


def add_account(
    *,
    refresh_token: str = "",
    label: str = "",
    direction: str = "",
) -> dict[str, Any]:
    refresh_token = _normalize_refresh_token(refresh_token)
    if not refresh_token:
        # Allow creating empty slot from the same endpoint when no token provided.
        return create_account_slot(label=label, direction=direction, set_active=True)
    shape_err = _validate_refresh_token_shape(refresh_token)
    if shape_err:
        raise ValueError(shape_err)
    data = _load_accounts_file()
    accounts: list[dict[str, Any]] = list(data.get("accounts") or [])
    acc_id = f"acc_{uuid.uuid4().hex[:10]}"
    entry = {
        "id": acc_id,
        "label": str(label or "").strip() or f"账号{len(accounts) + 1}",
        "refresh_token": refresh_token,
        "pixiv_user_id": None,
        "direction": str(direction or "").strip() or "AI 生成图爱好者，分享 NovelAI 同人插画",
        "persona": {},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    accounts.append(entry)
    data["accounts"] = accounts
    if not data.get("active_id"):
        data["active_id"] = acc_id
    _save_accounts_file(data)
    _TOKEN_CACHE.pop(acc_id, None)
    auth = test_account_auth(acc_id)
    if auth.get("ok"):
        user = auth.get("user") or {}
        _assert_pixiv_uid_available(
            user.get("id"),
            account_id=acc_id,
            label=str(entry.get("label") or ""),
        )
        store = _load_accounts_file()
        for item in store.get("accounts") or []:
            if item.get("id") == acc_id:
                item["pixiv_user_id"] = user.get("id")
                item["user_name"] = user.get("name") or ""
                item["user_account"] = user.get("account") or ""
                item["updated_at"] = _now_iso()
                break
        _save_accounts_file(store)
        try:
            refresh_account_stats(acc_id, force=True)
        except Exception:
            pass
    return {
        "ok": True,
        "account": _public_account(_find_account(acc_id) or entry),
        "active_id": data.get("active_id"),
        "auth": auth,
        "message": auth.get("message") if auth.get("ok") else (auth.get("error") or {}).get("hint"),
    }


def _parse_import_line(raw: str) -> dict[str, str] | None:
    """Parse one import line.

    Supported forms:
    - refresh_token
    - label|refresh_token
    - label|refresh_token|direction
    - JSON object: {"label","refresh_token","direction"}
    - CSV-like with commas (label,token) when token has no comma
    Lines starting with # are ignored.
    """
    text = str(raw or "").strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        token = _normalize_refresh_token(
            str(obj.get("refresh_token") or obj.get("token") or obj.get("refreshToken") or "")
        )
        if not token:
            return None
        return {
            "label": str(obj.get("label") or obj.get("name") or "").strip(),
            "refresh_token": token,
            "direction": str(obj.get("direction") or obj.get("bio") or "").strip(),
        }
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
        if len(parts) == 1:
            token = _normalize_refresh_token(parts[0])
            return {"label": "", "refresh_token": token, "direction": ""} if token else None
        if len(parts) == 2:
            # label|token OR token|direction-like — prefer token-shaped second field
            a, b = parts[0], parts[1]
            if _validate_refresh_token_shape(b) is None and b:
                return {
                    "label": a,
                    "refresh_token": _normalize_refresh_token(b),
                    "direction": "",
                }
            token = _normalize_refresh_token(a)
            return {"label": "", "refresh_token": token, "direction": b} if token else None
        label, token_raw, direction = parts[0], parts[1], "|".join(parts[2:]).strip()
        token = _normalize_refresh_token(token_raw)
        if not token:
            return None
        return {"label": label, "refresh_token": token, "direction": direction}
    if "," in text:
        parts = [p.strip() for p in text.split(",", 2)]
        if len(parts) >= 2 and _validate_refresh_token_shape(parts[1]) is None:
            return {
                "label": parts[0],
                "refresh_token": _normalize_refresh_token(parts[1]),
                "direction": parts[2] if len(parts) > 2 else "",
            }
    token = _normalize_refresh_token(text)
    if not token:
        return None
    return {"label": "", "refresh_token": token, "direction": ""}


def import_accounts_batch(
    text: str = "",
    *,
    items: list[dict[str, Any]] | None = None,
    verify: bool = True,
    skip_duplicates: bool = True,
    set_first_active: bool = False,
) -> dict[str, Any]:
    """Import one or many accounts from text lines and/or structured items."""
    rows: list[dict[str, str]] = []
    for line in str(text or "").splitlines():
        parsed = _parse_import_line(line)
        if parsed:
            rows.append(parsed)
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        token = _normalize_refresh_token(
            str(raw.get("refresh_token") or raw.get("token") or raw.get("refreshToken") or "")
        )
        if not token:
            continue
        rows.append(
            {
                "label": str(raw.get("label") or raw.get("name") or "").strip(),
                "refresh_token": token,
                "direction": str(raw.get("direction") or "").strip(),
            }
        )
    if not rows:
        raise ValueError("没有可导入的账号行（支持：token / 备注|token / 备注|token|方向 / JSON）")

    data = _load_accounts_file()
    accounts: list[dict[str, Any]] = list(data.get("accounts") or [])
    existing_tokens = {
        _normalize_refresh_token(str(a.get("refresh_token") or ""))
        for a in accounts
        if a.get("refresh_token")
    }
    results: list[dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    skip_count = 0
    first_new_id = ""

    for idx, row in enumerate(rows):
        token = row["refresh_token"]
        label = row.get("label") or f"导入号{idx + 1}"
        direction = row.get("direction") or "AI 生成图爱好者，分享 NovelAI 同人插画"
        shape_err = _validate_refresh_token_shape(token)
        if shape_err:
            fail_count += 1
            results.append({"ok": False, "label": label, "message": shape_err, "line": idx + 1})
            continue
        if skip_duplicates and token in existing_tokens:
            skip_count += 1
            results.append(
                {
                    "ok": True,
                    "skipped": True,
                    "label": label,
                    "message": "refresh_token 已存在，已跳过",
                    "line": idx + 1,
                }
            )
            continue
        acc_id = f"acc_{uuid.uuid4().hex[:10]}"
        entry = {
            "id": acc_id,
            "label": label,
            "refresh_token": token,
            "pixiv_user_id": None,
            "direction": direction,
            "persona": {},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        accounts.append(entry)
        existing_tokens.add(token)
        if not first_new_id:
            first_new_id = acc_id
        if not data.get("active_id"):
            data["active_id"] = acc_id
        data["accounts"] = accounts
        _save_accounts_file(data)
        _TOKEN_CACHE.pop(acc_id, None)

        auth_ok = False
        auth_msg = "已导入（未校验）"
        user: dict[str, Any] = {}
        if verify:
            try:
                auth = test_account_auth(acc_id)
                auth_ok = bool(auth.get("ok"))
                auth_msg = (
                    auth.get("message")
                    if auth_ok
                    else ((auth.get("error") or {}).get("hint") or auth.get("message") or "登录校验失败")
                )
                if auth_ok:
                    user = auth.get("user") or {}
                    try:
                        _assert_pixiv_uid_available(
                            user.get("id"),
                            account_id=acc_id,
                            label=label,
                        )
                    except ValueError as exc:
                        auth_ok = False
                        auth_msg = str(exc)
                    if auth_ok:
                        store = _load_accounts_file()
                        for item in store.get("accounts") or []:
                            if item.get("id") == acc_id:
                                item["pixiv_user_id"] = user.get("id")
                                item["user_name"] = user.get("name") or ""
                                item["user_account"] = user.get("account") or ""
                                item["updated_at"] = _now_iso()
                                break
                        _save_accounts_file(store)
                        try:
                            refresh_account_stats(acc_id, force=True)
                        except Exception:
                            pass
            except Exception as exc:
                auth_ok = False
                auth_msg = str(exc)
        if auth_ok or not verify:
            ok_count += 1
        else:
            fail_count += 1
        results.append(
            {
                "ok": auth_ok if verify else True,
                "account_id": acc_id,
                "label": label,
                "message": auth_msg,
                "user_name": user.get("name") or "",
                "pixiv_user_id": user.get("id") or "",
                "line": idx + 1,
                "verified": verify,
            }
        )

    if set_first_active and first_new_id:
        store = _load_accounts_file()
        store["active_id"] = first_new_id
        _save_accounts_file(store)

    return {
        "ok": fail_count == 0,
        "total": len(rows),
        "ok_count": ok_count,
        "fail_count": fail_count,
        "skip_count": skip_count,
        "results": results,
        "accounts": list_accounts(),
        "active_id": get_active_account_id(),
        "message": (
            f"导入完成：成功 {ok_count} · 失败 {fail_count} · 跳过 {skip_count}"
            + ("（已在线校验）" if verify else "（未校验）")
        ),
    }


def update_account_token(account_id: str, refresh_token: str) -> dict[str, Any]:
    refresh_token = _normalize_refresh_token(refresh_token)
    if not refresh_token:
        raise ValueError("refresh_token 不能为空")
    shape_err = _validate_refresh_token_shape(refresh_token)
    if shape_err:
        raise ValueError(shape_err)
    data = _load_accounts_file()
    found = False
    for acc in data.get("accounts") or []:
        if acc.get("id") == account_id:
            acc["refresh_token"] = refresh_token
            acc["updated_at"] = _now_iso()
            found = True
            break
    if not found:
        raise ValueError("账号不存在")
    _save_accounts_file(data)
    _TOKEN_CACHE.pop(account_id, None)
    auth = test_account_auth(account_id)
    if auth.get("ok"):
        user = auth.get("user") or {}
        acc = _find_account(account_id) or {}
        _assert_pixiv_uid_available(
            user.get("id"),
            account_id=account_id,
            label=_account_label(acc),
        )
        store = _load_accounts_file()
        for item in store.get("accounts") or []:
            if item.get("id") == account_id:
                item["pixiv_user_id"] = user.get("id")
                item["user_name"] = user.get("name") or ""
                item["user_account"] = user.get("account") or ""
                item["updated_at"] = _now_iso()
                break
        _save_accounts_file(store)
    return {
        "ok": True,
        "account_id": account_id,
        "auth": auth,
        "message": auth.get("message") if auth.get("ok") else (auth.get("error") or {}).get("hint"),
    }


def switch_account(account_id: str) -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    if not account_id:
        raise ValueError("account_id 不能为空")
    data = _load_accounts_file()
    if not any(a.get("id") == account_id for a in data.get("accounts") or []):
        raise ValueError("账号不存在")
    data["active_id"] = account_id
    _save_accounts_file(data)
    acc = get_active_account()
    label = account_display_name(account_id)
    who = (acc or {}).get("user_name") or (acc or {}).get("user_account") or ""
    msg = f"已切换到「{label}」"
    if who:
        msg += f"（{who}）"
    msg += "，后续上传与 AI 导演将使用该账号"
    return {
        "ok": True,
        "active_id": account_id,
        "account": acc,
        "message": msg,
    }


def remove_account(account_id: str) -> dict[str, Any]:
    data = _load_accounts_file()
    accounts = [a for a in data.get("accounts") or [] if a.get("id") != account_id]
    if len(accounts) == len(data.get("accounts") or []):
        raise ValueError("账号不存在")
    data["accounts"] = accounts
    if data.get("active_id") == account_id:
        data["active_id"] = accounts[0]["id"] if accounts else ""
    if not accounts:
        data["allow_restore"] = False
    _save_accounts_file(data)
    _TOKEN_CACHE.pop(account_id, None)
    return {"ok": True, "active_id": data.get("active_id"), "accounts": list_accounts()}


def update_account_profile(
    account_id: str,
    *,
    label: str | None = None,
    direction: str | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _load_accounts_file()
    for acc in data.get("accounts") or []:
        if acc.get("id") != account_id:
            continue
        if label is not None:
            acc["label"] = str(label).strip() or acc.get("label") or "未命名"
        if direction is not None:
            acc["direction"] = str(direction).strip()
        if persona is not None and isinstance(persona, dict):
            warning = str(persona.get("warning") or "")
            if warning and any(marker in warning for marker in _STALE_AI_WARNING_MARKERS):
                persona = {k: v for k, v in persona.items() if k != "warning"}
            acc["persona"] = persona
        acc["updated_at"] = _now_iso()
        _save_accounts_file(data)
        return {"ok": True, "account": _public_account(acc)}
    raise ValueError("账号不存在")


def _oauth_client_time() -> str:
    # 与 Pixiv 官方 App 一致：本地时间 + +00:00 后缀
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _oauth_client_hash(client_time: str | None = None) -> str:
    ts = client_time or _oauth_client_time()
    return hashlib.md5((ts + PIXIV_HASH_SECRET).encode()).hexdigest()


def _pixiv_oauth_headers() -> dict[str, str]:
    """Pixiv OAuth 必须带 X-Client-Time / X-Client-Hash，否则常见 403。"""
    client_time = _oauth_client_time()
    return {
        "User-Agent": PIXIV_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "App-OS": PIXIV_APP_OS,
        "App-OS-Version": PIXIV_APP_OS_VERSION,
        "App-Version": PIXIV_APP_VERSION,
        "X-Client-Time": client_time,
        "X-Client-Hash": _oauth_client_hash(client_time),
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


def _pixiv_headers(access_token: str) -> dict[str, str]:
    return pixiv_api_headers(access_token)


def _normalize_refresh_token(raw: str) -> str:
    token = str(raw or "").strip()
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        token = token[1:-1].strip()
    return token


def _validate_refresh_token_shape(token: str) -> str | None:
    low = token.lower()
    if "password manager" in low or low in {"google", "chrome", "edge", "firefox"}:
        return "这是浏览器密码管理器误填的内容，不是 refresh_token。请用「通行密钥登录」或重新复制 token。"
    if len(token) < 32:
        return "refresh_token 太短，请确认复制完整（一般 64 位以上）"
    if any(ch.isspace() for ch in token):
        return "refresh_token 不能含空格或换行"
    if token.count(".") >= 2 and token.startswith("eyJ"):
        return "这看起来像 access_token（JWT），请填写 refresh_token"
    return None


def parse_oauth_error(status_code: int, body: str) -> dict[str, Any]:
    code: str | int | None = None
    message = str(body or "").strip()[:500]
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            system = (data.get("errors") or {}).get("system") or {}
            if isinstance(system, dict):
                code = system.get("code") or system.get("error_code")
                message = str(system.get("message") or message)
            err = data.get("error")
            if err and not code:
                code = err
            err_desc = data.get("error_description")
            if err_desc:
                message = str(err_desc)
    except Exception:
        pass

    hint = "请检查 refresh_token 是否完整、未过期。"
    code_str = str(code or "").strip()
    body_low = body.lower()
    if code_str == "918" or "oauth" in message.lower() and "client" in message.lower():
        hint = "Pixiv OAuth 客户端校验失败（code 918）。请更新到最新版 Pixiv NAI Gallery 后重试。"
    if status_code == 403:
        hint = (
            "Pixiv 拒绝了 OAuth 请求（403）。若 token 刚填入，先点「检测登录」；"
            "仍失败请重新获取 refresh_token（旧 token 可能已失效）。"
        )
    if code_str == "103" or "unknown error" in message.lower():
        hint = "Pixiv 返回 103：多为 token 无效/过期，或复制时多了引号空格。"
    if code_str in {"1508", "invalid_grant"} or "invalid_grant" in body_low:
        hint = "refresh_token 已失效或被撤销，请用浏览器扩展重新登录 Pixiv 获取新 token。"
    if "rate" in body_low or code_str in {"900", "429"}:
        hint = "请求过于频繁，请等待几分钟后再检测登录。"

    return {
        "status_code": status_code,
        "code": code,
        "message": message,
        "hint": hint,
        "raw": body[:300],
    }


def _oauth_refresh(refresh_token: str) -> dict[str, Any]:
    shape_err = _validate_refresh_token_shape(refresh_token)
    if shape_err:
        raise ValueError(shape_err)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.post(
            PIXIV_OAUTH_URL,
            data={
                "client_id": PIXIV_CLIENT_ID,
                "client_secret": PIXIV_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "get_secure_url": "1",
            },
            headers=_pixiv_oauth_headers(),
        )
    if resp.status_code >= 400:
        raise PixivAuthError(parse_oauth_error(resp.status_code, resp.text))
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Pixiv 返回了无法解析的登录响应")
    return data


def ensure_access_token(account_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """返回 (access_token, user_dict)。"""
    with _credential_process_lock():
        return _ensure_access_token_locked(account_id)


def _ensure_access_token_locked(
    account_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    account_id = account_id or get_active_account_id()
    acc = _find_account(account_id) if account_id else None
    if not acc:
        raise ValueError("未配置 Pixiv 账号，请先添加 refresh_token")

    now = time.time()
    cached = _TOKEN_CACHE.get(account_id) or {}
    if cached.get("access_token") and now < float(cached.get("expires_at") or 0):
        return str(cached["access_token"]), dict(cached.get("user") or {})

    refresh_token = _normalize_refresh_token(str(acc.get("refresh_token") or ""))
    if not refresh_token:
        raise ValueError(f"账号 {acc.get('label')} 未配置 refresh_token")

    data = _oauth_refresh(refresh_token)

    access_token = str(data.get("access_token") or "")
    if not access_token:
        raise RuntimeError("Pixiv 未返回 access_token")

    new_refresh = str(data.get("refresh_token") or "").strip()
    if new_refresh and new_refresh != refresh_token:
        update_account_token(account_id, new_refresh)

    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    _TOKEN_CACHE[account_id] = {
        "access_token": access_token,
        "expires_at": now + max(60, int(data.get("expires_in") or 3600) - 120),
        "user": user,
    }

    if user.get("id"):
        store = _load_accounts_file()
        for item in store.get("accounts") or []:
            if item.get("id") == account_id:
                item["pixiv_user_id"] = user.get("id")
                item["user_name"] = user.get("name") or ""
                item["user_account"] = user.get("account") or ""
                item["updated_at"] = _now_iso()
                break
        _save_accounts_file(store)

    return access_token, user


def _scrape_followers_from_web(user_id: Any) -> int | None:
    """Pixiv App API 常不返回粉丝数，从公开主页兜底读取。"""
    uid = _int_or_none(user_id)
    if uid is None:
        return None
    url = f"https://www.pixiv.net/users/{uid}"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "ja,en;q=0.8,zh-CN;q=0.6",
                },
            )
            if resp.status_code >= 400:
                return None
            text = resp.text or ""
    except Exception:
        return None

    patterns = [
        r'"followerCount"\s*:\s*(\d+)',
        r'"follower_count"\s*:\s*(\d+)',
        r'フォロワー[^0-9]{0,24}(\d[\d,]*)',
        r'followers?[^0-9]{0,24}(\d[\d,]*)',
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if not m:
            continue
        raw = str(m.group(1)).replace(",", "")
        parsed = _int_or_none(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_user_stats(detail: dict[str, Any]) -> dict[str, Any]:
    user = detail.get("user") if isinstance(detail.get("user"), dict) else detail
    profile = detail.get("profile") if isinstance(detail.get("profile"), dict) else {}
    followers = _first_int(
        user.get("follower_count"),
        user.get("total_follower"),
        user.get("followers"),
        profile.get("follower_count"),
        profile.get("total_follower"),
        profile.get("followers"),
        detail.get("follower_count"),
        detail.get("total_follower"),
    )
    views = _first_int(
        user.get("total_mypixiv_illust_views"),
        user.get("total_illust_views"),
        profile.get("total_illust_views"),
        profile.get("total_mypixiv_illust_views"),
    )
    following = _first_int(user.get("total_follow_users"), profile.get("total_follow_users"))
    illusts = _sum_present_ints(
        profile.get("total_illusts"),
        profile.get("total_manga"),
        profile.get("total_novels"),
    )
    if illusts is None:
        illusts = _first_int(user.get("total_illusts"))
    return {
        "followers": followers,
        "following": following,
        "illusts": illusts,
        "views": views,
        "user_name": str(user.get("name") or ""),
        "user_account": str(user.get("account") or ""),
        "pixiv_user_id": user.get("id"),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _sum_present_ints(*values: Any) -> int | None:
    seen = False
    total = 0
    for value in values:
        parsed = _int_or_none(value)
        if parsed is None:
            continue
        seen = True
        total += parsed
    return total if seen else None


def _upload_matches_account(
    upload: dict[str, Any],
    *,
    account_id: str,
    account: dict[str, Any],
) -> bool:
    upload_uid = _int_or_none(upload.get("user_id") or upload.get("pixiv_user_id"))
    account_uid = _int_or_none(account.get("pixiv_user_id"))
    if upload_uid is not None and account_uid is not None:
        return upload_uid == account_uid
    return str(upload.get("account_id") or "") == str(account_id or "")


def _fetch_user_work_totals(
    client: httpx.Client,
    headers: dict[str, str],
    user_id: Any,
) -> dict[str, int]:
    totals = {
        "views": 0,
        "bookmarks": 0,
        "comments": 0,
        "works": 0,
        "pages": 0,
    }
    seen_urls: set[str] = set()
    for work_type in ("illust", "manga"):
        url = f"{PIXIV_API_BASE}/v1/user/illusts"
        params: dict[str, Any] | None = {"user_id": user_id, "type": work_type}
        for _ in range(120):
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"获取用户作品列表失败 {resp.status_code}: {resp.text[:300]}")
            page = resp.json()
            for item in page.get("illusts") or []:
                totals["works"] += 1
                totals["views"] += int(item.get("total_view") or 0)
                totals["bookmarks"] += int(item.get("total_bookmarks") or 0)
                totals["comments"] += int(item.get("total_comments") or 0)
                totals["pages"] += int(item.get("page_count") or 1)
            next_url = str(page.get("next_url") or "")
            if not next_url or next_url in seen_urls:
                break
            seen_urls.add(next_url)
            url = next_url
            params = None
    return totals


def fetch_account_stats(account_id: str) -> dict[str, Any]:
    access_token, user = ensure_access_token(account_id)
    user_id = user.get("id") or (_find_account(account_id) or {}).get("pixiv_user_id")
    if not user_id:
        raise RuntimeError("无法获取 Pixiv user_id")

    headers = _pixiv_headers(access_token)
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{PIXIV_API_BASE}/v1/user/detail",
            params={"user_id": user_id},
            headers=headers,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"获取用户数据失败 {resp.status_code}: {resp.text[:300]}")
        detail = resp.json()
        stats = _parse_user_stats(detail if isinstance(detail, dict) else {})
        try:
            work_totals = _fetch_user_work_totals(client, headers, user_id)
            stats["views"] = work_totals["views"]
            stats["bookmarks"] = work_totals["bookmarks"]
            stats["comments"] = work_totals["comments"]
            stats["work_pages"] = work_totals["pages"]
            if stats.get("illusts") is None:
                stats["illusts"] = work_totals["works"]
        except Exception as exc:
            stats["views_error"] = str(exc)[:200]

    if _int_or_none(stats.get("followers")) is None:
        scraped = _scrape_followers_from_web(user_id)
        if scraped is not None:
            stats["followers"] = scraped
            stats["followers_source"] = "web_profile"

    stats["captured_at"] = _now_iso()
    return stats


def account_display_name(account_id: str) -> str:
    acc = _find_account(account_id) or {}
    return (
        str(acc.get("label") or "").strip()
        or str(acc.get("user_name") or "").strip()
        or str(account_id or "").strip()
        or "未命名"
    )


def _filter_account_history(
    account_id: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """只保留与当前 Pixiv 用户一致的历史点，避免换 token 后数据串号。"""
    if not history:
        return []
    acc = _find_account(account_id) or {}
    expected_uid = _int_or_none(acc.get("pixiv_user_id"))
    if expected_uid is not None:
        matched = [
            item
            for item in history
            if _int_or_none(item.get("pixiv_user_id")) == expected_uid
        ]
        if matched:
            return matched
    last_uid = _int_or_none(history[-1].get("pixiv_user_id"))
    if last_uid is not None:
        return [
            item
            for item in history
            if _int_or_none(item.get("pixiv_user_id")) == last_uid
        ]
    return list(history)


def _merge_stats_snapshots(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    """合并快照：避免 API 偶发空值/归零覆盖已有粉丝/浏览数据。"""
    prev = previous or {}
    out = dict(current)
    soft_keys = ("followers", "views", "illusts")
    for key in ("followers", "following", "views", "illusts", "bookmarks", "comments", "work_pages"):
        cur = _int_or_none(out.get(key))
        old = _int_or_none(prev.get(key))
        if cur is None and old is not None:
            out[key] = old
        elif (
            key in soft_keys
            and cur == 0
            and old is not None
            and old > 0
        ):
            out[key] = old
    if _int_or_none(out.get("followers")) is None and prev.get("followers_source"):
        out["followers_source"] = prev.get("followers_source")
    return out


def _load_stats_db() -> dict[str, Any]:
    if not STATS_PATH.exists():
        return {"accounts": {}, "last_refresh_at": ""}
    try:
        data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"accounts": {}}
    except Exception:
        return {"accounts": {}, "last_refresh_at": ""}


def _save_stats_db(data: dict[str, Any]) -> None:
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        STATS_PATH,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _calc_delta(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    prev = previous or {}
    out: dict[str, Any] = {}
    for key in ("followers", "views", "illusts", "following"):
        cur = _int_or_none(current.get(key))
        old = _int_or_none(prev.get(key))
        if cur is None or old is None:
            out[key] = None
            continue
        diff = cur - old
        if diff < 0 and key in ("followers", "views", "illusts") and old > 0 and cur == 0:
            out[key] = None
            continue
        out[key] = diff
    return out


def _stats_summary(account_id: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    acc = _find_account(account_id)
    history = _filter_account_history(account_id, history)
    latest = history[-1] if history else {}
    prev = history[-2] if len(history) >= 2 else None
    delta = _calc_delta(latest, prev) if latest else {}
    user_account = latest.get("user_account") or (acc or {}).get("user_account") or ""
    return {
        "account_id": account_id,
        "label": (acc or {}).get("label") or account_id,
        "pixiv_user_id": latest.get("pixiv_user_id") or (acc or {}).get("pixiv_user_id"),
        "user_name": latest.get("user_name") or (acc or {}).get("user_name") or "",
        "user_account": user_account,
        "latest": latest,
        "delta": delta,
        "delta_since": (prev or {}).get("captured_at") or "",
        "history_points": len(history),
        "history": history[-12:],
        "delta_reliable": len(history) >= 2,
    }


def refresh_account_stats(account_id: str, *, force: bool = False) -> dict[str, Any]:
    with _STATS_LOCK:
        db = _load_stats_db()
        histories: dict[str, list] = db.setdefault("accounts", {})
        raw_hist: list[dict[str, Any]] = list(histories.get(account_id) or [])
        hist = _filter_account_history(account_id, raw_hist)
        if len(hist) != len(raw_hist):
            histories[account_id] = hist[-120:]

        if not force and hist:
            try:
                last_at = datetime.fromisoformat(str(hist[-1].get("captured_at")))
                interval = float(_load_accounts_file().get("refresh_interval_hours") or REFRESH_INTERVAL_HOURS)
                if datetime.now() - last_at < timedelta(hours=interval):
                    return _stats_summary(account_id, hist)
            except Exception:
                pass

        snap = fetch_account_stats(account_id)
        new_uid = _int_or_none(snap.get("pixiv_user_id"))
        last_uid = _int_or_none(hist[-1].get("pixiv_user_id")) if hist else None
        if hist and new_uid is not None and last_uid is not None and new_uid != last_uid:
            hist = []
        snap = _merge_stats_snapshots(hist[-1] if hist else None, snap)
        if hist and hist[-1].get("captured_at"):
            if (
                _int_or_none(hist[-1].get("followers")) == _int_or_none(snap.get("followers"))
                and _int_or_none(hist[-1].get("views")) == _int_or_none(snap.get("views"))
                and _int_or_none(hist[-1].get("illusts")) == _int_or_none(snap.get("illusts"))
            ):
                hist[-1] = {**hist[-1], **snap, "captured_at": snap["captured_at"]}
            else:
                hist.append(snap)
        else:
            hist.append(snap)

        histories[account_id] = _filter_account_history(account_id, hist)[-120:]
        db["last_refresh_at"] = _now_iso()
        _save_stats_db(db)
        return _stats_summary(account_id, histories[account_id])


def refresh_all_stats(*, force: bool = False) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for acc in list_accounts():
        if not acc.get("has_token"):
            continue
        aid = str(acc.get("id") or "")
        try:
            items.append(refresh_account_stats(aid, force=force))
        except Exception as exc:
            errors.append({"account_id": aid, "message": str(exc)})
    return {
        "ok": True,
        "items": items,
        "errors": errors,
        "last_refresh_at": _load_stats_db().get("last_refresh_at") or "",
        "refresh_interval_hours": _load_accounts_file().get("refresh_interval_hours") or REFRESH_INTERVAL_HOURS,
    }


def list_stats_dashboard() -> dict[str, Any]:
    db = _load_stats_db()
    histories = db.get("accounts") or {}
    items = []
    dirty = False
    for acc in list_accounts():
        aid = str(acc.get("id") or "")
        raw_hist = histories.get(aid) or []
        hist = _filter_account_history(aid, raw_hist)
        if len(hist) != len(raw_hist):
            histories[aid] = hist[-120:]
            dirty = True
        items.append(_stats_summary(aid, hist))
    if dirty:
        db["accounts"] = histories
        _save_stats_db(db)
    return {
        "ok": True,
        "active_id": get_active_account_id(),
        "items": items,
        "last_refresh_at": db.get("last_refresh_at") or "",
        "refresh_interval_hours": _load_accounts_file().get("refresh_interval_hours") or REFRESH_INTERVAL_HOURS,
    }


def test_account_auth(account_id: str | None = None) -> dict[str, Any]:
    account_id = account_id or get_active_account_id()
    acc = _find_account(account_id) if account_id else None
    if not account_id or not acc:
        return {
            "ok": False,
            "account_id": account_id,
            "message": "未配置 Pixiv 账号",
            "error": {"hint": "请先添加 refresh_token"},
        }
    token = _normalize_refresh_token(str(acc.get("refresh_token") or ""))
    if not token:
        return {
            "ok": False,
            "account_id": account_id,
            "message": "未配置 refresh_token",
            "error": {"hint": "请在下方填入 refresh_token"},
        }
    shape_err = _validate_refresh_token_shape(token)
    if shape_err:
        return {
            "ok": False,
            "account_id": account_id,
            "message": shape_err,
            "error": {"hint": shape_err},
        }
    try:
        _TOKEN_CACHE.pop(account_id, None)
        _, user = ensure_access_token(account_id)
        return {
            "ok": True,
            "account_id": account_id,
            "user": user,
            "message": f"登录有效：{user.get('name') or user.get('account') or 'Pixiv 用户'}",
        }
    except ValueError as exc:
        return {
            "ok": False,
            "account_id": account_id,
            "message": str(exc),
            "error": {"hint": str(exc)},
        }
    except PixivAuthError as exc:
        detail = dict(exc.detail or {})
        return {
            "ok": False,
            "account_id": account_id,
            "message": str(exc),
            "error": detail,
        }
    except Exception as exc:
        return {
            "ok": False,
            "account_id": account_id,
            "message": str(exc),
            "error": {"hint": str(exc)},
        }


def _save_login_result(
    result: dict[str, Any],
    *,
    account_id: str | None = None,
    label: str = "",
    direction: str = "",
) -> dict[str, Any]:
    refresh_token = str(result.get("refresh_token") or "").strip()
    if not refresh_token:
        raise RuntimeError("登录完成但未获取到 refresh_token")

    user = result.get("user") or {}
    target_id = str(account_id or "").strip() or get_active_account_id()
    if target_id and _find_account(target_id):
        out = update_account_token(target_id, refresh_token)
    else:
        out = add_account(
            refresh_token=refresh_token,
            label=label or str(user.get("name") or user.get("account") or "Pixiv 账号"),
            direction=direction,
        )
        target_id = str((out.get("account") or {}).get("id") or out.get("active_id") or "")

    if user.get("id"):
        data = _load_accounts_file()
        for acc in data.get("accounts") or []:
            if acc.get("id") == target_id:
                acc["pixiv_user_id"] = user.get("id")
                acc["updated_at"] = _now_iso()
                break
        _save_accounts_file(data)

    auth = out.get("auth") or test_account_auth(target_id)
    return {
        "ok": bool(auth.get("ok")),
        "account_id": target_id,
        "user": auth.get("user") or user,
        "message": auth.get("message") if auth.get("ok") else (auth.get("error") or {}).get("hint"),
        "auth": auth,
        "error": auth.get("error"),
    }


def login_with_browser(
    *,
    account_id: str | None = None,
    label: str = "",
    direction: str = "",
) -> dict[str, Any]:
    """仅打开浏览器登录（支持通行密钥 / 手动登录），换取 refresh_token。"""
    from pixiv_browser_login import browser_login_pixiv_sync

    target_id = str(account_id or "").strip() or get_active_account_id()
    result = browser_login_pixiv_sync(account_id=target_id)
    return _save_login_result(
        result,
        account_id=target_id or account_id,
        label=label,
        direction=direction,
    )


def login_with_email_password(
    username: str,
    password: str,
    *,
    account_id: str | None = None,
    label: str = "",
    direction: str = "",
) -> dict[str, Any]:
    """邮箱/ID + 密码浏览器登录，换取 refresh_token 并保存。密码不落盘。"""
    from pixiv_browser_login import browser_login_pixiv_sync

    username = str(username or "").strip()
    password = str(password or "")
    if not username:
        raise ValueError("请填写 Pixiv 邮箱或 ID")
    if not password:
        raise ValueError("请填写 Pixiv 密码")

    target_id = str(account_id or "").strip() or get_active_account_id()
    result = browser_login_pixiv_sync(
        username=username,
        password=password,
        account_id=target_id,
    )
    return _save_login_result(
        result,
        account_id=target_id or account_id,
        label=label,
        direction=direction,
    )


def accounts_auth_status(account_id: str | None = None) -> dict[str, Any]:
    account_id = account_id or get_active_account_id()
    acc = get_active_account() if account_id == get_active_account_id() else _public_account(_find_account(account_id) or {})
    if not account_id or not (acc or {}).get("has_token"):
        return {
            "ok": False,
            "has_refresh_token": False,
            "active_id": account_id,
            "account": acc,
            "message": "未配置 Pixiv 账号",
        }
    result = test_account_auth(account_id)
    return {
        "ok": bool(result.get("ok")),
        "has_refresh_token": True,
        "active_id": account_id,
        "account": acc,
        "user": result.get("user") or {},
        "message": result.get("message") or "",
        "error": result.get("error"),
    }


def _load_analytics_cache() -> dict[str, Any]:
    if not ANALYTICS_PATH.exists():
        return {"by_account": {}}
    try:
        data = json.loads(ANALYTICS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"by_account": {}}
    except Exception:
        return {"by_account": {}}


def _save_analytics_cache(data: dict[str, Any]) -> None:
    ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANALYTICS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate_analytics(
    *,
    account_id: str | None = None,
    chat_completion: Any,
    upload_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """需要传入 pixiv_launch._chat_completion 避免循环导入。"""
    account_id = account_id or get_active_account_id()
    acc = _find_account(account_id)
    if not acc:
        raise ValueError("账号不存在")

    dashboard = list_stats_dashboard()
    item = next((x for x in dashboard.get("items") or [] if x.get("account_id") == account_id), None)
    history = (item or {}).get("history") or []
    uploads = [
        u for u in (upload_history or [])
        if isinstance(u, dict)
        and _upload_matches_account(u, account_id=account_id, account=acc)
    ][:10]

    payload = {
        "account": {
            "label": acc.get("label"),
            "direction": acc.get("direction"),
            "persona": acc.get("persona") or {},
        },
        "stats_history": history,
        "latest": (item or {}).get("latest") or {},
        "delta": (item or {}).get("delta") or {},
        "recent_uploads": uploads,
        "context": "账号定位：AI 生成图（NovelAI 等）爱好者发图，不是职业手绘画师。",
    }

    from pixiv_launch import _ai_env, load_config

    env = _ai_env(load_config())
    if not env.get("api_key"):
        raise ValueError("未配置 AI API Key，无法生成数据分析")

    text = chat_completion(env, ANALYTICS_SYSTEM, payload)
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        result = json.loads(raw[start : end + 1]) if start >= 0 and end > start else {"summary": raw}

    if not isinstance(result, dict):
        result = {"summary": str(result)}

    cache = _load_analytics_cache()
    cache.setdefault("by_account", {})[account_id] = {
        "generated_at": _now_iso(),
        "result": result,
    }
    _save_analytics_cache(cache)

    return {"ok": True, "account_id": account_id, "analysis": result, "generated_at": cache["by_account"][account_id]["generated_at"]}


ANALYTICS_ALL_SYSTEM = """你是 Pixiv 多账号矩阵运营顾问，客户都是用 NovelAI / Stable Diffusion 发 AI 图的爱好者。
根据多个账号的粉丝、浏览量、作品数历史与变化，给出矩阵级运营策略。
只返回一个 JSON 对象，不要 Markdown，不要解释。

JSON 字段：
summary（250字内总览）,
account_highlights（对象数组，每项含 account_label, status, key_metric, note）,
trends（字符串数组，3-6条跨账号趋势）,
recommendations（字符串数组，4-8条可执行建议，可指定账号）,
risks（字符串数组，0-4条）,
next_actions（字符串数组，4-6条按优先级排序）

硬规则：
- 对比各账号增速，指出表现好/需加油的账号。
- 建议符合 AI 发图爱好者定位，不要装职业画师。
- 样本不足时说明并给冷启动矩阵策略。"""


def generate_analytics_all(
    *,
    chat_completion: Any,
    upload_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dashboard = list_stats_dashboard()
    payload = {
        "accounts_stats": dashboard.get("items") or [],
        "last_refresh_at": dashboard.get("last_refresh_at") or "",
        "refresh_interval_hours": dashboard.get("refresh_interval_hours") or REFRESH_INTERVAL_HOURS,
        "recent_uploads": (upload_history or [])[:20],
        "context": "多账号矩阵：均为 AI 生成图爱好者账号，用 NovelAI 等工具发二次元插画。",
    }
    from pixiv_launch import _ai_env, load_config

    env = _ai_env(load_config())
    if not env.get("api_key"):
        raise ValueError("未配置 AI API Key，无法生成数据分析")

    text = chat_completion(env, ANALYTICS_ALL_SYSTEM, payload)
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        result = json.loads(raw[start : end + 1]) if start >= 0 and end > start else {"summary": raw}

    if not isinstance(result, dict):
        result = {"summary": str(result)}

    cache = _load_analytics_cache()
    cache["all_accounts"] = {"generated_at": _now_iso(), "result": result}
    _save_analytics_cache(cache)
    return {"ok": True, "account_id": "all", "analysis": result, "generated_at": cache["all_accounts"]["generated_at"]}


def get_cached_analytics(account_id: str | None = None) -> dict[str, Any]:
    account_id = account_id or get_active_account_id()
    cache = _load_analytics_cache()
    if account_id == "all":
        entry = cache.get("all_accounts") or {}
        return {
            "ok": True,
            "account_id": "all",
            "analysis": entry.get("result") or {},
            "generated_at": entry.get("generated_at") or "",
        }
    by_account = cache.get("by_account") or {}
    entry = by_account.get(account_id) or {}
    return {
        "ok": True,
        "account_id": account_id,
        "analysis": entry.get("result") or {},
        "generated_at": entry.get("generated_at") or "",
    }


def start_stats_scheduler() -> None:
    global _SCHEDULER_STARTED, _SCHEDULER_THREAD
    if _SCHEDULER_STARTED:
        return
    _SCHEDULER_STARTED = True
    _SCHEDULER_STOP.clear()

    def _loop() -> None:
        while not _SCHEDULER_STOP.is_set():
            try:
                refresh_all_stats(force=False)
            except Exception:
                pass
            hours = float(_load_accounts_file().get("refresh_interval_hours") or REFRESH_INTERVAL_HOURS)
            if _SCHEDULER_STOP.wait(max(1.0, hours * 3600)):
                break

    _SCHEDULER_THREAD = threading.Thread(
        target=_loop,
        daemon=True,
        name="pixiv-stats-refresh",
    )
    _SCHEDULER_THREAD.start()


def stop_stats_scheduler() -> None:
    global _SCHEDULER_STARTED, _SCHEDULER_THREAD
    _SCHEDULER_STOP.set()
    thread = _SCHEDULER_THREAD
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)
    _SCHEDULER_THREAD = None
    _SCHEDULER_STARTED = False
