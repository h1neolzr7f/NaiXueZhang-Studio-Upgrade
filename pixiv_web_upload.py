"""通过 Pixiv 网页投稿（Playwright + 持久化浏览器会话）。"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page, Response

from paths import data_dir
from pixiv_browser_login import profile_dir_for_account, proxy_settings

CREATE_URL = "https://www.pixiv.net/illustration/create"
PIXIV_MAX_TAGS = 10
_ARTWORK_RE = re.compile(r"/artworks/(\d+)")
_ILLUST_ID_RE = re.compile(r'"illustId"\s*:\s*"?(\d+)"?')
_PROFILE_LOCK = threading.Lock()
_PROGRESS_HOOK: Callable[[str], None] | None = None

# 内置兜底选择器包。站点改版时的首选动作是更新
# data/pixiv_upload_selectors.json（外置包），而不是改这里；
# 外置包缺失/损坏时自动回落到本表，保证投稿功能永远可用。
_BUILTIN_SELECTOR_PACK: dict[str, tuple[str, ...]] = {
    "upload": (
        "input[name='files[]']",
        "input[type='file'][accept*='image']",
        "input[type='file']",
    ),
    "title": (
        "input[name='title']",
        "input[placeholder*='タイトル']",
        "input[placeholder*='title' i]",
    ),
    "tags": (
        "input[placeholder='标签']",
        "input[placeholder*='タグ']",
        "input[placeholder*='tag' i]",
        "input[name*='tag' i]",
    ),
    "caption": (
        "textarea[name='comment']",
        "textarea[placeholder*='キャプション']",
        "textarea[placeholder*='caption' i]",
    ),
    "submit": (
        "button:has-text('投稿する')",
        "button:has-text('投稿')",
        "button[type='submit']",
    ),
    "overlay_dismiss": (
        "button:has-text('同意')",
        "button:has-text('接受')",
        "button:has-text('知道了')",
        "button:has-text('关闭')",
    ),
    "confirm_dialog": (
        "[role='dialog'] button:has-text('投稿')",
        "[role='dialog'] button:has-text('确定')",
        "[role='dialog'] button:has-text('确认')",
        "button:has-text('确定投稿')",
    ),
}

# 投稿必需控件；其余组（caption/overlay/confirm）是辅助交互，不纳入 probe 缺失判定
_REQUIRED_SELECTOR_GROUPS = ("upload", "title", "tags", "submit")

_SELECTOR_PACK_PATH = "pixiv_upload_selectors.json"


def _selector_pack_file() -> Path:
    return data_dir() / _SELECTOR_PACK_PATH


def _validate_selector_pack(raw: Any) -> dict[str, tuple[str, ...]] | None:
    """校验外置选择器包；任何结构问题都返回 None（调用方回落内置包）。"""
    if not isinstance(raw, dict):
        return None
    packs = raw.get("packs")
    if not isinstance(packs, dict):
        return None
    pack = packs.get("default")
    if not isinstance(pack, dict):
        return None
    out: dict[str, tuple[str, ...]] = {}
    for group, selectors in _BUILTIN_SELECTOR_PACK.items():
        value = pack.get(group)
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(s, str) and s.strip() for s in value)
        ):
            # 必需组缺失/非法则整包作废；辅助组缺失用内置补齐
            if group in _REQUIRED_SELECTOR_GROUPS:
                return None
            out[group] = selectors
            continue
        out[group] = tuple(str(s).strip() for s in value)
    return out


def load_selector_pack() -> tuple[dict[str, tuple[str, ...]], str]:
    """加载生效的选择器包，返回 (pack, source)。source ∈ external/builtin。"""
    path = _selector_pack_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return dict(_BUILTIN_SELECTOR_PACK), "builtin"
    pack = _validate_selector_pack(raw)
    if pack is None:
        return dict(_BUILTIN_SELECTOR_PACK), "builtin"
    return pack, "external"


def _selector_pack_mtime() -> float | None:
    try:
        return _selector_pack_file().stat().st_mtime
    except OSError:
        return None


PIXIV_UPLOAD_SELECTORS, SELECTOR_PACK_SOURCE = load_selector_pack()
_SELECTOR_PACK_MTIME: float | None = _selector_pack_mtime()


def reload_selector_pack() -> str:
    """重新加载外置选择器包（更新 JSON 后无需重启服务）。返回生效来源。"""
    global PIXIV_UPLOAD_SELECTORS, SELECTOR_PACK_SOURCE, _SELECTOR_PACK_MTIME
    PIXIV_UPLOAD_SELECTORS, SELECTOR_PACK_SOURCE = load_selector_pack()
    _SELECTOR_PACK_MTIME = _selector_pack_mtime()
    return SELECTOR_PACK_SOURCE


def maybe_reload_selector_pack() -> str:
    """外置选择器包 mtime 变化时才重新加载（廉价 stat 检查）。返回生效来源。"""
    if _selector_pack_mtime() != _SELECTOR_PACK_MTIME:
        return reload_selector_pack()
    return SELECTOR_PACK_SOURCE


class PixivWebUploadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "pixiv_web_upload_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": dict(self.details),
        }


def set_upload_progress_hook(fn: Callable[[str], None] | None) -> None:
    global _PROGRESS_HOOK
    _PROGRESS_HOOK = fn


def _progress(msg: str) -> None:
    if _PROGRESS_HOOK:
        try:
            _PROGRESS_HOOK(msg)
        except Exception:
            pass


async def probe_pixiv_upload_selectors(
    page: Page,
    selectors: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Inspect the create form without choosing files, filling fields, or submitting."""
    pack = selectors or PIXIV_UPLOAD_SELECTORS
    checks: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for control in _REQUIRED_SELECTOR_GROUPS:
        selectors_for_control = pack[control]
        check: dict[str, Any] = {
            "ok": False,
            "matched_selector": None,
            "count": 0,
            "visible": False,
            "enabled": False,
            "selectors": list(selectors_for_control),
            "selector_errors": [],
        }
        for selector in selectors_for_control:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception as exc:
                check["selector_errors"].append(
                    {"selector": selector, "message": str(exc)}
                )
                continue
            if count < 1:
                continue
            first = locator.first
            check["ok"] = True
            check["matched_selector"] = selector
            check["count"] = count
            try:
                check["visible"] = bool(await first.is_visible())
            except Exception:
                pass
            try:
                check["enabled"] = bool(await first.is_enabled())
            except Exception:
                pass
            break
        checks[control] = check
        if not check["ok"]:
            missing.append(control)

    error = None
    if missing:
        error = {
            "code": "pixiv_selector_probe_failed",
            "message": "Pixiv create form is missing required controls: " + ", ".join(missing),
            "missing": list(missing),
        }
    return {
        "ok": not missing,
        "phase": "selectors",
        "url": str(page.url or ""),
        "checks": checks,
        "missing": missing,
        "error": error,
        "selector_pack": SELECTOR_PACK_SOURCE,
    }


