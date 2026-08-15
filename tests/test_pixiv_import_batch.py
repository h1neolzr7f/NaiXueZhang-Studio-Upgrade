from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.asgi_client import TestClient

import pixiv_accounts
import server


class PixivImportBatchTests(unittest.TestCase):
    def _patch_paths(self, tmp: str):
        data_dir = Path(tmp)
        return (
            patch.object(pixiv_accounts, "DATA_DIR", data_dir),
            patch.object(pixiv_accounts, "ACCOUNTS_PATH", data_dir / "pixiv_accounts.local.json"),
            patch.object(
                pixiv_accounts,
                "ACCOUNTS_BACKUP_PATH",
                data_dir / "pixiv_accounts.local.backup.json",
            ),
        )

    def test_parse_import_formats(self) -> None:
        long = "a" * 40
        self.assertEqual(
            pixiv_accounts._parse_import_line(long)["refresh_token"],
            long,
        )
        row = pixiv_accounts._parse_import_line(f"主号|{long}|温柔系")
        self.assertEqual(row["label"], "主号")
        self.assertEqual(row["direction"], "温柔系")
        row2 = pixiv_accounts._parse_import_line(
            '{"label":"JSON号","refresh_token":"%s"}' % long
        )
        self.assertEqual(row2["label"], "JSON号")
        self.assertIsNone(pixiv_accounts._parse_import_line("# comment"))
        # short tokens parse but fail shape validation on import
        short = pixiv_accounts._parse_import_line("short")
        self.assertIsNotNone(short)
        self.assertIsNotNone(pixiv_accounts._validate_refresh_token_shape(short["refresh_token"]))

    def test_import_batch_skip_dup_and_api(self) -> None:
        if os.name != "nt":
            self.skipTest("Pixiv account import persists refresh tokens via Windows DPAPI")
        long1 = "b" * 48
        long2 = "c" * 48
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3 = self._patch_paths(tmp)
            with p1, p2, p3, patch.object(
                pixiv_accounts, "test_account_auth", return_value={"ok": True, "message": "ok", "user": {"id": "1", "name": "u1"}}
            ), patch.object(pixiv_accounts, "_assert_pixiv_uid_available", return_value=None), patch.object(
                pixiv_accounts, "refresh_account_stats", return_value={}
            ):
                r1 = pixiv_accounts.import_accounts_batch(
                    f"号1|{long1}\n号2|{long2}",
                    verify=True,
                )
                self.assertEqual(r1["ok_count"], 2)
                r2 = pixiv_accounts.import_accounts_batch(
                    f"重复|{long1}",
                    verify=True,
                    skip_duplicates=True,
                )
                self.assertEqual(r2["skip_count"], 1)
                self.assertEqual(len(pixiv_accounts.list_accounts()), 2)

                client = TestClient(server.app)
                res = client.post(
                    "/api/pixiv/accounts/import",
                    json={"text": f"号3|{'d' * 48}", "verify": False},
                )
                self.assertEqual(res.status_code, 200, res.text)
                body = res.json()
                self.assertGreaterEqual(body.get("ok_count", 0), 1)


if __name__ == "__main__":
    unittest.main()
