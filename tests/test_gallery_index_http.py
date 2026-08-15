"""Additive gallery index HTTP. Search JSON stays frozen."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from db import Database
from gallery_index import run_incremental, sha256_bytes
from tests.asgi_client import TestClient

import server


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (48, 48)) -> Image.Image:
    return Image.new("RGB", size, color)


class GalleryIndexHttpTests(unittest.TestCase):
    def test_search_route_source_is_unchanged_shape(self) -> None:
        gallery = (Path(__file__).resolve().parents[1] / "routes" / "gallery.py").read_text(encoding="utf-8")
        search = gallery.split("def api_search", 1)[1].split("\n@router", 1)[0]
        self.assertIn('result["gallery_id"] = gid', search)
        self.assertIn("serialize_gallery_payload(result, gid)", search)
        self.assertNotIn("duplicates", search)
        self.assertNotIn("find_similar", search)
        self.assertIn("/api/gallery/{gallery_id}/index/status", gallery)
        self.assertIn("/api/gallery/{gallery_id}/index/incremental", gallery)
        self.assertIn("/api/gallery/{gallery_id}/duplicates", gallery)
        self.assertIn("/api/gallery/{gallery_id}/similar", gallery)

    def test_additive_routes_use_existing_db(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                db.conn.execute(
                    "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (1, 'amiya', '', 'arknights', 'nai')"
                )
                png = root / "a.png"
                _solid((30, 40, 50)).save(png)
                digest = sha256_bytes(png.read_bytes())
                db.conn.execute(
                    """
                    INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                    VALUES (1, 0, ?, ?, 1, '1girl')
                    """,
                    (str(png), digest),
                )
                db.conn.commit()
                run_incremental(db, [1], images_dir=root)
                client = TestClient(server.app)
                with patch("routes.gallery._gallery_db", return_value=db), patch(
                    "routes.gallery.get_gallery_spec"
                ) as spec:
                    spec.return_value.images_dir = root
                    status = client.get("/api/gallery/codex/index/status")
                    incremental = client.post("/api/gallery/codex/index/incremental", json={"work_ids": [1]})
                    dups = client.get("/api/gallery/codex/duplicates")
                    similar = client.get("/api/gallery/codex/similar?work_id=1")
            finally:
                db.close()
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json().get("gallery_id"), "codex")
        self.assertEqual(status.json().get("embed", {}).get("provider"), "local_none")
        self.assertEqual(incremental.status_code, 200)
        self.assertEqual(incremental.json().get("text_dirty"), 0)
        self.assertEqual(dups.status_code, 200)
        self.assertEqual(dups.json().get("kind"), "exact")
        self.assertEqual(similar.status_code, 200)
        self.assertEqual(similar.json().get("query", {}).get("work_id"), 1)


if __name__ == "__main__":
    unittest.main()