def _restrict_value(restrict: int) -> str:
    mapping = {0: "public", 1: "mypixiv", 2: "private"}
    return mapping.get(int(restrict), "public")


async def _dismiss_overlays(page: Page) -> None:
    for sel in PIXIV_UPLOAD_SELECTORS["overlay_dismiss"]:
        try:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=1500)
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def _locator_first(
    page: Page,
    selectors: list[str],
    *,
    control: str = "control",
    timeout_ms: int = 8000,
) -> Locator:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            await loc.wait_for(state="attached", timeout=timeout_ms)
            return loc
        except Exception:
            continue
    raise PixivWebUploadError(
        f"未找到 Pixiv 页面控件：{control}",
        code="pixiv_selector_missing",
        details={
            "control": control,
            "selectors": list(selectors),
            "required_state": "attached",
        },
    )


async def _fill_input(loc: Locator, text: str) -> None:
    await loc.scroll_into_view_if_needed()
    await loc.click()
    await loc.fill(str(text or ""))


async def _pick_radio(page: Page, name: str, value: str) -> None:
    radio = page.locator(f"input[name='{name}'][value='{value}']").first
    if not await radio.count():
        return
    await radio.scroll_into_view_if_needed()
    label = page.locator(f"label:has(input[name='{name}'][value='{value}'])").first
    if await label.count():
        await label.click()
    else:
        await radio.click(force=True)
    await page.wait_for_timeout(200)


