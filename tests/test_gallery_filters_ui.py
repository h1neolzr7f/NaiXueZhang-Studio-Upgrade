from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_app() -> str:
    # app.js 已按域拆分：详情/预览在 app-detail.js，线上换角在 app-online-remix.js，
    # index.html 按序加载三者，契约断言对合并视图生效
    return "".join(
        (ROOT / "web" / name).read_text(encoding="utf-8")
        for name in ("app.js", "app-detail.js", "app-online-remix.js")
    )


class GalleryFiltersUiTests(unittest.TestCase):
    def test_gallery_sources_are_visible_one_click_controls_outside_advanced_filters(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = read_app()
        advanced_start = html.index('<details id="advancedFilters"')
        switch_start = html.index('id="gallerySourceSwitch"')
        self.assertLess(switch_start, advanced_start)
        self.assertIn('role="group"', html[switch_start - 100:switch_start + 200])
        for gallery_id, label in (("site", "Pixiv NAI"), ("codex", "自选库"), ("qqgroup", "Q群"), ("aitag-online", "AITag 在线库")):
            with self.subTest(gallery_id=gallery_id):
                self.assertIn(f'data-gallery-source="{gallery_id}"', html)
                self.assertIn(f'>{label}</button>', html)
        self.assertIn("button.setAttribute('aria-pressed'", app)
        self.assertNotIn("window.location.assign('/aitag-library')", app)
        self.assertIn("new URL('/api/nai/aitag/search', API_BASE)", app)
        self.assertIn("adaptAitagWork", app)
        self.assertIn("adaptAitagDetail", app)
        self.assertIn("gallerySourceSel.dispatchEvent(new Event('change'))", app)
        self.assertIn("url.searchParams.set('gallery', currentGalleryId())", app)

    def test_aitag_uses_native_gallery_cards_and_remote_image_urls(self) -> None:
        app = read_app()
        core = (ROOT / "web" / "app-core.js").read_text(encoding="utf-8")
        hooks = (ROOT / "web" / "shared" / "gallery-detail-hooks.js").read_text(encoding="utf-8")
        self.assertIn("isAitagGallery()", app)
        self.assertIn("/api/nai/aitag/work/", app)
        self.assertIn("openOnlineRemixPanel", app)
        self.assertIn("imgOrPath.thumbnail_url", core)
        self.assertIn("work.thumbnail_url", core)
        self.assertIn('source === "aitag-online"', hooks)
        self.assertIn("if (online) return", hooks)

    def test_aitag_switch_updates_the_whole_gallery_shell(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = read_app()
        for element_id in (
            "galleryHeroEyebrow",
            "galleryHeroLead",
            "galleryNoteIndex",
            "galleryAboutSummary",
            "galleryResultsLabel",
            "galleryResultsHelp",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("AITag online · NAI works", app)
        self.assertIn("正在读取 AITag 在线库", app)
        self.assertIn("零生成草稿换角", app)
        self.assertIn("localBanner')?.classList.toggle('hidden', online)", app)
        self.assertIn("if (isAitagGallery()) return", app)
        self.assertIn("!isAitagGallery() && window.GalleryBootstrap", app)
        self.assertIn("单击在线作品查看详情与全部图片", app)
        self.assertIn("建立原图草稿 →", app)
        self.assertIn("角色换角 →", app)
        self.assertIn("generateOnlineCurrentDraft", app)
        self.assertIn("inspirationToQueue')?.classList.toggle('hidden', online)", app)

    def test_primary_search_stays_visible_while_secondary_filters_are_collapsed(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        match = re.search(
            r'<details[^>]+id="advancedFilters"[^>]*>(?P<body>.*?)</details>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Gallery should expose one collapsed advanced-filter surface")
        advanced = match.group("body")
        self.assertIn("高级筛选", advanced)
        for control_id in ("prompt", "sortMode", "timeRange", "blacklist"):
            with self.subTest(control_id=control_id):
                self.assertIn(f'id="{control_id}"', advanced)
        self.assertLess(html.index('id="q"'), match.start())
        self.assertLess(html.index('id="searchBtn"'), match.start())

    def test_long_gallery_description_is_collapsed_behind_about_disclosure(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        match = re.search(
            r'<details[^>]+id="galleryAbout"[^>]*>(?P<body>.*?)</details>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("关于图库", body)
        self.assertIn("从 Pixiv 搜索、画师与榜单发现候选图片", body)

    def test_qq_filter_renders_group_then_account_hierarchy(self) -> None:
        source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("全部群组和账号", source)
        self.assertIn("it.kind === 'group'", source)
        self.assertIn("it.kind === 'account'", source)
        self.assertIn("<optgroup", source)
        self.assertIn("账号 ·", source)

    def test_empty_state_keeps_message_and_exposes_one_click_recovery(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        core = (ROOT / "web" / "app-core.js").read_text(encoding="utf-8")
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="noResultText"', html)
        self.assertIn('id="clearFiltersBtn"', html)
        self.assertIn("const noResultTextEl", core)
        self.assertNotIn("noResultEl.textContent =", core)
        self.assertIn("clearFiltersBtn.addEventListener('click'", app)
        self.assertIn("qInput.value = ''", app)
        self.assertIn("promptInput.value = ''", app)
        self.assertIn("galleryGroupSel.value = ''", app)

    def test_detail_keeps_every_action_but_has_one_primary_action(self) -> None:
        app = read_app()
        self.assertIn('class="detail-primary-actions"', app)
        self.assertIn('class="detail-more-actions"', app)
        self.assertIn('class="detail-info-disclosure"', app)
        self.assertEqual(app.count('class="primary" id="detailToStudioBtn"'), 1)
        for control_id in (
            "detailToStudioBtn",
            "detailToRemixBtn",
            "detailQueueBtn",
            "detailCopyPromptBtn",
        ):
            with self.subTest(control_id=control_id):
                self.assertIn(f'id="{control_id}"', app)
        self.assertIn("/generated?g=", app)

    def test_gallery_shell_and_collapsed_swap_drawer_are_compact(self) -> None:
        css = (ROOT / "web" / "local.css").read_text(encoding="utf-8")
        self.assertIn("--gallery-logo-size: 52px", css)
        self.assertIn("--gallery-logo-size-mobile: 36px", css)
        self.assertIn(".detail-view .char-swap-batch-drawer:not(.open)", css)
        self.assertIn("width: min(188px, calc(100vw - 20px))", css)


if __name__ == "__main__":
    unittest.main()
