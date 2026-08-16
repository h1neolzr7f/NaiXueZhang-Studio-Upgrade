"""Confirmed memories must reach request_plan before chat_json, with secrets stripped."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from butler import companion_state
from butler.planning import request_plan


class PlannerMemoryInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "companion_state.json"
        self.patcher = patch.object(companion_state, "STATE_PATH", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_confirmed_memory_is_injected_before_chat_json_without_secrets(self) -> None:
        token = "pst-" + "abc123secret"
        unix_path = "/" + "/".join(("home", "user", "secret"))
        win_path = "C:" + "\\" + "\\".join(("Users", "me", "tok"))
        item = companion_state.propose_memory(
            f"竖图优先 {token} token=leak cookie=sid {unix_path} {win_path}",
            agent="tomori",
        )
        companion_state.confirm_memory(item["id"], confirm=True)
        captured: dict[str, object] = {}

        def fake_chat_json(prompt, payload, **_kwargs):
            captured["prompt"] = prompt
            captured["payload"] = payload
            return {"reply": "好", "actions": []}

        with patch("butler_service.chat_json", side_effect=fake_chat_json), patch(
            "butler_service._main_gallery_empty", return_value=False
        ):
            request_plan("帮我看看图库状态")

        payload = captured["payload"]
        prompt = str(captured["prompt"])
        self.assertIsInstance(payload, dict)
        prefs = payload.get("confirmed_preferences")
        self.assertTrue(prefs)
        blob = " ".join(prefs) + " " + prompt
        self.assertIn("竖图优先", blob)
        self.assertIn("已过滤", prompt)
        self.assertNotIn("pst-", blob)
        self.assertNotIn("token=leak", blob)
        self.assertNotIn("cookie=sid", blob)
        self.assertNotIn(unix_path, blob)
        self.assertNotIn(win_path, blob)

    def test_unconfirmed_or_secret_only_memory_is_not_injected(self) -> None:
        companion_state.propose_memory("还没确认的竖图", agent="tomori")
        secret_only = "pst-" + "onlytoken " + "/" + "/".join(("etc", "passwd"))
        secret = companion_state.propose_memory(secret_only, agent="tomori")
        companion_state.confirm_memory(secret["id"], confirm=True)
        captured: dict[str, object] = {}

        def fake_chat_json(prompt, payload, **_kwargs):
            captured["prompt"] = prompt
            captured["payload"] = payload
            return {"reply": "好", "actions": []}

        with patch("butler_service.chat_json", side_effect=fake_chat_json), patch(
            "butler_service._main_gallery_empty", return_value=False
        ):
            request_plan("帮我看看图库状态")

        payload = captured["payload"]
        self.assertNotIn("confirmed_preferences", payload)
        self.assertNotIn("还没确认的竖图", str(captured["prompt"]))
        self.assertNotIn("pst-", str(captured))
        self.assertNotIn("/" + "/".join(("etc", "passwd")), str(captured))


if __name__ == "__main__":
    unittest.main()
