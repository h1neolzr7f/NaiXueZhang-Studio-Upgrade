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
    assert '{ href: "/app", id: "gallery", label: "图库" }' in nav
    assert '{ href: "/app/studio", id: "studio", label: "工作台" }' in nav
    assert '{ href: "/app/generated", id: "generated", label: "生成库" }' in nav
    assert '{ href: "/app/butler", id: "butler", label: "小镜" }' in nav
    assert '{ href: "/app/remix", id: "remix", label: "换角" }' in nav
    assert '{ href: "/app/progress", id: "progress", label: "爬虫" }' in nav
    assert '{ href: "/app/pixiv", id: "pixiv", label: "发布" }' in nav
    assert '{ href: "/app/tags", id: "nai-tags", label: "分类" }' in nav
    assert 'p === "/app" || p.startsWith("/app")' in nav
    assert 'id: "classic"' in nav


def test_gallery_serves_workspace_shell() -> None:
    source = (ROOT / "routes" / "gallery.py").read_text(encoding="utf-8")
    assert "workspace.html" in source
    assert '@router.get("/app")' in source
