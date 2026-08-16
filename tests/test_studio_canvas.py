"""Studio img2img/inpaint canvas: source-image API and UI wiring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from gallery_index import resolve_index_image_path
from studio_service import encode_local_source_image, resolve_work_image_path
from tests.asgi_client import TestClient

import server


ROOT = Path(__file__).resolve().parents[1]


class StudioCanvasTests(unittest.TestCase):
    def test_encode_local_png_is_raw_base64(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "src.png"
            Image.new("RGB", (32, 24), (12, 34, 56)).save(path)
            payload = encode_local_source_image(path)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mime"], "image/png")
        self.assertEqual(payload["width"], 32)
        self.assertEqual(payload["height"], 24)
        self.assertNotIn("data:", payload["image"])
        self.assertGreater(len(payload["image"]), 20)

    def test_source_image_route_uses_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "work.png"
            Image.new("RGB", (16, 16), (200, 10, 10)).save(path)
            client = TestClient(server.app)
            with patch("studio_service.resolve_work_image_path", return_value=path), patch(
                "studio_service._work_thumb", return_value="/data/images/x.png"
            ), patch("studio_service._work_title", return_value="canvas"):
                response = client.get("/api/studio/source-image?work_id=9&page_index=0&gallery_id=site")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("work_id"), 9)
        self.assertTrue(body.get("image"))

    def test_missing_source_image_is_400(self) -> None:
        client = TestClient(server.app)
        with patch("studio_service.resolve_work_image_path", return_value=None):
            response = client.get("/api/studio/source-image?work_id=9")
        self.assertEqual(response.status_code, 400)

    def test_workspace_and_classic_studio_have_canvas_controls(self) -> None:
        page = (ROOT / "frontend" / "src" / "pages" / "StudioPage.tsx").read_text(encoding="utf-8")
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
        self.assertIn("/api/studio/source-image", page)
        self.assertIn('mode === "img2img"', page)
        self.assertIn("inpaint", page)
        self.assertIn("ws-canvas-mask", page)
        self.assertIn("studioAction", html)
        self.assertIn("studioMaskCanvas", html)
        self.assertIn("studioLoadSourceImage", html)
        self.assertIn("requested_action", js)
        self.assertIn("exportMaskBase64", js)
        self.assertIn("exportCanvasBase64", js)
        self.assertIn("exportCanvasBase64", page)
        self.assertIn("/api/studio/source-image", js)
        self.assertIn("/api/nai/authorize", page)
        self.assertIn("/api/nai/authorize", js)
        self.assertIn("confirmed: true", js)

    def test_absolute_and_traversal_paths_cannot_leave_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as gallery_raw, tempfile.TemporaryDirectory() as evil_raw:
            images = Path(gallery_raw) / "images"
            images.mkdir()
            inside = images / "ok.png"
            Image.new("RGB", (8, 8), (1, 2, 3)).save(inside)
            evil = Path(evil_raw) / "evil.png"
            Image.new("RGB", (8, 8), (9, 9, 9)).save(evil)
            self.assertIsNone(resolve_index_image_path(str(evil), images))
            self.assertIsNone(resolve_index_image_path("../../../etc/passwd", images))
            self.assertIsNone(resolve_index_image_path("ok.png\x00.png", images))
            self.assertEqual(resolve_index_image_path("ok.png", images), inside.resolve())
            self.assertEqual(resolve_index_image_path(str(inside), images), inside.resolve())

            class _Result:
                def __init__(self, path: str) -> None:
                    self._path = path

                def fetchone(self):
                    return {"local_path": self._path}

            class _DB:
                def __init__(self, path: str) -> None:
                    self.conn = self

                def execute(self, *_args, **_kwargs):
                    return _Result(str(evil))

            with patch("studio_service._gallery_db", return_value=_DB(str(evil))), patch(
                "gallery_catalog.get_spec"
            ) as spec:
                spec.return_value.images_dir = images
                with patch("studio_service.DATA_DIR", Path(gallery_raw)):
                    self.assertIsNone(resolve_work_image_path(99))
            client = TestClient(server.app)
            with patch("studio_service.resolve_work_image_path", return_value=None):
                response = client.get("/api/studio/source-image?work_id=99")
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
