"""v1.9 confirmed memory, handoff, and anti-disturbance. TTS is not scored here."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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
            {
                "enabled": True,
                "start": "22:00",
                "end": "08:00",
                "timezone": "UTC",
                "max_events_per_hour": 1,
                "min_interval_seconds": 1800,
            }
        )
        night = datetime(2026, 8, 15, 23, 0, tzinfo=timezone.utc)
        self.assertTrue(companion_state.in_quiet_hours(night))
        allowed = companion_state.delivery_allowed(night)
        self.assertFalse(allowed["ok"])
        self.assertEqual(allowed["reason"], "quiet_hours")
        companion_state.update_quiet({"enabled": False, "max_events_per_hour": 1, "min_interval_seconds": 1800})
        companion_state.mark_delivered("evt-1")
        again = companion_state.delivery_allowed()
        self.assertFalse(again["ok"])
        self.assertIn(again["reason"], {"rate_hour", "rate_interval"})

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
        ack = client.post("/api/companion/events/ack", json={"key": "token_missing"})
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json().get("ack", {}).get("key"), "token_missing")

    def test_quiet_hours_use_configured_non_utc_timezone(self) -> None:
        companion_state.update_quiet(
            {"enabled": True, "start": "22:00", "end": "23:00", "timezone": "Asia/Tokyo"}
        )
        stamp = datetime(2026, 8, 15, 13, 30, tzinfo=timezone.utc)
        self.assertTrue(companion_state.in_quiet_hours(stamp))
        utc_settings = {**companion_state.load_state()["quiet"], "timezone": "UTC"}
        self.assertFalse(companion_state.in_quiet_hours(stamp, utc_settings))

    def test_concurrent_memory_writes_are_serialized(self) -> None:
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                companion_state.propose_memory(f"pref-{index}", agent="tomori")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        texts = [item["text"] for item in payload["memories"]]
        self.assertEqual(len(texts), 20)
        self.assertEqual(len(set(texts)), 20)
        self.assertLessEqual(len(payload["memories"]), companion_state.MAX_MEMORIES)

    def test_proactive_events_dedupe_ttl_and_ack(self) -> None:
        first = companion_state.collect_local_events(token_ok=False)
        second = companion_state.collect_local_events(token_ok=False)
        self.assertTrue(any(item["key"] == "token_missing" for item in first))
        self.assertTrue(any(item["key"] == "token_missing" for item in second))
        start = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        companion_state.ack_event("token_missing", ttl_sec=3600, at=start)
        acked = companion_state.collect_local_events(token_ok=False, now=start + timedelta(minutes=10))
        self.assertFalse(any(item["key"] == "token_missing" for item in acked))
        expired = companion_state.collect_local_events(token_ok=False, now=start + timedelta(hours=2))
        self.assertTrue(any(item["key"] == "token_missing" for item in expired))

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
