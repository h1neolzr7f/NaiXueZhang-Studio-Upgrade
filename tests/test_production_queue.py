from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.asgi_client import TestClient

import production_queue
import server


class ProductionQueueTests(unittest.TestCase):
    def test_queue_add_toggle_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(production_queue, "QUEUE_PATH", Path(tmp) / "production_queue.json"):
                self.assertFalse(production_queue.has(42))
                production_queue.add(42, note="asset")
                self.assertTrue(production_queue.has(42))
                self.assertEqual(production_queue.list_ids(), [42])
                production_queue.toggle(42)
                self.assertFalse(production_queue.has(42))
                production_queue.add(7)
                production_queue.add(8)
                production_queue.clear()
                self.assertEqual(production_queue.list_ids(), [])

    def test_queue_api_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(production_queue, "QUEUE_PATH", Path(tmp) / "production_queue.json"):
                client = TestClient(server.app)
                r = client.post("/api/queue/123/toggle")
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json().get("queued"))
                s = client.get("/api/queue")
                self.assertEqual(s.status_code, 200)
                self.assertIn(123, s.json().get("ids") or [])
                d = client.delete("/api/queue/123")
                self.assertEqual(d.status_code, 200)
                self.assertFalse(d.json().get("queued"))

    def test_nav_is_gallery_first_with_production_surfaces(self) -> None:
        nav = (Path(__file__).resolve().parents[1] / "web" / "shared" / "site-nav.js").read_text(
            encoding="utf-8"
        )
        gallery = nav.find('id: "gallery"')
        generated = nav.find('id: "generated"')
        queue = nav.find('id: "queue"')
        studio = nav.find('id: "studio"')
        self.assertGreater(gallery, 0)
        self.assertLess(gallery, generated)
        # 待生成提升到主导航；完整对话收进「更多」
        self.assertIn('{ href: "/queue", id: "queue", label: "待生成" }', nav)
        self.assertLess(generated, studio)
        self.assertLess(studio, queue)
        self.assertIn("本地图库资产", nav)
        # 二级菜单按 创作/管理/系统 分组渲染
        self.assertIn('className = "nav-more-group"', nav)

    def test_detail_ctas_are_asset_first(self) -> None:
        # app.js 已按域拆分（app-detail.js / app-online-remix.js），合并断言
        root = Path(__file__).resolve().parents[1]
        app = "".join(
            (root / "web" / name).read_text(encoding="utf-8")
            for name in ("app.js", "app-detail.js", "app-online-remix.js")
        )
        self.assertIn("用此图生成", app)
        self.assertIn("加入待生成", app)
        self.assertIn("复制 Prompt 资产", app)
        self.assertIn("detailQueueBtn", app)

    def test_default_prefs_still_gallery_primary(self) -> None:
        import user_prefs

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_prefs, "PREFS_PATH", Path(tmp) / "user_prefs.json"):
                prefs = user_prefs.load_prefs()
        self.assertFalse(prefs["quick_send_studio"])
        self.assertTrue(prefs["nai_only_gallery"])


if __name__ == "__main__":
    unittest.main()
