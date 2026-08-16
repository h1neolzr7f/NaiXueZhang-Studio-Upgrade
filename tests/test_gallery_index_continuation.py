from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from db import Database
from gallery_index import (
    MAX_INCREMENTAL_ITEMS,
    find_near_duplicates,
    hash_bands,
    hamming,
    hash_to_text,
    list_stale,
    list_unindexed,
    reconcile_index,
    run_incremental,
    visibility_counts,
)


def _solid(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (32, 32), color)


class IndexContinuationAndVisibilityTests(unittest.TestCase):
    def _fill(self, db: Database, root: Path, count: int) -> None:
        for index in range(1, count + 1):
            db.conn.execute(
                "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (?, ?, '', 'arknights', 'nai')",
                (index, f"w{index}"),
            )
            png = root / f"{index}.png"
            _solid((index * 3 % 255, 20, 80)).save(png)
            db.conn.execute(
                """
                INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                VALUES (?, 0, ?, '', 1, '1girl')
                """,
                (index, png.name),
            )
        db.conn.commit()

    def test_501_and_1001_keyset_does_not_skip_or_lose_items(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                self._fill(db, root, 1001)
                seen: set[int] = set()
                cursor = None
                rounds = 0
                while True:
                    result = run_incremental(db, cursor=cursor, images_dir=root, visual=False)
                    rounds += 1
                    rows = db.conn.execute(
                        "SELECT work_id FROM gallery_index_files ORDER BY work_id"
                    ).fetchall()
                    current = {int(row["work_id"]) for row in rows}
                    self.assertTrue(seen.issubset(current))
                    seen = current
                    if not result["truncated"]:
                        break
                    cursor = result["next_cursor"]
                    self.assertIsNotNone(cursor)
                self.assertGreaterEqual(rounds, 3)
                self.assertEqual(len(seen), 1001)
                self.assertEqual(visibility_counts(db.conn)["unindexed"], 0)
            finally:
                db.close()

    def test_501_first_page_is_truncated_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                self._fill(db, root, 501)
                first = run_incremental(db, images_dir=root, visual=False)
                self.assertTrue(first["truncated"])
                self.assertEqual(first["scanned"], MAX_INCREMENTAL_ITEMS)
                self.assertEqual(first["next_cursor"]["work_id"], MAX_INCREMENTAL_ITEMS)
                replay = run_incremental(db, images_dir=root, visual=False)
                self.assertEqual(replay["next_cursor"], first["next_cursor"])
                second = run_incremental(db, cursor=first["next_cursor"], images_dir=root, visual=False)
                self.assertFalse(second["truncated"])
                self.assertEqual(visibility_counts(db.conn)["unindexed"], 0)
            finally:
                db.close()

    def test_unindexed_and_stale_are_anti_joins_not_page_windows(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                self._fill(db, root, 3)
                run_incremental(db, images_dir=root, visual=False)
                db.conn.execute(
                    "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (99, 'new', '', 'arknights', 'nai')"
                )
                png = root / "99.png"
                _solid((9, 9, 9)).save(png)
                db.conn.execute(
                    """
                    INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                    VALUES (99, 0, ?, '', 1, '1girl')
                    """,
                    (png.name,),
                )
                db.conn.execute("DELETE FROM work_images WHERE work_id = 1")
                db.conn.commit()
                self.assertEqual([item["work_id"] for item in list_unindexed(db.conn)], [99])
                stale = list_stale(db.conn)
                self.assertEqual([item["work_id"] for item in stale], [1])
                scoped = reconcile_index(db.conn, work_ids=[99])
                self.assertEqual(scoped["stale_removed"], 0)
                self.assertEqual([item["work_id"] for item in list_stale(db.conn)], [1])
                full = reconcile_index(db.conn, work_ids=[1, 99])
                self.assertEqual(full["stale_removed"], 1)
                self.assertEqual(list_stale(db.conn), [])
            finally:
                db.close()

    def test_cross_bucket_hamming_one_and_two_are_recalled(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                from gallery_index import ensure_schema

                ensure_schema(db.conn)
                base = 0x0F0F_0000_0000_0000
                neighbor = base ^ (1 << 60)
                far = base ^ (1 << 1)
                self.assertEqual(hamming(base, neighbor), 1)
                self.assertNotEqual(
                    hash_bands(base, 4)[0],
                    hash_bands(neighbor, 4)[0],
                )
                rows = [
                    (1, base, base),
                    (2, neighbor, neighbor),
                    (3, far, far),
                ]
                for work_id, dhash, phash in rows:
                    db.conn.execute(
                        """
                        INSERT INTO gallery_image_hashes(
                            image_key, work_id, page_index, sha256, dhash, phash,
                            width, height, algo_rev, updated_at
                        ) VALUES (?, ?, 0, '', ?, ?, 32, 32, 1, 'now')
                        """,
                        (f"{work_id}:0", work_id, hash_to_text(dhash), hash_to_text(phash)),
                    )
                db.conn.commit()
                groups = find_near_duplicates(db.conn, dhash_threshold=2, phash_threshold=2)
                members = {
                    item["image_key"]
                    for group in groups
                    for item in group["items"]
                }
                self.assertIn("1:0", members)
                self.assertIn("2:0", members)
                self.assertIn("3:0", members)
                paired = {
                    tuple(sorted((left["image_key"], right["image_key"])))
                    for group in groups
                    for left in group["items"]
                    for right in group["items"]
                    if left["image_key"] != right["image_key"]
                }
                self.assertIn(("1:0", "2:0"), paired)
                self.assertIn(("1:0", "3:0"), paired)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