async def _enabled_submit_button(page: Page) -> Locator:
    """页头/页尾各有一个「投稿」；填完表后优先点页尾那个可点的。"""
    for selector in PIXIV_UPLOAD_SELECTORS["submit"]:
        btns = page.locator(selector)
        count = await btns.count()
        enabled: list[Locator] = []
        for i in range(count):
            btn = btns.nth(i)
            try:
                if not await btn.is_visible():
                    continue
                if await btn.is_enabled():
                    enabled.append(btn)
            except Exception:
                continue
        if enabled:
            return enabled[-1]
    raise PixivWebUploadError(
        "未找到可点击的「投稿」按钮（请确认标题/标签已填写）",
        code="pixiv_submit_unavailable",
        details={
            "control": "submit",
            "selectors": list(PIXIV_UPLOAD_SELECTORS["submit"]),
            "required_state": "visible_enabled",
        },
    )


async def _fill_tags(page: Page, tags: list[str]) -> None:
    tag_input = await _locator_first(
        page,
        list(PIXIV_UPLOAD_SELECTORS["tags"]),
        control="tags",
    )
    limited = [str(t).strip() for t in tags if str(t).strip()][:PIXIV_MAX_TAGS]
    for raw in limited:
        await _fill_input(tag_input, raw)
        await tag_input.press("Enter")
        await page.wait_for_timeout(350)


async def _upload_files(page: Page, paths: list[Path]) -> None:
    uploaded = {"count": 0}

    async def on_response(resp: Response) -> None:
        url = resp.url.lower()
        if "/ajax/" not in url:
            return
        if "upload" not in url and "illust" not in url:
            return
        if resp.status >= 400:
            return
        uploaded["count"] += 1

    page.on("response", on_response)
    file_input = await _locator_first(
        page,
        list(PIXIV_UPLOAD_SELECTORS["upload"]),
        control="upload",
    )
    await file_input.set_input_files([str(p) for p in paths])

    need = len(paths)
    # 多页系列上传：每张预留更长时间，总上限 2 小时
    deadline = time.time() + max(300, min(7200, need * 35))
    while time.time() < deadline:
        if uploaded["count"] >= need:
            break
        try:
            previews = await page.locator(
                "img[src*='blob:'], img[src*='pximg.net'], [class*='thumbnail'] img"
            ).count()
            if previews >= need:
                break
            _progress(f"上传图片 {min(previews, need)}/{need} 张…")
        except Exception:
            pass
        await page.wait_for_timeout(1000)

    await page.wait_for_timeout(1500)
    if uploaded["count"] < need:
        _progress(f"已选择 {need} 张图片，继续填写标题/简介/标签…")


async def _fill_form(
    page: Page,
    *,
    title: str,
    caption: str,
    tags: list[str],
    restrict: int,
    x_restrict: str,
    ai_type: int | None,
) -> None:
    _progress("填写标题与简介…")
    title_input = await _locator_first(
        page,
        list(PIXIV_UPLOAD_SELECTORS["title"]),
        control="title",
    )
    await _fill_input(title_input, str(title or "无题")[:32])

    caption_input = await _locator_first(
        page,
        list(PIXIV_UPLOAD_SELECTORS["caption"]),
        control="caption",
    )
    await _fill_input(caption_input, str(caption or ""))

    _progress("填写标签…")
    await _fill_tags(page, tags)

    _progress("勾选 R-18 / AI 生成…")
    x_val = str(x_restrict or "general").lower()
    if x_val not in ("general", "r18", "r18g"):
        x_val = "r18" if x_val in ("nsfw", "r-18") else "general"
    await _pick_radio(page, "x_restrict", x_val)

    if ai_type is not None and int(ai_type) == 1:
        await _pick_radio(page, "ai_type", "aiGenerated")
    elif ai_type is not None and int(ai_type) == 0:
        await _pick_radio(page, "ai_type", "notAiGenerated")

    restrict_val = _restrict_value(restrict)
    await _pick_radio(page, "restrict", restrict_val)
    await page.wait_for_timeout(500)


