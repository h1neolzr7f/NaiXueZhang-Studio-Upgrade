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

    def test_nai_job_can_be_retried_by_task_id(self) -> None:
        retried = {"ok": True, "task_id": "job-10", "retry_of": "job-9"}
        with patch("routes.nai.retry_batch", return_value=retried) as retry:
            response = self.client.post("/api/nai/jobs/retry?task_id=job-9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), retried)
        retry.assert_called_once_with("job-9")

    def test_nai_job_retry_maps_needs_review(self) -> None:
        blocked = {
            "ok": False,
            "error": "needs_review",
            "message": "provider outcome may already be billable; review the remote gallery before retrying",
            "blocked_retry_count": 1,
        }
        with patch("routes.nai.retry_batch", return_value=blocked):
            response = self.client.post("/api/nai/jobs/retry?task_id=job-9")
        self.assertEqual(response.status_code, 400)
        self.assertIn("billable", response.json()["detail"])

    def test_nai_job_can_be_cancelled_by_task_id(self) -> None:
        stopped = {"ok": True, "message": "cancelled", "batch": {"task_id": "job-9", "status": "cancelled"}}
        with patch("routes.nai.cancel_batch", return_value=stopped) as cancel:
            response = self.client.post("/api/nai/jobs/cancel?task_id=job-9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stopped)
        cancel.assert_called_once_with("job-9")

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

    def test_token_network_route_updates_proxy(self) -> None:
        updated = {"ok": True, "message": "token network updated", "tokens": [{"id": "nai_abc", "has_proxy": True, "proxy": ""}]}
        with patch("routes.nai.update_token_network", return_value=updated) as upd:
            response = self.client.post(
                "/api/nai/token/nai_abc/network",
                json={"proxy": "http://127.0.0.1:7897"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tokens"][0]["has_proxy"], True)
        self.assertEqual(response.json()["tokens"][0]["proxy"], "")
        upd.assert_called_once_with("nai_abc", {"proxy": "http://127.0.0.1:7897"})

    def test_generate_uses_batch_count_when_copies_is_omitted(self) -> None:
        started = {"ok": True, "task_id": "job-copies", "copies": 8, "total": 8}
        with patch("routes.nai.start_studio_generate", return_value=started) as start:
            response = self.client.post(
                "/api/nai/generate",
                json={"patched_comment": {"prompt": "1girl"}, "batch_count": 8},
            )
        self.assertEqual(response.status_code, 200)
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs["copies"], 8)

    def test_generate_prefers_explicit_copies_over_default_batch_count(self) -> None:
        started = {"ok": True, "task_id": "job-copies-4", "copies": 4, "total": 4}
        with patch("routes.nai.start_studio_generate", return_value=started) as start:
            response = self.client.post(
                "/api/nai/generate",
                json={"patched_comment": {"prompt": "1girl"}, "copies": 4, "batch_count": 1},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(start.call_args.kwargs["copies"], 4)

    def test_generate_forwards_page_snapshots(self) -> None:
        started = {"ok": True, "task_id": "job-series", "copies": 1, "total": 3, "page_count": 3}
        pages = [
            {"page_index": 0, "patched_comment": {"prompt": "p0"}},
            {"page_index": 1, "patched_comment": {"prompt": "p1"}},
            {"page_index": 2, "patched_comment": {"prompt": "p2"}},
        ]
        with patch("routes.nai.start_studio_generate", return_value=started) as start:
            response = self.client.post(
                "/api/nai/generate",
                json={
                    "patched_comment": {"prompt": "p0"},
                    "copies": 1,
                    "source_gallery_id": "aitag-online",
                    "pages": pages,
                },
            )
        self.assertEqual(response.status_code, 200)
        snaps = start.call_args.kwargs["page_snapshots"]
        self.assertEqual([item["page_index"] for item in snaps], [0, 1, 2])
        self.assertEqual(snaps[1]["patched_comment"]["prompt"], "p1")

    def test_generate_soft_failures_map_to_http_errors(self) -> None:
        cases = [
            ("empty", 400, "target list is empty"),
            ("too_many_targets", 400, "too many"),
            ("start_failed", 503, "could not start"),
        ]
        for error, status, message in cases:
            with self.subTest(error=error):
                with patch(
                    "routes.nai.start_studio_generate",
                    return_value={"ok": False, "error": error, "message": message},
                ):
                    response = self.client.post(
                        "/api/nai/generate",
                        json={"patched_comment": {"prompt": "1girl"}},
                    )
                self.assertEqual(response.status_code, status)
                self.assertIn(message, response.json()["detail"])

    def test_unknown_token_network_update_maps_to_not_found(self) -> None:
        with patch("routes.nai.update_token_network", side_effect=ValueError("token not found")):
            response = self.client.post(
                "/api/nai/token/missing/network",
                json={"proxy": "http://127.0.0.1:7897"},
            )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
