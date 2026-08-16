import json
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from static_asset_security import SafeStaticFiles
from routes.compliance import router as compliance_router, page_router as compliance_page_router

try:
    from server_shared import (
        CONFIG,
        DB,
        DATA_DIR,
        WEB_DIR,
        CRAWLER_WATCHDOG,
        _CDN_CLIENT,
    )
except OSError as exc:
    # 数据目录不可写/权限不足时，给出可操作的中文提示而不是一坨 traceback。
    raise SystemExit(
        "启动失败：数据目录不可写或权限不足，无法初始化本地数据。\n"
        f"详情：{exc}\n"
        "请检查数据目录（默认 ./data）的写入权限，或以有足够权限的用户重新运行 START_GALLERY.bat。"
    ) from exc
from generated_gallery import migrate_legacy_meta
from gallery_catalog import close_all_gallery_dbs
from pixiv_accounts import start_stats_scheduler, stop_stats_scheduler
from runtime_resources import RuntimeResources
from routes import (
    aitag,
    butler,
    char_swap,
    crawler,
    director,
    gallery,
    maintenance,
    update as update_routes,
    nai_tags,
    nai,
    online,
    pipeline,
    pixiv,
    pixiv_intake,
    product,
    references,
    settings,
    studio,
)

_GENERATED_MAINTENANCE_STARTED = False
RUNTIME_RESOURCES = RuntimeResources(
    db=DB,
    watchdog=CRAWLER_WATCHDOG,
    http_client=_CDN_CLIENT,
    start_stats_scheduler=start_stats_scheduler,
    stop_stats_scheduler=stop_stats_scheduler,
    extra_close=close_all_gallery_dbs,
)


