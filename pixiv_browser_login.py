"""Pixiv 浏览器 OAuth 登录（通行密钥 / 邮箱密码），换取 refresh_token。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import getproxies

import httpx
from playwright.async_api import Request, Response, async_playwright

from paths import data_dir

ROOT = Path(__file__).resolve().parent
PROFILE_DIR: Path | None = None
PROFILES_ROOT: Path | None = None


def _profile_dir() -> Path:
    return Path(PROFILE_DIR) if PROFILE_DIR is not None else data_dir() / "pixiv_chrome_profile"


def _profiles_root() -> Path:
    return Path(PROFILES_ROOT) if PROFILES_ROOT is not None else data_dir() / "pixiv_chrome_profiles"


def profile_dir_for_account(account_id: str = "") -> Path:
    """每个本地账号使用独立 Chrome 配置，避免切号后仍用旧 Pixiv 登录态投稿。"""
    account_id = str(account_id or "").strip()
    if not account_id:
        path = _profile_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    path = _profiles_root() / account_id
    path.mkdir(parents=True, exist_ok=True)
    legacy = _profile_dir()
    marker = _profiles_root() / f".legacy_migrated_{account_id}"
    if marker.exists() or not legacy.exists():
        return path
    try:
        has_legacy = any(legacy.iterdir())
    except Exception:
        has_legacy = False
    if not has_legacy:
        return path

    import shutil

    try:
        for item in legacy.iterdir():
            dest = path / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        marker.write_text("ok", encoding="utf-8")
    except Exception:
        pass
    return path

LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
AUTH_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
CALLBACK_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
POST_REDIRECT = "https://accounts.pixiv.net/post-redirect"
CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
USER_AGENT = "PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)"
DEFAULT_WAIT_SECONDS = 300

_CODE_RE = re.compile(r"[?&#]code=([^&\s\"']+)")


def oauth_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def proxy_settings() -> dict | None:
    proxies = getproxies()
    server = proxies.get("https") or proxies.get("http") or proxies.get("all")
    if not server:
        return None
    return {"server": server}


def extract_code(url: str) -> str | None:
    if "code=" not in url:
        return None
    m = _CODE_RE.search(url)
    return m.group(1) if m else None


def exchange_code(code: str, code_verifier: str) -> dict:
    with httpx.Client(timeout=30.0, trust_env=True) as client:
        resp = client.post(
            AUTH_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "include_policy": "true",
                "redirect_uri": CALLBACK_URI,
            },
            headers={
                "user-agent": USER_AGENT,
                "app-os-version": "14.6",
                "app-os": "ios",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"换取 token 失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Pixiv 返回了无法解析的 token 响应")
    return data


async def _slow_type(locator, text: str) -> None:
    await locator.click()
    await locator.fill("")
    for ch in text:
        await locator.type(ch, delay=60)


async def _fill_login_form(page, username: str, password: str) -> None:
    user_selectors = [
        "input[autocomplete^='username']",
        "input[type='email']",
        "input[name='login_id']",
    ]
    pass_selectors = [
        "input[autocomplete^='current-password']",
        "input[type='password']",
    ]
    user_el = None
    for sel in user_selectors:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(timeout=5000)
            user_el = loc
            break
        except Exception:
            continue
    if user_el is None:
        raise ValueError("未找到账号输入框，请手动登录")

    pass_el = None
    for sel in pass_selectors:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(timeout=5000)
            pass_el = loc
            break
        except Exception:
            continue
    if pass_el is None:
        raise ValueError("未找到密码输入框，请手动登录")

    await _slow_type(user_el, username)
    await _slow_type(pass_el, password)
    await page.locator("button[type='submit']").first.click()


async def browser_login_pixiv(
    *,
    account_id: str = "",
    username: str = "",
    password: str = "",
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
) -> dict:
    """持久化 Chrome 配置登录，通行密钥可复用。自动捕获 OAuth code。"""
    code_holder: dict[str, str | None] = {"code": None}
    code_verifier, code_challenge = oauth_pkce()
    login_url = f"{LOGIN_URL}?{urlencode({
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'client': 'pixiv-android',
    })}"

    def store_code(url: str) -> None:
        found = extract_code(url)
        if found:
            code_holder["code"] = found

    async def on_request(request: Request) -> None:
        store_code(request.url)

    async def on_response(response: Response) -> None:
        store_code(response.url)

    profile_dir = profile_dir_for_account(account_id)
    proxy = proxy_settings()
    ctx_kwargs: dict = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "args": ["--start-maximized"],
        "user_agent": USER_AGENT,
        "locale": "zh-CN",
    }
    if proxy:
        ctx_kwargs["proxy"] = proxy

    async with async_playwright() as p:
        context = None
        for channel in ("chrome", "msedge", None):
            try:
                kwargs = dict(ctx_kwargs)
                if channel:
                    kwargs["channel"] = channel
                context = await p.chromium.launch_persistent_context(**kwargs)
                break
            except Exception:
                context = None
        if context is None:
            raise RuntimeError("无法启动 Chrome/Edge，请确认浏览器已安装")

        page = context.pages[0] if context.pages else await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("framenavigated", lambda frame: store_code(frame.url))

        print(f"[pixiv] 使用持久浏览器配置（通行密钥保存在 {profile_dir}）")
        print("[pixiv] 若通行密钥不可用，请在此 Chrome 窗口登录 Google 账号后再试 Passkey")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=90000)

        if username and password:
            try:
                await _fill_login_form(page, username, password)
            except Exception as exc:
                print(f"[pixiv] 自动填表未完成，请手动登录: {exc}")
        else:
            print("[pixiv] 请在浏览器中使用通行密钥或手动完成 Pixiv 登录")

        deadline = time.time() + wait_seconds
        last_hint = 0.0
        while time.time() < deadline and not code_holder["code"]:
            store_code(page.url)
            try:
                html = await page.content()
                store_code(html)
            except Exception:
                pass
            if time.time() - last_hint > 20:
                left = int(deadline - time.time())
                cur = page.url[:80]
                print(f"[pixiv] 等待登录回调… 剩余 {left}s · 当前页 {cur}")
                last_hint = time.time()
            if POST_REDIRECT in page.url and not code_holder["code"]:
                await asyncio.sleep(2)
            await asyncio.sleep(0.4)

        await context.close()

    if not code_holder["code"]:
        proxy_hint = "请确认代理可访问 Pixiv。" if proxy else ""
        raise TimeoutError(
            f"在 {wait_seconds} 秒内未捕获 OAuth 回调。{proxy_hint} "
            "请确认已在弹出 Chrome 中完成通行密钥登录；若 Passkey 灰色，先在该窗口登录 Google 账号。"
        )

    return exchange_code(str(code_holder["code"]), code_verifier)


def browser_login_pixiv_sync(
    *,
    username: str = "",
    password: str = "",
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
    account_id: str = "",
) -> dict:
    return asyncio.run(
        browser_login_pixiv(
            username=username,
            password=password,
            wait_seconds=wait_seconds,
            account_id=account_id,
        )
    )