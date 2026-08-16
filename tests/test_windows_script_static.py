from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_check():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_windows_scripts.py"
    spec = importlib.util.spec_from_file_location("check_windows_scripts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WindowsScriptStaticTests(unittest.TestCase):
    def test_required_windows_entries_exist_without_tokens(self) -> None:
        self.assertEqual(_load_check().check(), [])
