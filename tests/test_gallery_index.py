"""Cloud-safe gallery index: dirty set, exact/near dups, local similar."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from PIL import Image

from db import Database
from gallery_index import (
    TEXT_INDEX_REV,
    VISUAL_INDEX_REV,
    IndexImage,
    compute_dhash,
    find_exact_duplicates,
    find_near_duplicates,
    find_similar,
    hamming,
    image_key,
    index_images,
    index_status,
    is_dirty,
    sha256_bytes,
)


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> Image.Image:
    return Image.new("RGB", size, color)


class DirtyPredicateTests(unittest.TestCase):
    def test_missing_row_or_rev_or_parser_is_dirty(self) -> None:
        self.assertTrue(is_dirty(None, file_size=1, mtime_ns=2))
        fresh = {
            "file_size": 10,
            "mtime_ns": 20,
            "source_sha256": "abc",
            "parser_version": "qq-nai-v1+novelai-3d9c7b7",
            "text_rev": TEXT_INDEX_REV,
            "visual_rev": VISUAL_INDEX_REV,
            "embed_rev": 0,
        }
        self.assertFalse(
            is_dirty(
                fresh,
                file_size=10,
                mtime_ns=20,
                source_sha256="abc",
                parser_version="qq-nai-v1+novelai-3d9c7b7",
            )
        )
        self.assertTrue(
            is_dirty(
                {**fresh, "text_rev": 0},
                file_size=10,
                mtime_ns=20,
                source_sha256="abc",
            )
        )
        self.assertTrue(
            is_dirty(
                fresh,
                file_size=10,
                mtime_ns=20,
                source_sha256="abc",
                parser_version="newer-parser",
            )
        )
        self.assertTrue(
            is_dirty(
                fresh,
                file_size=11,
                mtime_ns=20,
                source_sha256="abc",
            )
        )


class GalleryIndexSqliteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.synced: list[int] = []

    def tearDown(self) -> None:
        self.conn.close()

    def test_incremental_only_dirties_changed_items(self) -> None:
        red = _solid((220, 10, 10))
        blue = _solid((10, 10, 220))
        first = index_images(
            self.conn,
            [
                IndexImage(work_id=1, page_index=0, source_sha256="aa", pixels=red),
                IndexImage(work_id=2, page_index=0, source_sha256="bb", pixels=blue),
            ],
            sync_text=self.synced.append,
        )
        self.assertEqual(first["text_dirty"], 2)
        self.assertEqual(first["visual_dirty"], 2)
        self.assertEqual(self.synced, [1, 2])
        self.synced.clear()
        second = index_images(
            self.conn,
            [
                IndexImage(work_id=1, page_index=0, source_sha256="aa", pixels=red),
                IndexImage(work_id=2, page_index=0, source_sha256="bb", pixels=blue),
            ],
            sync_text=self.synced.append,
        )
        self.assertEqual(second["text_dirty"], 0)
        self.assertEqual(self.synced, [])
        third = index_images(
            self.conn,
            [
                IndexImage(work_id=1, page_index=0, source_sha256="aa-changed", pixels=red),
                IndexImage(work_id=2, page_index=0, source_sha256="bb", pixels=blue),
            ],
            sync_text=self.synced.append,
        )
        self.assertEqual(third["works"], [1])
        self.assertEqual(self.synced, [1])

    def test_exact_and_near_duplicates_and_similar(self) -> None:
        red = _solid((200, 20, 20))
        red_twin = _solid((200, 20, 20))
        near = _solid((198, 22, 18))
        other = _solid((20, 200, 20), size=(72, 40))
        index_images(
            self.conn,
            [
                IndexImage(work_id=1, source_sha256="same", pixels=red),
                IndexImage(work_id=2, source_sha256="same", pixels=red_twin),
                IndexImage(work_id=3, source_sha256="near", pixels=near),
                IndexImage(work_id=4, source_sha256="other", pixels=other),
            ],
        )
        exact = find_exact_duplicates(self.conn)
        self.assertEqual(len(exact), 1)
        self.assertEqual({item["work_id"] for item in exact[0]["items"]}, {1, 2})
        near_groups = find_near_duplicates(self.conn)
        self.assertTrue(any(len(group["items"]) >= 2 for group in near_groups))
        similar = find_similar(self.conn, work_id=1, limit=8)
        neighbor_ids = {item["work_id"] for item in similar["items"]}
        self.assertIn(2, neighbor_ids)
        self.assertNotIn(1, neighbor_ids)
        status = index_status(self.conn, "codex")
        self.assertEqual(status["gallery_id"], "codex")
        self.assertEqual(status["hashed"], 4)
        self.assertEqual(status["embed"]["provider"], "local_none")
        self.assertFalse(status["embed"]["outbound"])

    def test_hamming_and_keys(self) -> None:
        self.assertEqual(hamming(0b1010, 0b1000), 1)
        self.assertEqual(image_key(9, 2), "9:2")
        left = compute_dhash(_solid((10, 10, 10)))
        right = compute_dhash(_solid((10, 10, 10)))
        self.assertEqual(left, right)


class DatabaseIncrementalIndexTests(unittest.TestCase):
    def test_database_incremental_uses_existing_fts_and_no_second_store(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            self.addCleanup(db.close)
            db.conn.execute(
                "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (1, 'amiya', '', 'arknights', 'nai')"
            )
            png = root / "a.png"
            _solid((30, 40, 50)).save(png)
            digest = sha256_bytes(png.read_bytes())
            db.conn.execute(
                """
                INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                VALUES (1, 0, ?, ?, 1, '1girl, amiya')
                """,
                (str(png), digest),
            )
            db.conn.commit()
            first = db.incremental_index([1], images_dir=root)
            self.assertEqual(first["text_dirty"], 1)
            second = db.incremental_index([1], images_dir=root)
            self.assertEqual(second["text_dirty"], 0)
            fts = db.conn.execute("SELECT work_id FROM works_fts WHERE works_fts MATCH 'amiya'").fetchall()
            self.assertEqual([int(row["work_id"]) for row in fts], [1])
            tables = {
                row[0]
                for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertIn("gallery_index_files", tables)
            self.assertIn("gallery_image_hashes", tables)
            self.assertNotIn("tasks", tables)
            self.assertNotIn("workflow_events", tables)