def _extract_illust_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("illustId", "illust_id", "id"):
            val = data.get(key)
            if val and str(val).isdigit():
                return str(val)
        body = data.get("body")
        if body is not None:
            found = _extract_illust_id(body)
            if found:
                return found
        for key in ("result", "data", "illust"):
            if key in data:
                found = _extract_illust_id(data[key])
                if found:
                    return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_illust_id(item)
            if found:
                return found
    else:
        m = _ILLUST_ID_RE.search(str(data))
        if m:
            return m.group(1)
    return None


async def _confirm_submit_dialogs(page: Page) -> None:
    for sel in PIXIV_UPLOAD_SELECTORS["confirm_dialog"]:
        try:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible() and await btn.is_enabled():
                await btn.click(timeout=3000)
                await page.wait_for_timeout(800)
                return
        except Exception:
            pass


async def _click_submit(page: Page) -> str | None:
    captured: dict[str, Any] = {"illust_id": None}

    async def on_response(resp: Response) -> None:
        url = resp.url
        if "/ajax/" not in url:
            return
        try:
            ctype = resp.headers.get("content-type") or ""
            if "application/json" in ctype:
                data = await resp.json()
                found = _extract_illust_id(data)
                if found:
                    captured["illust_id"] = found
                    return
            text = await resp.text()
            found = _extract_illust_id(text)
            if found:
                captured["illust_id"] = found
        except Exception:
            pass

    page.on("response", on_response)
    _progress("点击投稿…")
    submit = await _enabled_submit_button(page)
    await submit.scroll_into_view_if_needed()
    await submit.click()
    await page.wait_for_timeout(800)
    await _confirm_submit_dialogs(page)
    deadline = time.time() + 600
    while time.time() < deadline:
        if captured["illust_id"]:
            return str(captured["illust_id"])
        cur = page.url
        m = _ARTWORK_RE.search(cur)
        if m:
            return m.group(1)
        try:
            link = page.locator("a[href*='/artworks/']").first
            if await link.count():
                href = await link.get_attribute("href") or ""
                m2 = _ARTWORK_RE.search(href)
                if m2:
                    return m2.group(1)
        except Exception:
            pass
        await page.wait_for_timeout(500)
    return captured["illust_id"]


async def _read_browser_pixiv_uid(page: Page) -> int | None:
    """从浏览器会话读取当前 Pixiv 登录 uid（与 Chrome profile 一致）。"""
    try:
        # Intentional native fetch: this JavaScript runs inside pixiv.net, where the
        # gallery's window.ApiClient is not loaded. It only reads the active Pixiv UID.
        payload = await page.evaluate(
            """async () => {
                const urls = [
                    '/ajax/user/extra',
                    'https://www.pixiv.net/ajax/user/extra',
                ];
                for (const url of urls) {
                    try {
                        const resp = await fetch(url, { credentials: 'include' });
                        if (!resp.ok) continue;
                        const data = await resp.json();
                        const body = data && data.body ? data.body : data;
                        const raw = body && (body.userId ?? body.user_id ?? body.id);
                        const uid = parseInt(String(raw || ''), 10);
                        if (Number.isFinite(uid) && uid > 0) return uid;
                    } catch (e) {}
                }
                return null;
            }"""
        )
        if isinstance(payload, int) and payload > 0:
            return payload
    except Exception:
        pass

    patterns = [
        r'"userId"\s*:\s*"?(\d+)"?',
        r'"user_id"\s*:\s*"?(\d+)"?',
        r'data-user-id="(\d+)"',
    ]
    try:
        html = await page.content()
    except Exception:
        html = ""
    for pat in patterns:
        m = re.search(pat, html)
        if not m:
            continue
        try:
            uid = int(m.group(1))
        except ValueError:
            continue
        if uid > 0:
            return uid
    return None


