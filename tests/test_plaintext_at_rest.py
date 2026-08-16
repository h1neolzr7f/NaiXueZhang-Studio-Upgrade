# -*- coding: utf-8 -*-
"""Regression: plaintext credentials must never be written to disk.

Covers nai_api.py token file and pixiv_accounts.py accounts file:
main file, backup file and temp file are all asserted plaintext-free.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import nai_api
import pixiv_accounts

PLAIN_NOVELAI = "pst-PLAINTEXT-NOVELAI-TOKEN-123456"
PLAIN_PIXIV = "PIXIV-PLAINTEXT-REFRESH-TOKEN-123456"


@unittest.skipUnless(os.name == "nt", "DPAPI token-at-rest checks are Windows-only")
class PlaintextAtRestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_token_path = nai_api.TOKEN_PATH
        self._orig_acc_path = pixiv_accounts.ACCOUNTS_PATH
        self._orig_acc_backup = pixiv_accounts.ACCOUNTS_BACKUP_PATH
        self._orig_data_dir = pixiv_accounts.DATA_DIR
        nai_api.TOKEN_PATH = self.tmp / "nai_token.test.json"
        pixiv_accounts.ACCOUNTS_PATH = self.tmp / "accounts.test.json"
        pixiv_accounts.ACCOUNTS_BACKUP_PATH = self.tmp / "accounts.test.backup.json"
        pixiv_accounts.DATA_DIR = self.tmp

    def tearDown(self) -> None:
        nai_api.TOKEN_PATH = self._orig_token_path
        pixiv_accounts.ACCOUNTS_PATH = self._orig_acc_path
        pixiv_accounts.ACCOUNTS_BACKUP_PATH = self._orig_acc_backup
        pixiv_accounts.DATA_DIR = self._orig_data_dir

    def test_nai_token_file_never_contains_plaintext(self) -> None:
        nai_api.save_token(PLAIN_NOVELAI)
        raw = nai_api.TOKEN_PATH.read_text(encoding="utf-8")
        self.assertNotIn(PLAIN_NOVELAI, raw)
        self.assertIn("dpapi:v1:", raw)
        # 读取应还原
        entries = nai_api._normalize_token_entries()
        self.assertTrue(any(PLAIN_NOVELAI == e.get("token") for e in entries))

    def test_nai_remove_token_keeps_file_encrypted(self) -> None:
        nai_api.save_token(PLAIN_NOVELAI)
        entries = nai_api._normalize_token_entries()
        nai_api._remove_token_entry(entries[0], "test")
        raw = nai_api.TOKEN_PATH.read_text(encoding="utf-8")
        self.assertNotIn(PLAIN_NOVELAI, raw)

    def test_pixiv_accounts_main_and_backup_encrypted(self) -> None:
        data = {
            "active_id": "acc_t",
            "accounts": [
                {
                    "id": "acc_t",
                    "label": "t",
                    "refresh_token": PLAIN_PIXIV,
                    "pixiv_user_id": None,
                    "created_at": "now",
                    "updated_at": "now",
                }
            ],
        }
        pixiv_accounts._save_accounts_file(data)
        main_raw = pixiv_accounts.ACCOUNTS_PATH.read_text(encoding="utf-8")
        self.assertNotIn(PLAIN_PIXIV, main_raw)
        self.assertIn("dpapi:v1:", main_raw)
        # 再保存一次 → 写备份（备份内容是上一版加密数据）
        decoded = pixiv_accounts._read_accounts_secret_file(pixiv_accounts.ACCOUNTS_PATH)
        pixiv_accounts._save_accounts_file(decoded)
        backup_raw = pixiv_accounts.ACCOUNTS_BACKUP_PATH.read_text(encoding="utf-8")
        self.assertNotIn(PLAIN_PIXIV, backup_raw)
        self.assertIn("dpapi:v1:", backup_raw)
        # 解密还原
        restored = pixiv_accounts._read_accounts_secret_file(pixiv_accounts.ACCOUNTS_PATH)
        self.assertEqual(restored["accounts"][0]["refresh_token"], PLAIN_PIXIV)

    def test_no_tmp_leftover_plaintext(self) -> None:
        data = {
            "active_id": "acc_t",
            "accounts": [
                {"id": "acc_t", "label": "t", "refresh_token": PLAIN_PIXIV}
            ],
        }
        pixiv_accounts._save_accounts_file(data)
        leftovers = list(self.tmp.glob("*.tmp"))
        for leftover in leftovers:
            self.assertNotIn(PLAIN_PIXIV, leftover.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
