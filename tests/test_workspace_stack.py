from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
THEME_LINK = "/assets/studio-theme.css?v="


def test_workspace_shell_loads_dark_theme_last() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    assert html.count(THEME_LINK) == 1
    assert html.rfind(THEME_LINK) < html.lower().find("</head>")
    later = html.find('rel="stylesheet"', html.rfind(THEME_LINK) + len(THEME_LINK))
    assert later == -1 or later > html.lower().find("</head>")
    assert 'data-ui="nai-workspace"' in html
    assert 'id="siteNav"' in html
    assert "/assets/app/workspace.js" in html
    assert "/assets/shared/site-nav.css" in html
    assert "/assets/shared/site-nav.js" in html


def test_workspace_bundle_freezes_generation_comment() -> None:
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    bundle = (WEB / "app" / "workspace.js").read_text(encoding="utf-8")
    for needle in (
        "frozen_comment",
        "/api/nai/generate",
        "/api/studio/import",
        "/api/studio/source-image",
        "/api/companion/state",
        "/api/butler/chat",
        "/api/butler/confirm",
        "/api/generated/group/",
        "/api/generated/trash",
        "/api/studio/sanitize",
        "/api/plugin/char-swap/transform",
        "/api/crawler/start",
        "/api/pipeline/run",
        "/api/director/preview",
        "/api/nai-tags",
        "/api/plugin/char-swap/batch/run",
        "/api/pixiv/upload",
        "/api/pixiv/launch",
        "/api/product/health",
        "/api/compliance/blacklist",
        "force_free",
        "gallery_compare",
    ):
        assert needle in bundle, needle
    assert "未自动重试" in bundle
    assert "/assets/shared/api-client.js" in html


def test_workspace_typescript_does_not_call_fetch() -> None:
    src = ROOT / "frontend" / "src"
    offenders: list[str] = []
    for path in src.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "fetch(" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_workspace_is_primary_nav() -> None:
    nav = (WEB / "shared" / "site-nav.js").read_text(encoding="utf-8")
    primary = nav.split("const NAV_SECONDARY", 1)[0]
    assert '{ href: "/", id: "gallery", label: "图库" }' in nav
    assert '{ href: "/studio", id: "studio", label: "工作台" }' in nav
    assert '{ href: "/generated", id: "generated", label: "生成库" }' in nav
    assert '{ href: "/queue", id: "queue", label: "待生成" }' in primary
    assert '{ href: "/remix", id: "remix", label: "换角" }' in nav
    assert "remixHref" in nav
    assert "#onlineRemixPanel" in nav
    assert '{ href: "/progress", id: "progress", label: "爬虫" }' in nav
    assert '{ href: "/pixiv", id: "pixiv", label: "发布" }' in nav
    assert '{ href: "/nai-tags", id: "nai-tags", label: "分类" }' in nav
    assert 'href: "/app/' not in primary
    assert 'p === "/" || p.startsWith("/i/") || p === "/app"' in nav
    assert 'id: "classic"' not in nav
    assert "addEventListener(\"popstate\"" in nav
    routes = (ROOT / "frontend" / "src" / "routes.ts").read_text(encoding="utf-8")
    assert 'return "/studio"' in routes
    assert 'return "/remix"' in routes
    assert 'return "/generated"' in routes
    assert 'query.set("from", workId)' in routes
    assert 'path: "/app/studio"' not in routes
    assert 'return "/app/studio"' not in routes


def test_workspace_does_not_render_a_second_nav() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "工作区导航" not in app
    assert 'className="ws-nav"' not in app
    assert "返回图库" in app
    assert 'href="/"' in app
    assert "location.replace" in app
    nav = (WEB / "shared" / "site-nav.js").read_text(encoding="utf-8")
    assert nav.count('label: "客服小祥"') == 1
    assert nav.count('label: "助手凑企鹅"') == 1
    assert nav.count('label: "图库"') == 1
    bundle = (WEB / "app" / "workspace.js").read_text(encoding="utf-8")
    assert "工作区导航" not in bundle
    assert "返回图库" in bundle
    assert "正在打开图库" in bundle
    assert "点一张图" not in bundle
    assert "按 prompt 过滤" not in bundle


def test_bare_workspace_root_redirects_to_gallery() -> None:
    source = (ROOT / "routes" / "gallery.py").read_text(encoding="utf-8")
    assert "RedirectResponse" in source
    assert "_APP_CLASSIC_PAGES" in source
    assert '"studio": "/studio"' in source
    assert '"butler": "/butler"' in source
    assert '"tags": "/nai-tags"' in source
    assert '@router.get("/app")' in source


def test_gallery_serves_workspace_shell() -> None:
    source = (ROOT / "routes" / "gallery.py").read_text(encoding="utf-8")
    assert "workspace.html" in source
    assert '@router.get("/app")' in source