def _start_generated_maintenance_once() -> None:
    global _GENERATED_MAINTENANCE_STARTED
    if _GENERATED_MAINTENANCE_STARTED:
        return
    _GENERATED_MAINTENANCE_STARTED = True

    def _run() -> None:
        try:
            migrate_legacy_meta()
        except Exception as exc:
            print(f"WARNING: 生成库元数据迁移失败：{exc}", flush=True)
        try:
            from generated_gallery import ensure_all_thumbnails

            ensure_all_thumbnails()
        except Exception as exc:
            print(f"WARNING: 生成库缩略图维护失败：{exc}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


def _start_char_swap_warmup_once() -> None:
    """Preload char-swap tag indexes in a background thread so the first
    transform/extract on a cold start does not pay the one-time load cost."""

    def _run() -> None:
        try:
            from char_tag_db import load_index, classify_caption_cached
            from nai_char import _ark_library_tags, _danbooru_recognition_characters
            from char_swap_config import load_config as load_char_swap_config

            load_index(force=False)
            load_char_swap_config()
            _ark_library_tags()
            _danbooru_recognition_characters()
            classify_caption_cached("1girl, solo")
        except Exception as exc:
            print(f"WARNING: 换角索引预热失败：{exc}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        RUNTIME_RESOURCES.start()
        _start_generated_maintenance_once()
        _start_char_swap_warmup_once()
        yield
    finally:
        RUNTIME_RESOURCES.close()


app = FastAPI(title="Pixiv NAI Gallery", lifespan=_lifespan)

# Per-process session token for write-op CSRF protection: the browser obtains
# it once from /api/session-token (same-origin, CORS-restricted) and sends it
# back in X-Session-Token on every POST/PATCH/DELETE. Requests without a
# matching token are rejected unless they are read-only (GET/HEAD/OPTIONS).
SESSION_TOKEN: str = secrets.token_urlsafe(32)
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _require_session_token(request: Request, call_next):
    if request.method.upper() in _WRITE_METHODS:
        provided = request.headers.get("x-session-token") or ""
        if provided != SESSION_TOKEN:
            return JSONResponse(status_code=403, content={"detail": "缺少有效的会话令牌（X-Session-Token）"})
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=_require_session_token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8797", "http://localhost:8797"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if WEB_DIR.exists():
    app.mount("/assets", SafeStaticFiles(directory=str(WEB_DIR)), name="assets")

GENERATED_DIR = DATA_DIR / "generated"
try:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    raise SystemExit(
        f"启动失败：数据目录不可写，无法创建 {GENERATED_DIR}。\n"
        f"详情：{exc}\n"
        "请检查数据目录的写入权限（例如被杀毒软件/ Controlled Folder Access 拦截），"
        "或以有足够权限的用户重新运行 START_GALLERY.bat。"
    ) from exc

_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost"}


@app.get("/api/session-token")
def api_session_token(request: Request) -> dict:
    """Return the per-process session token (read-only; CORS restricts
    cross-origin reads, so only same-origin pages can obtain it).

    即使设置了 GALLERY_ALLOW_REMOTE=1 监听局域网，令牌也只发给回环客户端，
    避免远程机器拿到写操作令牌后获得完整管理权限。
    """
    client_host = str(request.client.host if request.client else "").strip()
    if client_host not in _LOOPBACK_CLIENTS:
        raise HTTPException(status_code=403, detail="会话令牌仅对本机回环客户端开放")
    return {"token": SESSION_TOKEN}


# Include sub-routers
app.include_router(product.page_router)
app.include_router(product.router)
app.include_router(pixiv.router)
app.include_router(studio.router)
app.include_router(update_routes.router)
app.include_router(butler.router)
app.include_router(director.router)
app.include_router(references.router)
app.include_router(aitag.router)
app.include_router(settings.router)
app.include_router(char_swap.router)
app.include_router(nai.router)
app.include_router(online.router)
app.include_router(pipeline.router)
app.include_router(crawler.router)
app.include_router(pixiv_intake.router)
app.include_router(maintenance.router)
app.include_router(compliance_router)
app.include_router(compliance_page_router)
app.include_router(maintenance.page_router)
app.include_router(nai_tags.router)
app.include_router(nai_tags.page_router)
# Gallery owns the root page and a final `/{filename}` compatibility fallback.
# Register it after every specific page/API router so the fallback cannot shadow
# newer upgraded pages such as Butler or Director.
app.include_router(gallery.router)

if __name__ == "__main__":
    import sys
    import threading
    import time
    import webbrowser

    import uvicorn

    from local_secrets import protection_unavailable_reason

    secret_warning = protection_unavailable_reason()
    if secret_warning:
        print(f"WARNING: {secret_warning}", flush=True)

    port = int(os.environ.get("GALLERY_PORT", "8797"))

    # 信任模型：本服务无真实用户认证，/api/session-token 对本机任何进程开放，
    # 因此只允许监听 loopback。GALLERY_HOST 覆盖为非 loopback 地址时必须同时
    # 设置 GALLERY_ALLOW_REMOTE=1 明确确认，否则拒绝启动。
    host = str(os.environ.get("GALLERY_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    _loopback = {"127.0.0.1", "localhost", "::1"}
    if host not in _loopback:
        if os.environ.get("GALLERY_ALLOW_REMOTE") != "1":
            raise SystemExit(
                f"拒绝监听非本机地址 {host!r}：本服务采用同机完全信任模型，"
                "绑定局域网/公网会让同网段任何人获得完整管理权限。"
                "确知风险仍要继续，请设置 GALLERY_ALLOW_REMOTE=1。"
            )
        print(
            f"WARNING: listening on {host!r}; any host that can reach this port "
            "has full admin access (local trust model).",
            flush=True,
        )

    if getattr(sys, "frozen", False):
        # Standalone EXE: open the browser once the server is listening.
        def _open_browser() -> None:
            time.sleep(2.5)
            try:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            except Exception:
                pass

        threading.Thread(target=_open_browser, daemon=True).start()

    # 预检端口：占用时给出明确提示（多半是已有一个实例在运行），
    # 而不是让 uvicorn 打出一行英文 bind 错误后退出。
    import socket

    _family = socket.AF_INET6 if ":" in host else socket.AF_INET
    _probe = socket.socket(_family, socket.SOCK_STREAM)
    try:
        _probe.bind((host, port))
    except OSError:
        print(
            f"启动失败：端口 {port} 已被占用。很可能已经有一个图库实例正在运行，"
            "请直接使用已打开的窗口/浏览器页面；如需重启，请先结束旧进程 "
            "（或关闭之前的 START_GALLERY.bat 窗口）后再启动。",
            flush=True,
        )
        raise SystemExit(1)
    finally:
        _probe.close()

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
    )
