from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import nai_batch
from generation_jobs import GenerationJobManager, JobAlreadyRunning, JobPersistenceError


class GenerationJobManagerTests(unittest.IsolatedAsyncioTestCase):
    def test_queued_jobs_can_be_reordered_and_cancelled_without_touching_active(self) -> None:
        manager = GenerationJobManager()
        active, starts_now = manager.enqueue_job(total=1, generate=False, preview_only=True)
        second, second_starts = manager.enqueue_job(total=1, generate=False, preview_only=True)
        third, third_starts = manager.enqueue_job(total=1, generate=False, preview_only=True)

        self.assertTrue(starts_now)
        self.assertFalse(second_starts)
        self.assertFalse(third_starts)
        self.assertEqual([row["task_id"] for row in manager.queue_status()["pending"]], [second.task_id, third.task_id])

        moved = manager.reorder_queued(third.task_id, 0)
        self.assertEqual(moved["queue_position"], 1)
        self.assertEqual([row["task_id"] for row in manager.queue_status()["pending"]], [third.task_id, second.task_id])

        manager.request_cancel(second.task_id)
        self.assertEqual(manager.status(second.task_id)["status"], "cancelled")
        self.assertEqual(manager.status(active.task_id)["status"], "running")
        self.assertEqual([row["task_id"] for row in manager.queue_status()["pending"]], [third.task_id])

    def test_progress_updates_are_memory_only_until_a_durable_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = GenerationJobManager(
                state_path=Path(temp) / "generation_jobs.json",
            )
            job = manager.start_job(total=1, generate=True, preview_only=False)
            with patch.object(
                manager,
                "_persist_locked",
                wraps=manager._persist_locked,
            ) as persist:
                manager.update_progress(
                    job,
                    current_phase="generate",
                    message="waiting for provider",
                )
                self.assertEqual(persist.call_count, 0)
                self.assertEqual(manager.status(job.task_id)["current_phase"], "generate")

                manager.append_item(
                    job,
                    {"work_id": 1, "ok": True},
                    count_done=True,
                )
                self.assertEqual(persist.call_count, 1)

    def test_snapshot_derives_historical_cooldowns_as_unattempted(self) -> None:
        manager = GenerationJobManager()
        job = manager.start_job(total=3, generate=True, preview_only=False)
        manager.increment(job, "ok_count")
        manager.increment(job, "fail_count", 2)
        manager.append_item(
            job,
            {"target_index": 0, "work_id": 501, "ok": True},
            count_done=True,
        )
        manager.append_item(
            job,
            {
                "target_index": 1,
                "work_id": 501,
                "ok": False,
                "error": "cooldown",
                "request_attempted": True,
            },
            count_done=True,
        )
        manager.append_item(
            job,
            {
                "target_index": 2,
                "work_id": 501,
                "ok": False,
                "error": "provider_unavailable",
                "request_attempted": True,
            },
            count_done=True,
        )
        manager.finish(job, status="done", message="done")

        status = manager.status(job.task_id)
        self.assertEqual(status["fail_count"], 2)
        self.assertEqual(status["deferred_unattempted_count"], 1)
        self.assertEqual(status["effective_fail_count"], 1)

    def test_paid_job_is_not_started_when_initial_state_cannot_be_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = GenerationJobManager(state_path=Path(temp) / "generation_jobs.json")
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(JobPersistenceError):
                    manager.start_job(total=1, generate=True, preview_only=False)

        self.assertEqual(manager.status()["status"], "idle")

    def test_completed_job_survives_manager_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "generation_jobs.json"
            first_manager = GenerationJobManager(state_path=state_path)
            job = first_manager.start_job(total=2, generate=True, preview_only=False)
            first_manager.append_item(
                job,
                {"work_id": 501, "status": "ok", "output": "generated/501.png"},
                count_done=True,
            )
            first_manager.finish(job, status="done", message="2 张图片已生成")

            restored = GenerationJobManager(state_path=state_path).status(job.task_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored["status"], "done")
        self.assertTrue(restored["terminal"])
        self.assertEqual(restored["items"][0]["work_id"], 501)

    def test_running_job_becomes_unknown_after_restart_without_blocking_a_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "generation_jobs.json"
            first_manager = GenerationJobManager(state_path=state_path)
            abandoned = first_manager.start_job(total=4, generate=True, preview_only=False)
            first_manager.update(
                abandoned,
                done=1,
                current_work_id=502,
                current_phase="generating",
            )

            restarted_manager = GenerationJobManager(state_path=state_path)
            recovered = restarted_manager.status(abandoned.task_id)
            successor = restarted_manager.start_job(total=1, generate=False, preview_only=True)

        self.assertEqual(recovered["status"], "unknown")
        self.assertTrue(recovered["terminal"])
        self.assertTrue(recovered["recovered_after_restart"])
        self.assertIn("可能已扣费", recovered["message"])
        self.assertEqual(successor.state["status"], "running")

    def test_start_is_atomic_across_threads(self) -> None:
        manager = GenerationJobManager()
        ready = threading.Barrier(3)

        def attempt_start() -> tuple[str, str]:
            ready.wait()
            try:
                job = manager.start_job(total=1, generate=True, preview_only=False)
            except JobAlreadyRunning as exc:
                return "busy", str(exc.status["task_id"])
            return "started", job.task_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt_start) for _ in range(2)]
            ready.wait()
            results = [future.result(timeout=1) for future in futures]

        self.assertEqual(sorted(result for result, _ in results), ["busy", "started"])
        self.assertEqual(len({task_id for _, task_id in results}), 1)
        self.assertEqual(manager.status()["status"], "running")

    async def test_long_wait_is_interrupted_by_targeted_cancel(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=1, generate=True, preview_only=False)

        started = time.perf_counter()
        waiter = asyncio.create_task(manager.wait_or_cancel(job, 30.0))
        await asyncio.sleep(0.02)
        cancelled = manager.request_cancel(job.task_id)

        self.assertIsNotNone(cancelled)
        self.assertTrue(await asyncio.wait_for(waiter, timeout=0.3))
        self.assertLess(time.perf_counter() - started, 0.3)

    def test_ids_keep_job_ownership_separate(self) -> None:
        manager = GenerationJobManager()
        first = manager.start_job(total=1, generate=True, preview_only=False)
        manager.request_cancel(first.task_id)
        manager.finish(first, status="cancelled", message="cancelled")

        second = manager.start_job(total=2, generate=False, preview_only=True)
        manager.request_cancel(first.task_id)

        self.assertNotEqual(first.task_id, second.task_id)
        self.assertIsNot(first.cancel_event, second.cancel_event)
        self.assertFalse(second.cancel_requested)
        self.assertEqual(manager.status(first.task_id)["status"], "cancelled")
        self.assertEqual(manager.status(second.task_id)["status"], "running")
        self.assertEqual(manager.status()["task_id"], second.task_id)


class NaiBatchJobApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_exhaustion_stops_remaining_upstream_requests(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=3, generate=True, preview_only=False)

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        generate = AsyncMock(
            return_value={
                "ok": False,
                "error": "provider_unavailable",
                "failure_reason": "quota_exhausted",
                "message": "NAI API error 402: Not enough Anlas",
            }
        )
        targets = [
            {"work_id": 910 + index, "page_index": 0}
            for index in range(3)
        ]
        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "generate_image", generate),
        ):
            await nai_batch._run_batch(targets, {}, job=job)

        status = manager.status(job.task_id)
        self.assertEqual(generate.await_count, 1)
        self.assertEqual(status["done"], 3)
        self.assertEqual(status["fail_count"], 3)
        self.assertEqual(status["items"][1]["error"], "quota_exhausted")
        self.assertFalse(status["items"][1]["request_attempted"])

    async def test_start_batch_reports_initial_persistence_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = GenerationJobManager(
                state_path=Path(temp) / "generation_jobs.json",
            )
            with (
                patch.object(nai_batch, "_JOB_MANAGER", manager),
                patch.object(nai_batch, "generation_concurrency", return_value=1),
                patch.object(Path, "write_text", side_effect=OSError("disk full")),
            ):
                result = nai_batch.start_batch(
                    [{"work_id": 904, "page_index": 0}],
                    {},
                    generate=True,
                    preview_only=False,
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "persistence_failed")
        self.assertEqual(manager.status()["status"], "idle")

    async def test_resume_queue_reports_persistence_failure_without_raising(self) -> None:
        manager = GenerationJobManager()
        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(
                manager,
                "activate_next",
                side_effect=JobPersistenceError("disk read-only"),
            ),
        ):
            result = nai_batch.resume_batch_queue()

        self.assertFalse(result["ok"])
        self.assertFalse(result["resumed"])
        self.assertEqual(result["error"], "persistence_failed")

    async def test_start_query_and_cancel_by_task_id_interrupts_retry_wait(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        generate_called = asyncio.Event()

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        async def fake_generate(*args, **kwargs):
            generate_called.set()
            return {
                "ok": False,
                "error": "rate_limited",
                "message": "Request too frequent; please retry later",
                "request_attempted": False,
                "retry_safe": True,
            }

        generate_mock = AsyncMock(side_effect=fake_generate)

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "generation_concurrency", return_value=1),
            patch.object(nai_batch, "generation_concurrency_for_batch", return_value=1),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "generate_image", generate_mock),
            patch.object(nai_batch, "_defer_retry_sec", return_value=30.0),
        ):
            result = nai_batch.start_batch(
                [{"work_id": 901, "page_index": 0}],
                {},
                generate=True,
                preview_only=False,
            )
            self.assertTrue(result["ok"])
            task_id = result["task_id"]
            self.assertEqual(result["batch"]["id"], task_id)
            self.assertEqual(result["batch"]["task_id"], task_id)

            await asyncio.wait_for(generate_called.wait(), timeout=0.3)
            cancel_result = nai_batch.cancel_batch(task_id)
            self.assertTrue(cancel_result["ok"])

            for _ in range(50):
                status = nai_batch.batch_status(task_id)
                if status["status"] == "cancelled":
                    break
                await asyncio.sleep(0.01)

            self.assertEqual(status["status"], "cancelled")
            self.assertTrue(status["terminal"])
            self.assertEqual(status["task_id"], task_id)
            self.assertLess(status["done"], status["total"])
            self.assertEqual(generate_mock.await_count, 1)

    async def test_deferred_retry_wait_is_interrupted_by_cancel(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        generate_target = AsyncMock(
            return_value={
                "ok": False,
                "error": "rate_limited",
                "message": "Request too frequent; please retry later",
                "request_attempted": False,
                "retry_safe": True,
            }
        )
        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "generation_concurrency", return_value=2),
            patch.object(nai_batch, "generation_concurrency_for_batch", return_value=2),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "_generate_for_target", generate_target),
        ):
            result = nai_batch.start_batch(
                [{"work_id": 902, "page_index": 0}],
                {},
                generate=True,
                preview_only=False,
            )
            task_id = result["task_id"]

            for _ in range(50):
                status = nai_batch.batch_status(task_id)
                if status.get("current_phase") == "defer_retry":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(status["current_phase"], "defer_retry")

            nai_batch.cancel_batch(task_id)
            for _ in range(50):
                status = nai_batch.batch_status(task_id)
                if status["status"] == "cancelled":
                    break
                await asyncio.sleep(0.01)

            self.assertEqual(status["status"], "cancelled")
            self.assertEqual(generate_target.await_count, 1)

    async def test_batch_honors_provider_retry_after(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=1, generate=True, preview_only=False)

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        generate_target = AsyncMock(
            side_effect=[
                {
                    "ok": False,
                    "error": "cooldown",
                    "message": "NAI token pool cooling down; retry in 14.5s",
                    "provider": "novelai",
                    "wait": 14.5,
                    "request_attempted": False,
                },
                {
                    "ok": True,
                    "message": "Image generated",
                    "provider": "novelai",
                    "request_attempted": True,
                },
            ]
        )

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "generation_concurrency_for_batch", return_value=1),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "_generate_for_target", generate_target),
            patch.object(manager, "wait_or_cancel", AsyncMock(return_value=False)) as wait,
        ):
            await nai_batch._run_batch(
                [{"work_id": 905, "page_index": 0}],
                {},
                job=job,
            )

        status = manager.status(job.task_id)
        self.assertEqual(status["ok_count"], 1)
        self.assertEqual(status["fail_count"], 0)
        self.assertGreaterEqual(wait.await_args_list[0].args[1], 14.5)

    async def test_cooldown_before_provider_request_is_not_marked_attempted(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=1, generate=True, preview_only=False)
        cooldown = {
            "ok": False,
            "error": "cooldown",
            "message": "NAI token pool cooling down; retry in 12.0s",
            "provider": "novelai",
            "wait": 12.0,
        }

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "queue_status", return_value={}),
            patch.object(nai_batch, "generate_image", AsyncMock(return_value=cooldown)),
        ):
            result = await nai_batch._generate_for_target(
                {"prompt": "test"},
                907,
                force_free=True,
                job=job,
            )

        self.assertFalse(result["request_attempted"])

    async def test_transient_failures_are_not_terminal_after_three_cycles(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=1, generate=True, preview_only=False)

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        transient = {
            "ok": False,
            "error": "rate_limited",
            "message": "Request too frequent; please retry later",
            "provider": "novelai",
            "request_attempted": False,
            "retry_safe": True,
        }
        generate_target = AsyncMock(
            side_effect=[
                dict(transient),
                dict(transient),
                dict(transient),
                {
                    "ok": True,
                    "message": "Image generated",
                    "provider": "novelai",
                    "request_attempted": True,
                },
            ]
        )

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "generation_concurrency_for_batch", return_value=1),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "_generate_for_target", generate_target),
            patch.object(nai_batch, "_defer_retry_sec", return_value=0.001),
            patch.object(manager, "wait_or_cancel", AsyncMock(return_value=False)),
        ):
            await nai_batch._run_batch(
                [{"work_id": 906, "page_index": 0}],
                {},
                job=job,
            )

        status = manager.status(job.task_id)
        self.assertEqual(generate_target.await_count, 4)
        self.assertEqual(status["done"], 1)
        self.assertEqual(status["ok_count"], 1)
        self.assertEqual(status["fail_count"], 0)

    async def test_http_500_is_not_automatically_retried(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=1, generate=True, preview_only=False)

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        generate_target = AsyncMock(
            return_value={
                "ok": False,
                "error": "http_5xx",
                "message": "NAI API error 500: upstream",
                "provider": "novelai",
                "request_attempted": True,
                "retry_safe": False,
                "billing_uncertain": True,
            }
        )
        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "generation_concurrency_for_batch", return_value=1),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
            patch.object(nai_batch, "_generate_for_target", generate_target),
        ):
            await nai_batch._run_batch(
                [{"work_id": 908, "page_index": 0}],
                {},
                job=job,
            )

        status = manager.status(job.task_id)
        self.assertEqual(generate_target.await_count, 1)
        self.assertEqual(status["fail_count"], 1)
        self.assertEqual(status["items"][0]["error"], "http_5xx")

    def test_studio_generate_four_copies_is_one_job(self) -> None:
        captured: dict[str, object] = {}

        def fake_start_batch(targets, recipe, **kwargs):
            captured["targets"] = list(targets)
            captured["recipe"] = dict(recipe)
            captured["kwargs"] = kwargs
            return {"ok": True, "task_id": "studio-job-1", "queued": False}

        with patch.object(nai_batch, "start_batch", side_effect=fake_start_batch):
            result = nai_batch.start_studio_generate(
                {"prompt": "frozen", "seed": 11},
                work_id=42,
                page_index=1,
                copies=4,
                source_gallery_id="site",
                seed_policy="increment",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["task_id"], "studio-job-1")
        self.assertEqual(len(captured["targets"]), 4)
        self.assertEqual(captured["recipe"]["retry_policy"], "no-5xx-retry")
        self.assertEqual(captured["recipe"]["copies"], 4)
        self.assertEqual(captured["targets"][0]["patched_comment"]["seed"], 11)
        self.assertEqual(captured["targets"][3]["patched_comment"]["seed"], 14)

    async def test_multiple_batches_run_in_reordered_fifo_sequence(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        execution_order: list[int] = []

        def fake_prepare(work_id, page_index, recipe, patched_comment=None):
            execution_order.append(work_id)
            return {
                "ok": True,
                "patched_comment": {"prompt": f"work {work_id}"},
                "summary": f"work {work_id}",
                "style_replacements": 0,
            }

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch, "prepare_work_draft", side_effect=fake_prepare),
        ):
            first = nai_batch.start_batch(
                [{"work_id": 1, "page_index": 0}],
                {},
                generate=False,
                preview_only=True,
            )
            second = nai_batch.start_batch(
                [{"work_id": 2, "page_index": 0}],
                {},
                generate=False,
                preview_only=True,
            )
            third = nai_batch.start_batch(
                [{"work_id": 3, "page_index": 0}],
                {},
                generate=False,
                preview_only=True,
            )

            self.assertTrue(second["queued"])
            self.assertTrue(third["queued"])
            moved = nai_batch.reorder_batch(third["task_id"], 0)
            self.assertTrue(moved["ok"])

            for _ in range(100):
                statuses = [
                    nai_batch.batch_status(item["task_id"])["status"]
                    for item in (first, second, third)
                ]
                if statuses == ["done", "done", "done"]:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual(statuses, ["done", "done", "done"])
        self.assertEqual(execution_order, [1, 3, 2])

    async def test_legacy_no_arg_status_and_cancel_target_the_active_job(self) -> None:
        manager = GenerationJobManager(cancel_poll_interval=0.01)
        job = manager.start_job(total=3, generate=True, preview_only=False)

        with patch.object(nai_batch, "_JOB_MANAGER", manager):
            status = nai_batch.batch_status()
            result = nai_batch.cancel_batch()

        self.assertEqual(status["id"], job.task_id)
        self.assertEqual(result["batch"]["task_id"], job.task_id)
        self.assertTrue(job.cancel_requested)
        self.assertTrue(
            {
                "id",
                "status",
                "message",
                "total",
                "done",
                "ok_count",
                "fail_count",
                "skip_count",
                "items",
            }.issubset(status)
        )

    async def test_task_creation_failure_releases_active_slot(self) -> None:
        manager = GenerationJobManager()

        with (
            patch.object(nai_batch, "_JOB_MANAGER", manager),
            patch.object(nai_batch.asyncio, "create_task", side_effect=RuntimeError("loop closed")),
        ):
            result = nai_batch.start_batch(
                [{"work_id": 903, "page_index": 0}],
                {},
                generate=False,
                preview_only=True,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "start_failed")
        self.assertEqual(manager.status(result["task_id"])["status"], "error")
        successor = manager.start_job(total=1, generate=False, preview_only=True)
        self.assertEqual(manager.status()["task_id"], successor.task_id)

    async def test_unknown_task_id_does_not_cancel_current_job(self) -> None:
        manager = GenerationJobManager()
        job = manager.start_job(total=1, generate=False, preview_only=True)

        with patch.object(nai_batch, "_JOB_MANAGER", manager):
            result = nai_batch.cancel_batch("missing-task")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")
        self.assertFalse(job.cancel_requested)

    async def test_retry_failed_batch_reuses_only_failed_and_unfinished_targets(self) -> None:
        manager = GenerationJobManager()
        job = manager.start_job(total=3, generate=True, preview_only=False)
        targets = [
            {"work_id": 701, "page_index": 0, "_target_index": 0},
            {"work_id": 702, "page_index": 0, "_target_index": 1},
            {"work_id": 703, "page_index": 0, "_target_index": 2},
        ]
        manager.update(
            job,
            _request={
                "targets": targets,
                "recipe": {"prompt_profile": "native"},
                "force_free": True,
                "generate": True,
                "preview_only": False,
            },
        )
        manager.append_item(job, {"target_index": 0, "work_id": 701, "ok": True}, count_done=True)
        manager.append_item(job, {"target_index": 1, "work_id": 702, "ok": False}, count_done=True)
        manager.finish(job, status="done", message="1 failed")

        started = {
            "ok": True,
            "task_id": "successor",
            "batch": {"task_id": "successor", "status": "running"},
        }
        with patch.object(nai_batch, "_JOB_MANAGER", manager), patch.object(
            nai_batch, "start_batch", return_value=started
        ) as start:
            result = nai_batch.retry_batch(job.task_id)

        self.assertTrue(result["ok"])
        retry_targets = start.call_args.args[0]
        self.assertEqual([target["work_id"] for target in retry_targets], [702, 703])
        self.assertEqual(start.call_args.kwargs["_retry_of"], job.task_id)

    async def test_billing_uncertain_target_requires_review_instead_of_retry(self) -> None:
        manager = GenerationJobManager()
        job = manager.start_job(total=1, generate=True, preview_only=False)
        manager.update(
            job,
            _request={
                "targets": [{"work_id": 801, "page_index": 0, "_target_index": 0}],
                "recipe": {},
                "generate": True,
                "preview_only": False,
            },
        )
        manager.append_item(
            job,
            {
                "target_index": 0,
                "work_id": 801,
                "ok": False,
                "error": "billing_uncertain",
                "billing_uncertain": True,
                "retry_safe": False,
                "request_attempted": True,
            },
            count_done=True,
        )
        manager.finish(job, status="done", message="needs review")

        status = manager.status(job.task_id)
        with patch.object(nai_batch, "_JOB_MANAGER", manager), patch.object(
            nai_batch, "start_batch"
        ) as start:
            result = nai_batch.retry_batch(job.task_id)

        self.assertTrue(status["needs_review"])
        self.assertEqual(status["blocked_retry_count"], 1)
        self.assertFalse(status["can_retry"])
        self.assertEqual(result["error"], "needs_review")
        start.assert_not_called()

    async def test_unknown_job_with_missing_item_cannot_be_retried(self) -> None:
        manager = GenerationJobManager()
        job = manager.start_job(total=2, generate=True, preview_only=False)
        manager.update(
            job,
            _request={
                "targets": [
                    {"work_id": 901, "page_index": 0, "_target_index": 0},
                    {"work_id": 902, "page_index": 0, "_target_index": 1},
                ],
                "recipe": {},
                "generate": True,
                "preview_only": False,
            },
        )
        manager.finish(job, status="unknown", message="crash before append")

        status = manager.status(job.task_id)
        with patch.object(nai_batch, "_JOB_MANAGER", manager), patch.object(
            nai_batch, "start_batch"
        ) as start:
            result = nai_batch.retry_batch(job.task_id)

        self.assertTrue(status["needs_review"])
        self.assertGreaterEqual(status["blocked_retry_count"], 2)
        self.assertFalse(status["can_retry"])
        self.assertEqual(result["error"], "needs_review")
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
