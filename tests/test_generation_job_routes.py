from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from tests.asgi_client import TestClient

import server


class GenerationJobRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(server.app)

    def test_status_and_cancel_accept_stable_task_id(self) -> None:
        state = {"task_id": "job-1", "id": "job-1", "status": "running"}
        with patch("routes.char_swap.batch_status", return_value=state) as status, patch(
            "routes.char_swap.cancel_batch",
            return_value={"ok": True, "task_id": "job-1", "batch": state},
        ) as cancel:
            read = self.client.get("/api/plugin/char-swap/batch/status?task_id=job-1")
            stopped = self.client.post("/api/plugin/char-swap/batch/cancel?task_id=job-1")
        self.assertEqual(read.status_code, 200)
        self.assertEqual(stopped.status_code, 200)
        status.assert_called_once_with("job-1")
        cancel.assert_called_once_with("job-1")

    def test_unknown_generation_task_maps_to_not_found(self) -> None:
        missing = {
            "ok": False,
            "error": "not_found",
            "id": "missing",
            "task_id": "missing",
            "status": "not_found",
            "terminal": True,
        }
        with patch("routes.char_swap.batch_status", return_value=missing):
            response = self.client.get("/api/plugin/char-swap/batch/status?task_id=missing")
        self.assertEqual(response.status_code, 404)

    def test_generated_trash_entry_can_be_restored(self) -> None:
        restored = {"ok": True, "trash_id": "a" * 32, "restored_files": 3}
        with patch("routes.nai.restore_deleted", return_value=restored) as restore:
            response = self.client.post(f"/api/generated/trash/{'a' * 32}/restore")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), restored)
        restore.assert_called_once_with("a" * 32)

    def test_generated_trash_list_omits_file_manifest(self) -> None:
        hidden = {
            "trash_id": "b" * 32,
            "kind": "group",
            "group_id": "11",
            "image_ids": ["img-1"],
            "created_at": "2026-08-13T00:00:00",
            "file_count": 2,
            "files": [{"name": "secret.png", "sha256": "abc"}],
        }
        with patch("routes.nai.list_deleted", return_value=[hidden]):
            response = self.client.get("/api/generated/trash")
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["trash_id"], "b" * 32)
        self.assertNotIn("files", item)

    def test_failed_generation_items_can_be_retried_by_stable_task_id(self) -> None:
        retried = {"ok": True, "task_id": "job-2", "retry_of": "job-1"}
        with patch("routes.char_swap.retry_batch", return_value=retried) as retry:
            response = self.client.post("/api/plugin/char-swap/batch/retry?task_id=job-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), retried)
        retry.assert_called_once_with("job-1")

    def test_retry_route_runs_inside_the_asyncio_event_loop(self) -> None:
        def retry_from_running_loop(task_id: str) -> dict:
            asyncio.get_running_loop()
            return {"ok": True, "task_id": "job-2", "retry_of": task_id}

        with patch("routes.char_swap.retry_batch", side_effect=retry_from_running_loop):
            response = self.client.post("/api/plugin/char-swap/batch/retry?task_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["retry_of"], "job-1")

    def test_waiting_generation_task_can_be_reordered(self) -> None:
        result = {"ok": True, "task_id": "job-2", "queue_position": 1}
        with patch("routes.char_swap.reorder_batch", return_value=result) as reorder:
            response = self.client.post(
                "/api/plugin/char-swap/batch/reorder",
                json={"task_id": "job-2", "position": 0},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        reorder.assert_called_once_with("job-2", 0)

    def test_nai_status_reuses_short_subscription_snapshot_until_forced_refresh(self) -> None:
        base = {
            "has_token": True,
            "updated_at": "2026-07-27T01:00:00",
            "tokens": [{"id": "nai-1", "enabled": True}],
        }
        with patch("routes.nai.token_status", return_value=base), patch(
            "routes.nai.get_subscription",
            return_value={"ok": True, "tier": 3, "anlas_total": 5866},
        ) as subscription, patch(
            "routes.nai.queue_status",
            return_value={"status": "idle"},
        ), patch(
            "routes.nai.list_generation_slots",
            return_value=[],
        ):
            import routes.nai

            routes.nai._clear_subscription_cache()
            first = self.client.get("/api/nai/status")
            second = self.client.get("/api/nai/status")
            refreshed = self.client.get("/api/nai/status?refresh=true")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(subscription.call_count, 2)


if __name__ == "__main__":
    unittest.main()
