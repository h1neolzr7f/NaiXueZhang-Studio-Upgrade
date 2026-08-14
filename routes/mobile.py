"""Android / phone shell and LAN pairing for write operations."""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

from server_shared import WEB_DIR

page_router = APIRouter()
router = APIRouter(prefix="/api/mobile")

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
_PAIR_TTL_SEC = 10 * 60
_MOBILE_TTL_SEC = 12 * 60 * 60
_MOBILE_MAX = 5
_LOCK = threading.Lock()
_PAIR: dict[str, object] = {}
_MOBILE_TOKENS: dict[str, dict[str, object]] = {}

_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate"}
_MOBILE_INDEX = Path(WEB_DIR) / "m" / "index.html"
_PAIR_CLAIM_PATHS = frozenset({"/api/mobile/pair/claim"})


def is_pair_claim_path(path: str) -> bool:
    return str(path or "").rstrip("/") in _PAIR_CLAIM_PATHS


def is_mobile_token(token: str) -> bool:
    value = str(token or "").strip()
    if not value:
        return False
    now = time.time()
    with _LOCK:
        meta = _MOBILE_TOKENS.get(value)
        if not meta:
            return False
        if float(meta.get("expires") or 0) <= now:
            _MOBILE_TOKENS.pop(value, None)
            return False
        return True


def reset_mobile_pairing() -> None:
    with _LOCK:
        _PAIR.clear()
        _MOBILE_TOKENS.clear()


def _client_host(request: Request) -> str:
    return str(request.client.host if request.client else "").strip()


def _is_loopback(request: Request) -> bool:
    return _client_host(request) in _LOOPBACK


def _require_loopback(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="配对管理仅限本机回环客户端")


def _listen_port() -> int:
    try:
        return int(os.environ.get("GALLERY_PORT", "8797") or 8797)
    except (TypeError, ValueError):
        return 8797


def lan_mobile_urls(port: int | None = None) -> list[str]:
    listen = int(port or _listen_port())
    found: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        outbound = str(probe.getsockname()[0] or "")
        probe.close()
        if outbound and not outbound.startswith("127."):
            found.append(f"http://{outbound}:{listen}/m")
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0] or "")
            if ip and not ip.startswith("127."):
                found.append(f"http://{ip}:{listen}/m")
    except OSError:
        pass
    return list(dict.fromkeys(found))


def _purge_expired_locked(now: float) -> None:
    expired = [key for key, meta in _MOBILE_TOKENS.items() if float(meta.get("expires") or 0) <= now]
    for key in expired:
        _MOBILE_TOKENS.pop(key, None)
    if _PAIR and float(_PAIR.get("expires") or 0) <= now:
        _PAIR.clear()


@page_router.get("/m")
def mobile_page() -> FileResponse:
    if not _MOBILE_INDEX.is_file():
        raise HTTPException(status_code=404, detail="mobile shell is missing")
    return FileResponse(_MOBILE_INDEX, headers=_NO_STORE)


@page_router.get("/m/{rest:path}")
def mobile_page_rest(rest: str) -> FileResponse:
    return mobile_page()


@router.get("/status")
def api_mobile_status(request: Request) -> dict:
    loopback = _is_loopback(request)
    remote_listen = os.environ.get("GALLERY_ALLOW_REMOTE") == "1"
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        pair_active = bool(_PAIR) and float(_PAIR.get("expires") or 0) > now
        sessions = len(_MOBILE_TOKENS) if loopback else 0
    return {
        "ok": True,
        "loopback": loopback,
        "remote_listen": remote_listen,
        "urls": lan_mobile_urls() if loopback else [],
        "pair_active": pair_active,
        "mobile_sessions": sessions,
        "pair_ttl_sec": _PAIR_TTL_SEC,
        "session_ttl_sec": _MOBILE_TTL_SEC,
    }


@router.post("/pair/start")
def api_mobile_pair_start(request: Request) -> dict:
    _require_loopback(request)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = time.time()
    expires = now + _PAIR_TTL_SEC
    with _LOCK:
        _purge_expired_locked(now)
        _PAIR.clear()
        _PAIR.update({"code": code, "expires": expires, "created": now})
    return {
        "ok": True,
        "code": code,
        "expires_at": int(expires),
        "ttl_sec": _PAIR_TTL_SEC,
        "urls": lan_mobile_urls(),
        "remote_listen": os.environ.get("GALLERY_ALLOW_REMOTE") == "1",
        "message": "在手机打开局域网地址后输入配对码。配对码 10 分钟内有效。",
    }


@router.post("/pair/claim")
def api_mobile_pair_claim(payload: dict = Body(default_factory=dict)) -> dict:
    code = str((payload or {}).get("code") or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="配对码须为 6 位数字")
    now = time.time()
    with _LOCK:
        _purge_expired_locked(now)
        expected = str(_PAIR.get("code") or "")
        if not expected or expected != code:
            raise HTTPException(status_code=403, detail="配对码无效或已过期")
        _PAIR.clear()
        if len(_MOBILE_TOKENS) >= _MOBILE_MAX:
            oldest = min(_MOBILE_TOKENS.items(), key=lambda item: float(item[1].get("created") or 0))[0]
            _MOBILE_TOKENS.pop(oldest, None)
        token = secrets.token_urlsafe(32)
        expires = now + _MOBILE_TTL_SEC
        _MOBILE_TOKENS[token] = {"expires": expires, "created": now}
    return {
        "ok": True,
        "token": token,
        "expires_at": int(expires),
        "ttl_sec": _MOBILE_TTL_SEC,
        "message": "手机已配对，可以换角和生成。关闭浏览器后 12 小时内仍可继续。",
    }


@router.post("/pair/revoke")
def api_mobile_pair_revoke(request: Request) -> dict:
    _require_loopback(request)
    with _LOCK:
        dropped = len(_MOBILE_TOKENS)
        _MOBILE_TOKENS.clear()
        _PAIR.clear()
    return {"ok": True, "revoked": dropped, "message": "已撤销全部手机配对"}
