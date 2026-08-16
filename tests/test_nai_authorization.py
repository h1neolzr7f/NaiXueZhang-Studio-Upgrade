from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from nai_authorization import (
    ACTION_STUDIO,
    AuthorizationError,
    authorize_start_batch,
    compile_batch_authorization,
    consume_ticket,
    issue_for_preview,
    reset_authorization_state_for_tests,
)
from nai_batch import start_batch, start_studio_generate
from nai_char_modules import generation


class PaidAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_authorization_state_for_tests()

    def _paid_comment(self) -> dict:
        return {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "action": "img2img",
            "image": "aGVsbG8=",
        }

    def _free_comment(self) -> dict:
        return {"prompt": "1girl", "width": 832, "height": 1216, "steps": 23}

    def test_free_eligible_does_not_require_ticket(self) -> None:
        preview = compile_batch_authorization(
            [{"patched_comment": self._free_comment()}],
            {"copies": 1},
            force_free=True,
            action=ACTION_STUDIO,
        )
        self.assertTrue(preview["free_eligible"])
        self.assertFalse(preview["requires_ticket"])

    def test_image_input_is_not_free_even_with_force_free(self) -> None:
        compiled = generation.build_generate_payload(self._paid_comment(), force_free=True)
        self.assertFalse(compiled["free_eligible"])
        preview = compile_batch_authorization(
            [{"patched_comment": self._paid_comment()}],
            {"copies": 2, "kind": "studio_snapshot"},
            force_free=True,
            action=ACTION_STUDIO,
            copies=2,
        )
        self.assertTrue(preview["requires_ticket"])

    def test_missing_ticket_is_rejected_before_enqueue(self) -> None:
        result = start_studio_generate(self._paid_comment(), copies=1, force_free=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ticket_invalid")
        self.assertFalse(result.get("request_attempted"))

    def test_ticket_replay_and_hash_mismatch_and_expiry(self) -> None:
        preview = compile_batch_authorization(
            [{"patched_comment": self._paid_comment(), "work_id": 1}],
            {"copies": 1},
            force_free=True,
            action=ACTION_STUDIO,
        )
        issued = issue_for_preview(preview)
        consume_ticket(issued["ticket"], preview)
        with self.assertRaises(AuthorizationError) as replay:
            consume_ticket(issued["ticket"], preview)
        self.assertEqual(replay.exception.error_code, "ticket_replay")

        other = compile_batch_authorization(
            [{"patched_comment": {**self._paid_comment(), "steps": 20}, "work_id": 1}],
            {"copies": 1},
            force_free=True,
            action=ACTION_STUDIO,
        )
        fresh = issue_for_preview(preview)
        with self.assertRaises(AuthorizationError) as changed:
            consume_ticket(fresh["ticket"], other)
        self.assertEqual(changed.exception.error_code, "ticket_hash_mismatch")

        expired = issue_for_preview(preview)
        with patch("nai_authorization.time.time", return_value=time.time() + 10_000):
            with self.assertRaises(AuthorizationError) as expired_exc:
                consume_ticket(expired["ticket"], preview)
        self.assertEqual(expired_exc.exception.error_code, "ticket_expired")

    def test_copies_change_invalidates_ticket(self) -> None:
        one = compile_batch_authorization(
            [{"patched_comment": self._paid_comment()}],
            {"copies": 1},
            force_free=True,
            action=ACTION_STUDIO,
            copies=1,
        )
        two = compile_batch_authorization(
            [{"patched_comment": self._paid_comment()}, {"patched_comment": self._paid_comment()}],
            {"copies": 2},
            force_free=True,
            action=ACTION_STUDIO,
            copies=2,
        )
        ticket = issue_for_preview(one)["ticket"]
        with self.assertRaises(AuthorizationError) as exc:
            consume_ticket(ticket, two)
        self.assertEqual(exc.exception.error_code, "ticket_hash_mismatch")

    def test_valid_ticket_allows_start_and_marks_authorized(self) -> None:
        from nai_authorization import issue_for_preview as issue
        from nai_batch import build_studio_targets

        targets, recipe = build_studio_targets(self._paid_comment(), work_id=9, copies=1)
        preview = compile_batch_authorization(
            targets,
            recipe,
            force_free=True,
            action=ACTION_STUDIO,
            copies=1,
        )
        ticket = issue(preview)["ticket"]
        with patch("nai_batch.generation_concurrency_for_batch", return_value=1), patch(
            "nai_batch._launch_job"
        ):
            result = start_studio_generate(
                self._paid_comment(),
                work_id=9,
                copies=1,
                force_free=True,
                authorization_ticket=ticket,
            )
        self.assertTrue(result["ok"], result)

    def test_generate_image_blocks_transport_without_authorization(self) -> None:
        import nai_api

        send = AsyncMock(side_effect=AssertionError("HTTP must not start"))
        with patch.object(nai_api, "_generate_image_with_entry", send):
            result = asyncio.run(nai_api.generate_image(self._paid_comment(), force_free=True))
        self.assertEqual(result["error"], "authorization_required")
        self.assertFalse(result["request_attempted"])
        send.assert_not_called()

    def test_force_free_false_without_comments_still_requires_ticket(self) -> None:
        with self.assertRaises(AuthorizationError) as exc:
            authorize_start_batch(
                [{"work_id": 1}],
                {},
                force_free=False,
                generate=True,
                preview_only=False,
                action="char_swap_batch",
                ticket="",
            )
        self.assertEqual(exc.exception.error_code, "ticket_invalid")

    def test_preview_only_skips_ticket(self) -> None:
        with patch("nai_batch._launch_job"):
            result = start_batch(
                [{"patched_comment": self._paid_comment(), "work_id": 1}],
                {},
                force_free=False,
                generate=True,
                preview_only=True,
            )
        self.assertTrue(result["ok"], result)

    def test_caller_paid_authorized_flag_cannot_bypass_ticket(self) -> None:
        result = start_batch(
            [{"patched_comment": self._paid_comment(), "work_id": 1}],
            {},
            force_free=True,
            generate=True,
            _paid_authorized=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ticket_invalid")
        self.assertFalse(result.get("request_attempted"))

    def test_fake_retry_of_cannot_reuse_authorization(self) -> None:
        result = start_batch(
            [{"patched_comment": self._paid_comment(), "work_id": 1}],
            {"_payload_hash": "x", "_manifest_hash": "y"},
            force_free=True,
            generate=True,
            _retry_of="missing-job",
            _paid_authorized=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_paid_subset_retry_reuses_frozen_job_authorization(self) -> None:
        from nai_authorization import ACTION_CHAR_SWAP

        comment = self._paid_comment()
        targets = [
            {"patched_comment": comment, "work_id": 1, "page_index": 0, "_target_index": 0},
            {"patched_comment": comment, "work_id": 2, "page_index": 0, "_target_index": 1},
        ]
        preview = compile_batch_authorization(
            targets,
            {},
            force_free=True,
            action=ACTION_CHAR_SWAP,
        )
        ticket = issue_for_preview(preview)["ticket"]
        with patch("nai_batch.generation_concurrency_for_batch", return_value=1), patch(
            "nai_batch._launch_job"
        ):
            started = start_batch(
                targets,
                {},
                force_free=True,
                authorization_ticket=ticket,
                authorization_action=ACTION_CHAR_SWAP,
            )
        self.assertTrue(started["ok"], started)
        from nai_batch import _JOB_MANAGER, retry_batch

        job = _JOB_MANAGER.get_job(started["task_id"])
        self.assertIsNotNone(job)
        _JOB_MANAGER.update(
            job,
            items=[
                {
                    "target_index": 0,
                    "work_id": 1,
                    "ok": False,
                    "error": "busy",
                    "failure_reason": "busy",
                },
                {"target_index": 1, "work_id": 2, "ok": True},
            ],
        )
        _JOB_MANAGER.finish(job, status="error", message="partial")
        with patch("nai_batch.generation_concurrency_for_batch", return_value=1), patch(
            "nai_batch._launch_job"
        ):
            retried = retry_batch(started["task_id"])
        self.assertTrue(retried["ok"], retried)

    def test_retry_rejects_mutated_frozen_target(self) -> None:
        from nai_authorization import ACTION_CHAR_SWAP
        from nai_batch import _JOB_MANAGER, retry_batch

        comment = self._paid_comment()
        targets = [
            {"patched_comment": comment, "work_id": 1, "page_index": 0, "_target_index": 0},
        ]
        preview = compile_batch_authorization(
            targets,
            {},
            force_free=True,
            action=ACTION_CHAR_SWAP,
        )
        ticket = issue_for_preview(preview)["ticket"]
        with patch("nai_batch.generation_concurrency_for_batch", return_value=1), patch(
            "nai_batch._launch_job"
        ):
            started = start_batch(
                targets,
                {},
                force_free=True,
                authorization_ticket=ticket,
                authorization_action=ACTION_CHAR_SWAP,
            )
        self.assertTrue(started["ok"], started)
        job = _JOB_MANAGER.get_job(started["task_id"])
        request = dict(job.state.get("_request") or {})
        mutated = dict((request.get("targets") or [targets[0]])[0])
        mutated["patched_comment"] = {**comment, "steps": 40}
        request["targets"] = [mutated]
        request["target_fingerprints"] = ["not-the-current-fingerprint"]
        _JOB_MANAGER.update(job, _request=request, items=[
            {"target_index": 0, "work_id": 1, "ok": False, "error": "busy", "failure_reason": "busy"},
        ])
        _JOB_MANAGER.finish(job, status="error", message="partial")
        retried = retry_batch(started["task_id"])
        self.assertFalse(retried["ok"])
        self.assertEqual(retried["error"], "ticket_hash_mismatch")

    def test_generate_http_rejects_paid_without_ticket(self) -> None:
        from tests.asgi_client import TestClient

        import server

        client = TestClient(server.app)
        response = client.post(
            "/api/nai/generate",
            json={
                "patched_comment": self._paid_comment(),
                "force_free": True,
            },
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
