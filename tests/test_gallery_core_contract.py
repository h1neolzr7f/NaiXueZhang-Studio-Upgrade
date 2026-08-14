from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.asgi_client import TestClient

import server
import user_prefs
from routes import gallery as gallery_routes

ROOT = Path(__file__).resolve().parents[1]


class GalleryCoreContractTests(unittest.TestCase):
    """User-facing gallery contracts that must survive future upgrades."""

    def test_lite_image_builder_prefers_local_path_and_rejects_unknown_objects(self) -> None:
        core_path = ROOT / "web" / "app-core.js"
        script = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function buildImageUrl(');
const end = source.indexOf('\nfunction buildThumbUrlFromWork', start);
if (start < 0 || end < 0) throw new Error('buildImageUrl source not found');
const functionSource = source.slice(start, end);
const CONFIG = { asset_base_url: '/data/images/' };
const siteWindow = { location: { href: 'http://127.0.0.1:8787/' } };
const qqWindow = {
  location: {
    href: 'http://127.0.0.1:8787/i/1060330205301688258?gallery=qqgroup'
  }
};
const factory = new Function('CONFIG', 'window', `${functionSource}; return buildImageUrl;`);
const buildImageUrl = factory(CONFIG, siteWindow);
const buildQqImageUrl = factory(CONFIG, qqWindow);
process.stdout.write(JSON.stringify({
  localPath: buildImageUrl({
    file_name: '1001_p0',
    page_index: 0,
    local_path: 'images/NAI/77/1001_p0.webp'
  }),
  localPngPath: buildImageUrl({
    local_path: 'images/NAI/77/1001_p0_abc.png'
  }),
  structured: buildImageUrl({ image_type: 'NAI', author_id: 77, file_name: '1001_p0' }),
  structuredWebp: buildImageUrl({ image_type: 'NAI', author_id: 77, file_name: '1001_p0.webp' }),
  structuredPng: buildImageUrl({ image_type: 'NAI', author_id: 77, file_name: '1001_p0.png' }),
  unknown: buildImageUrl({ file_name: '1001_p0', page_index: 0 }),
  qqDetail: buildQqImageUrl({
    file_name: '1060330205301688258_p0.png',
    local_path: 'account/1060330205301688258_p0.png'
  })
}));
"""
        try:
            result = subprocess.run(
                ["node", "-e", script, str(core_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except FileNotFoundError:
            self.skipTest("node is not available for JS behavior check")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        urls = json.loads(result.stdout)
        self.assertEqual(urls["localPath"], "/data/images/NAI/77/1001_p0.webp")
        self.assertEqual(urls["localPngPath"], "/data/images/NAI/77/1001_p0_abc.png")
        # Extensionless file_name stays bare: serve_image probes known image
        # extensions server-side instead of the frontend inventing `.webp`.
        self.assertEqual(urls["structured"], "/data/images/NAI/77/1001_p0")
        self.assertEqual(urls["structuredWebp"], "/data/images/NAI/77/1001_p0.webp")
        # Explicit .png must stay .png — mixed PNG/WebP storage is valid until migrated.
        self.assertEqual(urls["structuredPng"], "/data/images/NAI/77/1001_p0.png")
        self.assertEqual(urls["unknown"], "")
        self.assertEqual(
            urls["qqDetail"],
            "/data/gallery/qqgroup/account/1060330205301688258_p0.png",
        )

    def test_default_click_behavior_is_gallery_detail_not_studio(self) -> None:
        core = (ROOT / "web" / "app-core.js").read_text(encoding="utf-8")
        match = re.search(r"function\s+handleGalleryCardActivate\s*\([^)]*\)\s*\{(?P<body>.*?)\n\}", core, re.S)
        self.assertIsNotNone(match, "handleGalleryCardActivate must exist")
        body = match.group("body")
        self.assertIn("openDetail", body, "single-clicking a gallery card must open the detail/all-images view")
        self.assertIn("if (userPrefs.quick_send_studio && window.WorkBridge)", body)
        self.assertLess(body.find("if (userPrefs.quick_send_studio"), body.find("openDetail"))
        self.assertIn("return;", body[body.find("if (userPrefs.quick_send_studio"):body.find("openDetail")])
        self.assertIn(
            "openDetail(id);",
            body,
            "when the advanced quick-studio preference is off, single-click must open detail/all-images view",
        )

    def test_default_preferences_keep_gallery_as_primary_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_prefs, "PREFS_PATH", Path(tmp) / "user_prefs.json"):
                prefs = user_prefs.load_prefs()
        self.assertTrue(prefs["nai_only_gallery"])
        self.assertFalse(prefs["quick_send_studio"])

    def test_gallery_copy_and_page_count_affordance_exist_in_detail(self) -> None:
        # app.js 已按域拆分（app-detail.js / app-online-remix.js），合并断言
        app = "".join(
            (ROOT / "web" / name).read_text(encoding="utf-8")
            for name in ("app.js", "app-detail.js", "app-online-remix.js")
        )
        self.assertIn("detail-image-summary", app)
        self.assertIn("detail-page-index", app)
        self.assertIn("copy_all_image_links", app)
        self.assertRegex(app, r"\(data\.images \|\| \[\]\)\.slice\(\)\.sort")

    def test_detail_local_cache_count_uses_local_path_not_file_name(self) -> None:
        app = "".join(
            (ROOT / "web" / name).read_text(encoding="utf-8")
            for name in ("app.js", "app-detail.js", "app-online-remix.js")
        )
        match = re.search(
            r"const\s+localCount\s*=\s*sortedDetailImages\.filter\((?P<body>.*?)\)\.length",
            app,
            re.S,
        )
        self.assertIsNotNone(match, "detail local cache count must remain explicit")
        body = match.group("body")
        self.assertIn("local_path", body)
        self.assertNotIn(
            "file_name",
            body,
            "file_name exists for remote pages and is not proof of local cache",
        )

    def test_index_referenced_assets_exist(self) -> None:
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        refs = re.findall(r'<script[^>]+src="([^"]+)"', index) + re.findall(
            r'<link[^>]+href="([^"]+)"',
            index,
        )
        missing: list[str] = []
        for ref in refs:
            if ref.startswith(("http://", "https://")):
                continue
            asset_path = ref.split("?", 1)[0]
            if asset_path.startswith("/assets/"):
                candidate = ROOT / "web" / asset_path.removeprefix("/assets/")
            else:
                candidate = ROOT / "web" / asset_path.lstrip("/")
            if not candidate.exists():
                missing.append(ref)
        self.assertEqual(missing, [], "index.html must not reference missing JS/CSS assets")

    def test_shared_site_nav_is_valid_javascript_and_gallery_first(self) -> None:
        nav_path = ROOT / "web" / "shared" / "site-nav.js"
        nav = nav_path.read_text(encoding="utf-8")
        self.assertIn('id: "gallery", label: "图库"', nav)
        self.assertTrue(
            ("NAI 本地图库" in nav) or ("本地图库资产" in nav),
            "nav note should identify local gallery product",
        )
        try:
            result = subprocess.run(
                ["node", "--check", str(nav_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except FileNotFoundError:
            self.skipTest("node is not available for JS syntax check")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_default_ui_copy_says_click_to_view_all_images(self) -> None:
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        settings = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
        core = (ROOT / "web" / "app-core.js").read_text(encoding="utf-8")
        combined = "\n".join([index, settings, core])
        self.assertIn("单击查看详情与全部图片", combined)
        self.assertIn("单击查看详情与全部图片；侧边栏可预览咒语并送去生成或洗稿", core)
        self.assertIn("高级", settings)
        self.assertNotIn("单击作品直接去生图工作台；双击查看详情", combined)
        self.assertNotIn("双击查看详情", combined)
        self.assertNotIn('id="prefQuickStudio" checked', settings)

    def test_legacy_ai_work_endpoint_aliases_current_detail_api(self) -> None:
        client = TestClient(server.app)
        sample = {
            "work": {"id": 1001, "title": "sample", "AI_type": "NAI", "image_count": 2},
            "images": [
                {"work_id": 1001, "file_name": "1001_p0.webp", "page_index": 0},
                {"work_id": 1001, "file_name": "1001_p1.webp", "page_index": 1},
            ],
        }
        with patch.object(gallery_routes, "_work_scope_guard", return_value=None), patch.object(
            gallery_routes.DB, "get_work_detail", return_value=sample
        ):
            current = client.get("/api/work/1001")
            legacy = client.get("/api/ai_work/1001")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(current.json(), sample)
        self.assertEqual(legacy.json(), sample)

    def test_app_tool_routes_redirect_to_classic_pages(self) -> None:
        client = TestClient(server.app)
        expected = {
            "/app": "/",
            "/app/gallery": "/",
            "/app/studio": "/studio",
            "/app/generated": "/generated",
            "/app/butler": "/butler",
            "/app/remix": "/remix",
            "/app/progress": "/progress",
            "/app/tags": "/nai-tags",
            "/app/pixiv": "/pixiv",
            "/app/settings": "/settings",
            "/app/director": "/director",
            "/app/pipeline": "/pipeline",
        }
        for src, dest in expected.items():
            with self.subTest(src=src):
                response = client.get(src, follow_redirects=False)
                self.assertEqual(response.status_code, 303, src)
                location = response.headers.get("location") or ""
                self.assertTrue(
                    location == dest or location.endswith(dest),
                    f"{src} -> {location!r}, expected {dest}",
                )
        query = client.get("/app/studio?from=123&gallery=codex", follow_redirects=False)
        self.assertEqual(query.status_code, 303)
        location = query.headers.get("location") or ""
        self.assertIn("/studio", location)
        self.assertIn("from=123", location)
        self.assertIn("gallery=codex", location)


if __name__ == "__main__":
    unittest.main()
