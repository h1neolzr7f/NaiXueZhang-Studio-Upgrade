from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from db import Database
from gallery_index import run_incremental, visibility_counts
from nai_authorization import (
    ACTION_STUDIO,
    compile_batch_authorization,
    consume_ticket,
    issue_for_preview,
    reset_authorization_state_for_tests,
)


class SyntheticScaleTests(unittest.TestCase):
    def test_10k_metadata_index_continuation_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "gallery.db")
            try:
                db.conn.execute("BEGIN")
                for index in range(1, 10001):
                    db.conn.execute(
                        "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (?, ?, '', 't', 'nai')",
                        (index, f"w{index}"),
                    )
                    db.conn.execute(
                        """
                        INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                        VALUES (?, 0, '', '', 1, '1girl')
                        """,
                        (index,),
                    )
                db.conn.commit()
                cursor = None
                rounds = 0
                while True:
                    result = run_incremental(db, cursor=cursor, visual=False)
                    rounds += 1
                    if not result["truncated"]:
                        break
                    cursor = result["next_cursor"]
                self.assertGreaterEqual(rounds, 20)
                self.assertEqual(visibility_counts(db.conn)["unindexed"], 0)
                indexed = db.conn.execute("SELECT COUNT(*) AS c FROM gallery_index_files").fetchone()["c"]
                self.assertEqual(int(indexed), 10000)
            finally:
                db.close()


class SoakRepetitionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_authorization_state_for_tests()

    def test_authorization_issue_consume_repeats_without_flakes(self) -> None:
        comment = {"prompt": "1girl", "action": "img2img", "image": "abc"}
        failures = 0
        for _ in range(20):
            preview = compile_batch_authorization(
                [{"patched_comment": comment}],
                {"copies": 1},
                force_free=True,
                action=ACTION_STUDIO,
            )
            ticket = issue_for_preview(preview)["ticket"]
            try:
                consume_ticket(ticket, preview)
                consume_ticket(ticket, preview)
                failures += 1
            except Exception:
                pass
        self.assertEqual(failures, 0)


class MetadataSearchBenchTests(unittest.TestCase):
    def test_100k_keyset_scan_records_latency_without_windows_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "gallery.db")
            try:
                db.conn.execute("BEGIN")
                for index in range(1, 100001):
                    db.conn.execute(
                        """
                        INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded)
                        VALUES (?, 0, '', '', 1)
                        """,
                        (index,),
                    )
                db.conn.commit()
                started = time.perf_counter()
                rows = db.conn.execute(
                    """
                    SELECT work_id, page_index FROM work_images
                    WHERE downloaded = 1 AND (work_id > 50000 OR (work_id = 50000 AND page_index > 0))
                    ORDER BY work_id, page_index
                    LIMIT 501
                    """
                ).fetchall()
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.assertEqual(len(rows), 501)
                self.assertLess(elapsed_ms, 2000)
                # Linux synthetic only. Not a Windows 100k gallery claim.
            finally:
                db.close()
