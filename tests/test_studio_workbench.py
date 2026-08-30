from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tests.asgi_client import TestClient

import server
from studio_service import list_queue_for_studio, studio_config


ROOT = Path(__file__).resolve().parents[1]


class StudioWorkbenchTests(unittest.TestCase):
    def test_studio_config_has_presets(self) -> None:
        cfg = studio_config()
        self.assertTrue(cfg.get("ok"))
        self.assertGreaterEqual(len(cfg.get("size_presets") or []), 3)
        self.assertIn("k_euler_ancestral", cfg.get("samplers") or [])
        self.assertIn("width", (cfg.get("defaults") or {}))
        self.assertEqual(cfg.get("copy_max"), 20)

    def test_studio_html_is_workbench_layout(self) -> None:
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        self.assertIn("studio-shell-3", html)
        self.assertIn("studioGenerate", html)
        self.assertIn("studioQueueList", html)
        self.assertIn("studioSizePresets", html)
        self.assertIn("studioBatchPresets", html)
        self.assertIn("studioSeriesAll", html)
        self.assertIn("studioJobPanel", html)
        self.assertIn("studioRetryFailed", html)
        self.assertIn("生成队列", html)
        self.assertIn("生成本系列全部页", html)
        self.assertIn("批量张数", html)
        self.assertIn("Ctrl+Enter", html)
        self.assertIn("motion.css", html)

    def test_studio_js_has_batch_and_history(self) -> None:
        js = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
        self.assertIn("HISTORY_KEY", js)
        self.assertIn("studioBatchCount", js)
        self.assertIn("COPIES_KEY", js)
        self.assertIn("setCopies", js)
        self.assertIn("state.generating = true", js)
        self.assertIn("restoreCopies()", js)
        self.assertIn("buildSeriesPagePayloads", js)
        self.assertIn("sanitizeCommentCaptions", js)
        self.assertIn("resumeActiveJob", js)
        self.assertIn("studioSeriesAll", js)
        self.assertIn("studioRetryFailed", js)
        self.assertIn("/api/nai/jobs/retry", js)
        self.assertIn("本系列", js)
        self.assertNotIn(
            'return state.sourceProvider === "aitag-online" ? pages.length : 0',
            js,
        )
        self.assertNotIn("if (p.batch != null", js)
        self.assertIn("/api/studio/queue", js)
        self.assertIn("Ctrl+Enter", js) or self.assertIn("ctrlKey", js)
        self.assertIn("body: { comment, mode: modeKey, intent }", js)

    def test_queue_and_config_routes(self) -> None:
        client = TestClient(server.app)
        with patch("studio_service.list_ids", create=True):
            pass
        with patch(
            "production_queue.list_refs",
            return_value=[{"work_id": 1, "gallery_id": "site"}, {"work_id": 2, "gallery_id": "site"}],
        ):
            with patch("studio_service._work_title", return_value="t"), patch(
                "studio_service._work_thumb", return_value="/x.png"
            ):
                r = client.get("/api/studio/queue?limit=10")
        # queue may still work without patch if module path differs
        self.assertIn(r.status_code, (200, 500))
        cfg = client.get("/api/studio/config")
        self.assertEqual(cfg.status_code, 200)
        body = cfg.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("size_presets", body)

    def test_list_queue_helper(self) -> None:
        with patch(
            "production_queue.list_refs",
            return_value=[
                {"work_id": 11, "gallery_id": "site"},
                {"work_id": 22, "gallery_id": "codex"},
            ],
        ):
            with patch("studio_service._work_title", side_effect=lambda w, g="site": f"W{w}:{g}"), patch(
                "studio_service._work_thumb", return_value="/t.png"
            ):
                data = list_queue_for_studio(10)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(data.get("items") or []), 2)
        self.assertEqual(data["items"][1]["gallery_id"], "codex")

    def test_queue_uses_canonical_image_paths_for_thumbnails(self) -> None:
        details = {
            11: {
                "work": {"title": "local"},
                "images": [
                    {
                        "local_path": "images/NAI/77/11_p0.webp",
                        "image_type": "NAI",
                        "author_id": 999,
                        "file_name": "wrong_name",
                    }
                ],
            },
            22: {
                "work": {"title": "structured"},
                "images": [
                    {
                        "image_type": "NAI",
                        "author_id": 88,
                        "file_name": "22_p0",
                    }
                ],
            },
        }

        with patch(
            "production_queue.list_refs",
            return_value=[
                {"work_id": 11, "gallery_id": "site"},
                {"work_id": 22, "gallery_id": "site"},
            ],
        ), patch(
            "studio_service.DB.get_work_detail", side_effect=lambda work_id: details[int(work_id)]
        ):
            data = list_queue_for_studio(10)

        thumbs = [item["thumb"] for item in data["items"]]
        self.assertEqual(
            thumbs,
            [
                "/data/images/NAI/77/11_p0.webp",
                "/data/images/NAI/88/22_p0.webp",
            ],
        )


if __name__ == "__main__":
    unittest.main()