async def _ensure_logged_in(
    page: Page,
    *,
    expected_uid: int | None = None,
    expected_label: str = "",
) -> None:
    await page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(2000)
    await _dismiss_overlays(page)
    if "accounts.pixiv.net" in page.url or "/login" in page.url.lower():
        raise PixivWebUploadError(
            "浏览器未登录 Pixiv。请在起号页用「浏览器通行密钥」或邮箱密码重新登录一次。"
        )
    if "illustration/create" not in page.url:
        raise PixivWebUploadError(f"未能打开发帖页：{page.url[:120]}")

    if expected_uid is None:
        return
    browser_uid = await _read_browser_pixiv_uid(page)
    if browser_uid is None:
        raise PixivWebUploadError(
            "无法确认浏览器当前登录的 Pixiv 账号。"
            "请用起号页「浏览器通行密钥」为当前选中账号重新登录后再上传。"
        )
    if browser_uid != int(expected_uid):
        who = expected_label or f"uid {expected_uid}"
        raise PixivWebUploadError(
            f"浏览器当前登录的是 uid {browser_uid}，与选中账号「{who}」（uid {expected_uid}）不一致。"
            "网页投稿使用 Chrome 配置目录里的登录态，请切换到正确账号后重新通行密钥登录。"
        )


async def _launch_context(p, *, headless: bool, account_id: str = ""):
    profile_dir = profile_dir_for_account(account_id)
    proxy = proxy_settings()
    ctx_kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "locale": "zh-CN",
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if proxy:
        ctx_kwargs["proxy"] = proxy

    last_err: Exception | None = None
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(ctx_kwargs)
            if channel:
                kwargs["channel"] = channel
            return await p.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            last_err = exc
    hint = f" ({last_err})" if last_err else ""
    raise PixivWebUploadError(
        "无法启动 Chrome/Edge 进行网页投稿，请确认浏览器已安装。" + hint
    )


def _selector_probe_error(probe: dict[str, Any], *, phase: str) -> "PixivWebUploadError":
    error = probe.get("error") or {}
    missing = ", ".join(str(x) for x in (error.get("missing") or [])) or "unknown"
    return PixivWebUploadError(
        f"Pixiv 投稿页控件自检失败（{phase}，缺少：{missing}）。"
        "站点结构可能已改版：标题/标签/文案草稿已保留，可稍后在发布页重试；"
        "或更新 data/pixiv_upload_selectors.json 选择器包后重试。",
        code=str(error.get("code") or "pixiv_selector_probe_failed"),
        details={"probe": probe, "phase": phase},
    )


def _selector_probe_failure(
    exc: Exception,
    *,
    phase: str,
    url: str = "",
) -> dict[str, Any]:
    if isinstance(exc, PixivWebUploadError):
        error = exc.to_dict()
    else:
        error = {
            "code": "pixiv_selector_probe_error",
            "message": str(exc).strip() or exc.__class__.__name__,
            "details": {"exception_type": exc.__class__.__name__},
        }
    return {
        "ok": False,
        "phase": phase,
        "url": url,
        "checks": {},
        "missing": [],
        "error": error,
        "selector_pack": SELECTOR_PACK_SOURCE,
    }


