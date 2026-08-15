"""v1.9 confirmed memory, handoff, and anti-disturbance. TTS is not scored here."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from butler import companion_state
from butler.tool_loop_bridge import COST_OR_DESTRUCTIVE, execute_chat_action
from tests.asgi_client import TestClient

import server


class CompanionV19Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "companion_state.json"
        self.patcher = patch.object(companion_state, "STATE_PATH", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_unconfirmed_memory_is_not_recalled(self) -> None:
        item = companion_state.propose_memory("竖图优先", agent="tomori")
        self.assertEqual(item["status"], "proposed")
        self.assertEqual(companion_state.confirmed_lines(), [])
        confirmed = companion_state.confirm_memory(item["id"], confirm=True)
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(companion_state.confirmed_lines(), ["竖图优先"])

    def test_forbidden_memory_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            companion_state.propose_memory("from screen", source="screen")

    def test_quiet_hours_and_rate_limit_block_delivery(self) -> None:
        companion_state.update_quiet(
            {"enabled": True, "start": "22:00", "end": "08:00", "max_events_per_hour": 1, "min_interval_seconds": 1800}
        )
        night = datetime(2026, 8, 15, 23, 0, tzinfo=timezone.utc)
        self.assertTrue(companion_state.in_quiet_hours(night))
        allowed = companion_state.delivery_allowed(night)
        self.assertFalse(allowed["ok"])
        self.assertEqual(allowed["reason"], "quiet_hours")
        companion_state.update_quiet({"enabled": False})
        companion_state.mark_delivered("evt-1")
        again = companion_state.delivery_allowed(datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc))
        self.assertFalse(again["ok"])

    def test_handoff_is_between_desks_only(self) -> None:
        item = companion_state.record_handoff(from_agent="sakiko", to_agent="tomori", note="先出图")
        self.assertEqual(item["to_agent"], "tomori")
        with self.assertRaises(ValueError):
            companion_state.record_handoff(from_agent="sakiko", to_agent="god", note="no")
        consumed = companion_state.consume_handoff("tomori")
        self.assertIsNotNone(consumed)
        self.assertIsNone(companion_state.consume_handoff("tomori"))

    def test_companion_routes_and_no_tts_barrel(self) -> None:
        client = TestClient(server.app)
        state = client.get("/api/companion/state")
        self.assertEqual(state.status_code, 200)
        self.assertFalse(state.json().get("tts", {}).get("core"))
        proposed = client.post("/api/companion/memory/propose", json={"text": "喜欢暖色", "agent": "sakiko"})
        self.assertEqual(proposed.status_code, 200)
        memory_id = proposed.json()["memory"]["id"]
        confirm = client.post("/api/companion/memory/confirm", json={"id": memory_id, "confirm": True})
        self.assertEqual(confirm.json()["memory"]["status"], "confirmed")
        events = client.get("/api/companion/events")
        self.assertEqual(events.status_code, 200)
        self.assertFalse(events.json().get("tts", {}).get("enabled"))

    def test_kernel_bridge_does_not_execute_generate(self) -> None:
        self.assertIn("generate_image", COST_OR_DESTRUCTIVE)
        result = execute_chat_action(
            {"tool": "generate_image", "arguments": {"prompt": "1girl"}},
            agent_id="tomori",
        )
        self.assertEqual(result["status"], "workflow_requested")
        preview = execute_chat_action(
            {
                "tool": "compile_nai_preview",
                "arguments": {"comment": {"prompt": "1girl", "width": 832, "height": 1216, "steps": 28}},
            },
            agent_id="tomori",
        )
        self.assertEqual(preview["status"], "succeeded")
        self.assertEqual(preview["data"]["action"], "generate")


if __name__ == "__main__":
    unittest.main()
