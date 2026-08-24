from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from runtime_resources import RuntimeResources


class _LifecycleAdapter:
    def __init__(self, calls: list[str], name: str) -> None:
        self._calls = calls
        self._name = name

    def start(self) -> None:
        self._calls.append(f"{self._name}.start")

    def stop(self) -> None:
        self._calls.append(f"{self._name}.stop")

    def close(self) -> None:
        self._calls.append(f"{self._name}.close")


class _FailingStopAdapter(_LifecycleAdapter):
    def stop(self) -> None:
        super().stop()
        raise RuntimeError(f"{self._name} stop failed")


class _FailingStartAdapter(_LifecycleAdapter):
    def start(self) -> None:
        super().start()
        raise RuntimeError(f"{self._name} start failed")


class _FailOnceStopAdapter(_LifecycleAdapter):
    def __init__(self, calls: list[str], name: str) -> None:
        super().__init__(calls, name)
        self._failed = False

    def stop(self) -> None:
        super().stop()
        if not self._failed:
            self._failed = True
            raise RuntimeError(f"{self._name} stop failed once")


class RuntimeResourcesTests(unittest.TestCase):
    def test_start_is_idempotent(self) -> None:
        calls: list[str] = []
        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_LifecycleAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=lambda: calls.append("scheduler.start"),
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        resources.start()
        resources.start()

        self.assertEqual(calls, ["watchdog.start", "scheduler.start"])

    def test_close_is_idempotent_and_closes_every_resource(self) -> None:
        calls: list[str] = []
        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_LifecycleAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=lambda: calls.append("scheduler.start"),
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        resources.start()
        calls.clear()
        resources.close()
        resources.close()

        self.assertEqual(
            calls,
            ["scheduler.stop", "watchdog.stop", "http.close", "db.close"],
        )

    def test_pixiv_stats_scheduler_can_be_stopped(self) -> None:
        from pixiv_accounts import start_stats_scheduler, stop_stats_scheduler

        refreshed = threading.Event()
        refresh_calls = 0

        def refresh_once(*, force: bool = False) -> None:
            nonlocal refresh_calls
            del force
            refresh_calls += 1
            refreshed.set()

        with (
            patch("pixiv_accounts.refresh_all_stats", side_effect=refresh_once),
            patch(
                "pixiv_accounts._load_accounts_file",
                return_value={"refresh_interval_hours": 6},
            ),
        ):
            start_stats_scheduler()
            self.assertTrue(refreshed.wait(timeout=2))
            stop_stats_scheduler()
            calls_after_stop = refresh_calls
            time.sleep(0.05)

        self.assertEqual(refresh_calls, calls_after_stop)

    def test_close_attempts_every_resource_when_one_fails(self) -> None:
        calls: list[str] = []
        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_FailingStopAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=lambda: calls.append("scheduler.start"),
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        with self.assertRaisesRegex(RuntimeError, "watchdog.stop"):
            resources.close()

        self.assertEqual(
            calls,
            ["scheduler.stop", "watchdog.stop", "http.close", "db.close"],
        )

    def test_start_rolls_back_watchdog_when_scheduler_start_fails(self) -> None:
        calls: list[str] = []

        def fail_scheduler_start() -> None:
            calls.append("scheduler.start")
            raise RuntimeError("scheduler start failed")

        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_LifecycleAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=fail_scheduler_start,
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        with self.assertRaisesRegex(RuntimeError, "scheduler start failed"):
            resources.start()

        self.assertEqual(
            calls,
            ["watchdog.start", "scheduler.start", "scheduler.stop", "watchdog.stop"],
        )

    def test_close_retries_only_resources_that_failed_to_close(self) -> None:
        calls: list[str] = []
        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_FailOnceStopAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=lambda: calls.append("scheduler.start"),
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        with self.assertRaisesRegex(RuntimeError, "watchdog.stop"):
            resources.close()
        resources.close()

        self.assertEqual(
            calls,
            [
                "scheduler.stop",
                "watchdog.stop",
                "http.close",
                "db.close",
                "watchdog.stop",
            ],
        )

    def test_start_after_close_is_rejected(self) -> None:
        calls: list[str] = []
        resources = RuntimeResources(
            db=_LifecycleAdapter(calls, "db"),
            watchdog=_LifecycleAdapter(calls, "watchdog"),
            http_client=_LifecycleAdapter(calls, "http"),
            start_stats_scheduler=lambda: calls.append("scheduler.start"),
            stop_stats_scheduler=lambda: calls.append("scheduler.stop"),
        )

        resources.close()

        with self.assertRaisesRegex(RuntimeError, "already closed"):
            resources.start()


class ServerRuntimeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_uses_runtime_resources(self) -> None:
        import server

        calls: list[str] = []
        runtime = _LifecycleAdapter(calls, "runtime")

        with (
            patch.object(server, "RUNTIME_RESOURCES", runtime),
            patch.object(
                server,
                "_start_generated_maintenance_once",
                side_effect=lambda: calls.append("maintenance.start"),
            ),
        ):
            async with server._lifespan(server.app):
                calls.append("request")

        self.assertEqual(
            calls,
            ["runtime.start", "maintenance.start", "request", "runtime.close"],
        )
        import nai_batch

        self.assertIsNone(nai_batch._EVENT_LOOP)

    async def test_lifespan_closes_runtime_when_maintenance_start_fails(self) -> None:
        import server

        calls: list[str] = []
        runtime = _LifecycleAdapter(calls, "runtime")

        def fail_maintenance() -> None:
            calls.append("maintenance.start")
            raise RuntimeError("maintenance failed")

        with (
            patch.object(server, "RUNTIME_RESOURCES", runtime),
            patch.object(
                server,
                "_start_generated_maintenance_once",
                side_effect=fail_maintenance,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "maintenance failed"):
                async with server._lifespan(server.app):
                    self.fail("lifespan yielded after maintenance failure")

        self.assertEqual(
            calls,
            ["runtime.start", "maintenance.start", "runtime.close"],
        )

    async def test_lifespan_closes_runtime_when_runtime_start_fails(self) -> None:
        import server

        calls: list[str] = []
        runtime = _FailingStartAdapter(calls, "runtime")

        with patch.object(server, "RUNTIME_RESOURCES", runtime):
            with self.assertRaisesRegex(RuntimeError, "runtime start failed"):
                async with server._lifespan(server.app):
                    self.fail("lifespan yielded after runtime start failure")

        self.assertEqual(calls, ["runtime.start", "runtime.close"])


if __name__ == "__main__":
    unittest.main()