async def probe_pixiv_upload_page(
    *,
    account_id: str = "",
    headless: bool = True,
) -> dict[str, Any]:
    """Open the Pixiv create page and inspect its DOM without uploading or submitting."""
    if not _PROFILE_LOCK.acquire(blocking=False):
        return _selector_probe_failure(
            PixivWebUploadError(
                "浏览器投稿配置正在使用中，请稍后重试选择器自检。",
                code="pixiv_profile_busy",
            ),
            phase="browser",
        )

    from playwright.async_api import async_playwright

    page: Page | None = None
    try:
        async with async_playwright() as p:
            context = await _launch_context(
                p,
                headless=bool(headless),
                account_id=str(account_id or "").strip(),
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await _ensure_logged_in(page)
                return await probe_pixiv_upload_selectors(page)
            finally:
                await context.close()
    except Exception as exc:
        return _selector_probe_failure(
            exc,
            phase="navigation",
            url=str(page.url if page is not None else ""),
        )
    finally:
        _PROFILE_LOCK.release()


def probe_pixiv_upload_page_sync(
    *,
    account_id: str = "",
    headless: bool = True,
) -> dict[str, Any]:
    return asyncio.run(
        probe_pixiv_upload_page(account_id=account_id, headless=headless)
    )


async def upload_illust_via_web(
    image_paths: list[Path],
    *,
    title: str,
    caption: str,
    tags: list[str],
    restrict: int = 0,
    x_restrict: str = "general",
    ai_type: int | None = 1,
    headless: bool = False,
    account_id: str = "",
    expected_uid: int | None = None,
    expected_label: str = "",
) -> dict[str, Any]:
    paths = [Path(p).resolve() for p in image_paths if Path(p).exists()]
    if not paths:
        raise PixivWebUploadError("未找到可上传的图片文件")
    if not tags:
        raise PixivWebUploadError("Pixiv 投稿要求至少填写 1 个标签")

    if not _PROFILE_LOCK.acquire(blocking=False):
        raise PixivWebUploadError(
            "浏览器投稿占用中（可能正在登录或另一次上传）。请稍后再试。"
        )

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            context = await _launch_context(p, headless=headless, account_id=account_id)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                _progress("打开 Pixiv 投稿页…")
                await _ensure_logged_in(
                    page,
                    expected_uid=expected_uid,
                    expected_label=expected_label,
                )

                # 选择器包热重载：用户更新了 data/pixiv_upload_selectors.json
                # 后无需重启服务即可生效（mtime 未变时只是一次廉价 stat）。
                maybe_reload_selector_pack()

                # 预检：先验证投稿页控件存在再上传图片。站点改版时秒级失败，
                # 不再浪费几十分钟传图后才发现表单对不上。
                _progress("投稿页控件预检…")
                preflight = await probe_pixiv_upload_selectors(page)
                if not preflight["ok"]:
                    raise _selector_probe_error(preflight, phase="preflight")

                _progress(f"上传图片 {len(paths)} 张…")
                await _upload_files(page, paths)

                # 传图会触发页面重渲染，控件可能变化，提交前再探一次
                selector_probe = await probe_pixiv_upload_selectors(page)
                if not selector_probe["ok"]:
                    raise _selector_probe_error(selector_probe, phase="pre_submit")

                await _fill_form(
                    page,
                    title=title,
                    caption=caption,
                    tags=tags,
                    restrict=restrict,
                    x_restrict=x_restrict,
                    ai_type=ai_type,
                )

                illust_id = await _click_submit(page)
                if not illust_id:
                    debug_shot = Path(__file__).resolve().parent / "data" / "pixiv_upload_last.png"
                    try:
                        await page.screenshot(path=str(debug_shot), full_page=True)
                    except Exception:
                        pass
                    raise PixivWebUploadError(
                        "网页投稿已点击，但未解析到作品 ID。"
                        "请到 Pixiv 作品列表确认；调试截图已保存到 data/pixiv_upload_last.png"
                    )
                return {
                    "illust_id": illust_id,
                    "pixiv_url": f"https://www.pixiv.net/artworks/{illust_id}",
                    "upload_method": "web",
                    "page_count": len(paths),
                }
            finally:
                await context.close()
    finally:
        _PROFILE_LOCK.release()


def upload_illust_via_web_sync(
    image_paths: list[Path],
    **kwargs: Any,
) -> dict[str, Any]:
    return asyncio.run(upload_illust_via_web(image_paths, **kwargs))
