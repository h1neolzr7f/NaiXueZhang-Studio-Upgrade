from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from db import Database
from gallery_index import find_near_duplicates, hash_bands, hash_to_text, run_incremental
from nai_authorization import (
    ACTION_STUDIO,
    compile_batch_authorization,
    consume_ticket,
    issue_for_preview,
    reset_authorization_state_for_tests,
)
from nai_batch import start_studio_generate


class MutationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_authorization_state_for_tests()

    def test_start_batch_source_authorizes_before_token_check(self) -> None:
        text = Path("nai_batch.py").read_text(encoding="utf-8")
        fn_at = text.find("def start_batch(")
        auth_at = text.find("auth = authorize_start_batch(", fn_at)
        token_at = text.find("generation_concurrency_for_batch(normalized", fn_at)
        self.assertGreater(fn_at, 0)
        self.assertGreater(auth_at, fn_at)
        self.assertGreater(token_at, auth_at)
        auth_block = text[auth_at:token_at]
        self.assertIn("paid_authorized=paid_reuse", auth_block)
        self.assertNotIn("paid_authorized=_paid_authorized", auth_block)

    def test_generate_image_source_blocks_before_token_pick(self) -> None:
        text = Path("nai/generate.py").read_text(encoding="utf-8")
        fn_at = text.find("async def generate_image")
        auth_at = text.find("authorization_required", fn_at)
        pick_at = text.find("_pick_available_token", fn_at)
        self.assertGreater(auth_at, fn_at)
        self.assertGreater(pick_at, auth_at)

    def test_removing_ticket_check_would_fail_paid_start(self) -> None:
        comment = {"prompt": "1girl", "action": "img2img", "image": "abc"}
        from nai_authorization import authorize_start_batch as real

        called = {"n": 0}

        def wrapped(*args, **kwargs):
            called["n"] += 1
            return real(*args, **kwargs)

        with patch("nai_authorization.authorize_start_batch", side_effect=wrapped):
            start_studio_generate(comment, force_free=True)
        self.assertGreaterEqual(called["n"], 1)
        result = start_studio_generate(comment, force_free=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ticket_invalid")

    def test_ticket_consume_is_required_for_non_free(self) -> None:
        preview = compile_batch_authorization(
            [{"patched_comment": {"prompt": "1girl", "action": "img2img", "image": "abc"}}],
            {"copies": 1},
            force_free=True,
            action=ACTION_STUDIO,
        )
        ticket = issue_for_preview(preview)["ticket"]
        consume_ticket(ticket, preview)
        with self.assertRaises(Exception):
            consume_ticket(ticket, preview)

    def test_single_high_bit_bucket_would_miss_cross_bucket_pair(self) -> None:
        from gallery_index import hash_bucket, hamming

        left = 0xF000_0000_0000_0000
        right = left ^ (1 << 60)
        self.assertEqual(hamming(left, right), 1)
        self.assertNotEqual(hash_bucket(left), hash_bucket(right))
        self.assertTrue(any(a == b for a, b in zip(hash_bands(left, 4), hash_bands(right, 4))))

    def test_fixed_500_without_cursor_cannot_cover_501(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            try:
                for index in range(1, 502):
                    db.conn.execute(
                        "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (?, ?, '', 't', 'nai')",
                        (index, f"w{index}"),
                    )
                    png = root / f"{index}.png"
                    Image.new("RGB", (8, 8), (index % 255, 1, 2)).save(png)
                    db.conn.execute(
                        """
                        INSERT INTO work_images(work_id, page_index, local_path, source_sha256, downloaded, prompt_text)
                        VALUES (?, 0, ?, '', 1, '1girl')
                        """,
                        (index, png.name),
                    )
                db.conn.commit()
                first = run_incremental(db, images_dir=root, visual=False)
                self.assertTrue(first["truncated"])
                self.assertIsNotNone(first["next_cursor"])
            finally:
                db.close()


class FaultInjectionTests(unittest.TestCase):
    def test_provider_errors_do_not_claim_local_library_is_down(self) -> None:
        from online_library import reset_online_state_for_tests, search_online, set_provider_fail_mode

        reset_online_state_for_tests()
        for mode in ("timeout", "unavailable", "malformed"):
            set_provider_fail_mode(mode)
            result = search_online("x")
            self.assertFalse(result["ok"])
            self.assertTrue(result["local_library_available"])
        reset_online_state_for_tests()

    def test_cache_eviction_source_cannot_delete_library_rows(self) -> None:
        text = Path("library_lifecycle.py").read_text(encoding="utf-8")
        self.assertNotIn("DELETE FROM works", text)
        self.assertNotIn("work_images", text)
        self.assertIn("unlink", text)

    def test_index_source_uses_keyset_not_fixed_offset(self) -> None:
        text = Path("gallery_index.py").read_text(encoding="utf-8")
        self.assertIn("work_id > ?", text)
        self.assertIn("page_index > ?", text)
        self.assertIn("next_cursor", text)

    def test_hash_bands_are_t_plus_one(self) -> None:
        self.assertEqual(len(hash_bands(1, 4)), 5)
        self.assertEqual(len(hash_bands(1, 1)), 2)
