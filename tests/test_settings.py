from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import user_prefs
from studio_service import optimize_comment


class UserPrefsTests(unittest.TestCase):
    def test_defaults_nai_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_prefs, "PREFS_PATH", Path(tmp) / "user_prefs.json"):
                prefs = user_prefs.load_prefs()
        self.assertTrue(prefs["nai_only_gallery"])
        self.assertFalse(prefs["quick_send_studio"])
        self.assertEqual(prefs["default_optimize_mode"], "smart")

    def test_show_other_disables_nai_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_prefs.json"
            with patch.object(user_prefs, "PREFS_PATH", path):
                user_prefs.save_prefs({"show_other_ai_types": True})
                prefs = user_prefs.load_prefs()
        self.assertTrue(prefs["show_other_ai_types"])
        self.assertFalse(prefs["nai_only_gallery"])

    def test_save_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_prefs.json"
            with patch.object(user_prefs, "PREFS_PATH", path):
                user_prefs.save_prefs({
                    "quick_send_studio": False,
                    "default_optimize_mode": "sanitize",
                })
                raw = json.loads(path.read_text(encoding="utf-8"))
                prefs = user_prefs.load_prefs()
        self.assertFalse(raw["quick_send_studio"])
        self.assertEqual(raw["default_optimize_mode"], "sanitize")
        self.assertFalse(prefs["quick_send_studio"])

    def test_playbook_is_a_valid_default_optimize_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_prefs.json"
            with patch.object(user_prefs, "PREFS_PATH", path):
                user_prefs.save_prefs({"default_optimize_mode": "playbook"})
                prefs = user_prefs.load_prefs()
        self.assertEqual(prefs["default_optimize_mode"], "playbook")


class StudioFallbackTests(unittest.TestCase):
    def test_smart_optimize_fallback_to_sanitize(self) -> None:
        comment = {"prompt": "1girl, gore, standing", "uc": "bad"}

        def _fake_optimize(c, mode="smart", profile="", intent=""):
            if mode == "smart":
                raise ValueError("no api key")
            return {
                "ok": True,
                "provider": "local",
                "texts": {
                    "prompt": "1girl, standing",
                    "uc": "bad",
                    "base_caption": "",
                    "char_captions": [],
                },
                "comment": {"prompt": "1girl, standing", "uc": "bad"},
                "message": "净化完成",
            }

        with patch("studio_service.optimize_nai_prompt", side_effect=_fake_optimize):
            result = optimize_comment(comment, mode="smart")
        self.assertTrue(result.get("fallback"))
        self.assertIn("before", result)
        self.assertNotIn("gore", result["texts"]["prompt"].lower())


if __name__ == "__main__":
    unittest.main()
