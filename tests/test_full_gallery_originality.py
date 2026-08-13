from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_full_gallery_uses_original_atlas_shell_without_dropping_workflows() -> None:
    html = read("web/index.html")
    nav = read("web/shared/site-nav.js")

    assert 'data-ui="nai-atlas-full"' in html
    assert re.search(r'href="/assets/core-theme\.css(\?v=[0-9a-f]+)?"', html)
    assert 'href="/assets/gallery-atlas.css' in html
    assert '<svg' not in html
    # Global nav is JS-mounted into #siteNav (not hard-coded in index.html).
    assert 'id="siteNav"' in html
    assert "site-nav.js" in html or "/assets/shared/site-nav.js" in html

    for href, label in (
        ("/app", "图库"),
        ("/app/tags", "分类"),
        ("/app/butler", "小镜"),
        ("/app/studio", "工作台"),
        ("/app/generated", "生成库"),
        ("/app/pixiv", "发布"),
        ("/settings", "设置"),
        ("/favorites", "收藏"),
        ("/queue", "待生成"),
        ("/director", "导演台"),
        ("/references", "参考库"),
        ("/pipeline", "后处理"),
        ("/", "经典图库"),
    ):
        assert f'href: "{href}"' in nav
        assert f'label: "{label}"' in nav

    for control_id in (
        "q",
        "searchBtn",
        "gallerySourceSwitch",
        "advancedFilters",
        "prompt",
        "galleryGroup",
        "sortMode",
        "timeRange",
        "blacklist",
        "galleryAbout",
        "gallery",
        "pagination",
        "fcChip",
        "fcPanel",
        "detailView",
        "detailMeta",
        "detailImages",
        "inspirationSidebar",
        "inspirationToStudio",
        "inspirationToRemix",
        "inspirationToQueue",
    ):
        assert f'id="{control_id}"' in html

    # 缓存版本戳为内容哈希（scripts/asset_versions.py 维护），契约只要求入口脚本存在
    assert re.search(r'src="/assets/app-core\.js\?v=[0-9a-f]+"', html)
    assert re.search(r'src="/assets/app\.js\?v=[0-9a-f]+"', html)


def test_gallery_specific_theme_does_not_restyle_preserved_workspaces() -> None:
    for page in (
        "butler.html",
        "settings.html",
        "studio.html",
        "director.html",
        "generated.html",
        "pixiv.html",
    ):
        assert "gallery-atlas.css" not in read(f"web/{page}")


def test_original_atlas_and_progress_share_the_light_blue_direction() -> None:
    core = read("web/core-theme.css")
    progress = read("web/progress.html")
    assert "color-scheme: light" in core
    assert "--paper: #eaf4fb" in core
    assert "color-scheme: light" in progress
    assert "--bg: #eaf4fb" in progress
    assert "--card: #f8fcff" in progress


def test_atlas_theme_covers_dynamic_full_gallery_components() -> None:
    css = read("web/gallery-atlas.css")
    for selector in (
        ".gallery-grid .card",
        ".gallery-grid .card-link",
        ".gallery-grid .meta",
        ".detail-view",
        ".detail-send-row",
        ".inspiration-sidebar",
        ".fc-panel",
        ".hover-preview",
    ):
        assert selector in css
