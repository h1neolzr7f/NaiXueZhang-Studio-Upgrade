from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from db import Database
from studio_service import import_from_work


class WorkLiteTests(unittest.TestCase):
    def test_get_work_detail_enriches_only_downloaded_images_with_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "detail.sqlite"
            detail = {
                "work": {"id": 1001, "title": "detail"},
                "images": [
                    {"file_name": "1001_p0", "image_path": "NAI/77/1001_p0.webp"},
                    {"file_name": "1001_p1", "image_path": "NAI/77/1001_p1.webp"},
                ],
            }
            with Database(db_path) as db:
                db.conn.execute(
                    "INSERT INTO works(id, detail_json, image_count) VALUES (?, ?, ?)",
                    (1001, json.dumps(detail), 2),
                )
                db.conn.executemany(
                    """
                    INSERT INTO work_images(
                        work_id, file_name, page_index, downloaded, local_path
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (1001, "1001_p0", 0, 1, "images/NAI/77/1001_p0.webp"),
                        (1001, "1001_p1", 1, 0, None),
                    ],
                )
                db.conn.commit()
                loaded = db.get_work_detail(1001)

            assert loaded is not None
            self.assertEqual(loaded["images"][0]["page_index"], 0)
            self.assertEqual(
                loaded["images"][0]["local_path"],
                "images/NAI/77/1001_p0.webp",
            )
            self.assertEqual(loaded["images"][1]["page_index"], 1)
            self.assertIsNone(loaded["images"][1]["local_path"])

    def test_get_work_lite_reads_image_paths_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lite.sqlite"
            with Database(db_path) as db:
                db.conn.execute(
                    """
                    INSERT INTO works(id, list_json, image_count)
                    VALUES (?, ?, ?)
                    """,
                    (
                        1001,
                        json.dumps(
                            {
                                "id": 1001,
                                "title": "test",
                                "AI_type": "NAI",
                                "userId": 7788,
                            },
                            ensure_ascii=False,
                        ),
                        2,
                    ),
                )
                db.conn.execute(
                    """
                    INSERT INTO work_images(
                        work_id, file_name, page_index, downloaded, image_type, author_id
                    ) VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (1001, "1001_p0.webp", 0, "STALE", 1),
                )
                db.conn.execute(
                    """
                    INSERT INTO work_images(
                        work_id, file_name, page_index, downloaded, image_type, author_id
                    ) VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (1001, "1001_p1.webp", 1, "STALE", 1),
                )
                db.conn.commit()
                lite = db.get_work_lite(1001)
            self.assertIsNotNone(lite)
            assert lite is not None
            self.assertEqual(lite["work"]["title"], "test")
            self.assertEqual(len(lite["images"]), 2)
            self.assertNotIn("ai_json", lite["images"][0])
            self.assertEqual(
                [
                    (image["image_type"], image["author_id"])
                    for image in lite["images"]
                ],
                [("NAI", 7788), ("NAI", 7788)],
            )
            self.assertFalse(lite["images"][1]["local_path"])

    def test_import_from_work_uses_cache(self) -> None:
        from gallery_cache import clear_all

        clear_all()
        payload = {
            "comment": {"prompt": "1girl"},
            "params": {},
            "chars": [],
            "base_caption": "",
        }
        with patch("studio_service.extract_chars", return_value=payload) as extract:
            with patch("studio_service._work_title", return_value="t"):
                with patch("studio_service._work_thumb", return_value="/thumb"):
                    first = import_from_work(42, 0)
                    second = import_from_work(42, 0)
        self.assertEqual(first["work_id"], 42)
        self.assertEqual(second["work_id"], 42)
        self.assertEqual(extract.call_count, 1)
        extract.assert_called_with(42, 0, gallery_id="site")

    def test_import_from_work_cache_is_gallery_scoped(self) -> None:
        from gallery_cache import clear_all

        clear_all()
        payload = {
            "comment": {"prompt": "1girl"},
            "params": {},
            "chars": [],
            "base_caption": "",
        }
        with patch("studio_service.extract_chars", return_value=payload) as extract:
            with patch("studio_service._work_title", return_value="t"):
                with patch("studio_service._work_thumb", return_value="/thumb"):
                    import_from_work(42, 0, "site")
                    import_from_work(42, 0, "codex")
        self.assertEqual(extract.call_count, 2)
        extract.assert_any_call(42, 0, gallery_id="site")
        extract.assert_any_call(42, 0, gallery_id="codex")


if __name__ == "__main__":
    unittest.main()
