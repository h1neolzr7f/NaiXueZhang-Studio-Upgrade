from __future__ import annotations

import unittest

from scripts.check_windows_scripts import check


class WindowsScriptStaticTests(unittest.TestCase):
    def test_required_windows_entries_exist_without_tokens(self) -> None:
        self.assertEqual(check(), [])
