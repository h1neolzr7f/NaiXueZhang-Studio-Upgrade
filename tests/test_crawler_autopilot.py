from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import crawler_task
import crawler_watchdog
from routes import crawler as crawler_routes
from api_schemas import CrawlerControlRequest


class CrawlerAutopilotTests(unittest.TestCase):
    def test_balanced_profile_keeps_conservative_start_and_allows_adaptive_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "search_query": "-NAI_X NAI",
                        "search_sort": "new",
                        "search_time_range": "all",
                        "search_max_pages": 0,
                        "crawler_phase": "all",
                        "dataset_name": "fixture",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(crawler_task, "CONFIG_PATH", config_path):
                result = crawler_task.apply_performance_profile("balanced")

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["concurrent_workers"], 2)
            self.assertEqual(saved["max_concurrent_workers"], 4)
            self.assertEqual(saved["parallel_max_detail_workers"], 3)
            self.assertGreaterEqual(saved["adaptive_growth_clean_batches"], 2)
            self.assertLess(saved["min_request_delay_sec"], saved["request_delay_sec"])
            self.assertTrue(result["adaptive"])

    def test_count_sort_is_valid_for_beginner_task_form(self) -> None:
        base = {
            "search_query": "-NAI_X NAI",
            "search_sort": "new",
            "search_time_range": "all",
            "search_max_pages": 0,
            "search_batch_pages": 8,
            "search_stop_after_known_pages": 0,
            "crawler_phase": "all",
            "dataset_name": "fixture",
        }
        task = crawler_task._normalize_task({"search_sort": "count"}, base=base)
        self.assertEqual(task["search_sort"], "count")

    def test_autopilot_saves_and_starts_pixiv_direct_intake(self) -> None:
        current = {
            "enabled": False,
            "scopes": [{"id": "novelai", "type": "search", "query": "NovelAI"}],
            "max_pages_per_run": 3,
        }
        with patch.object(
            crawler_routes,
            "load_pixiv_task",
            return_value=current,
        ), patch.object(
            crawler_routes,
            "save_pixiv_task",
            side_effect=lambda task, **_: task,
        ) as save, patch.object(
            crawler_routes,
            "start_crawler_target",
            return_value={"pixiv": {"mode": "watch"}},
        ) as start, patch.object(
            crawler_routes,
            "get_pixiv_report",
            return_value={"status": "idle"},
        ), patch.object(
            crawler_routes,
            "multi_crawler_status",
            return_value={"pixiv": {"running": True}},
        ):
            result = crawler_routes.api_crawler_autopilot(
                CrawlerControlRequest(
                    task={"search_query": "-NAI_X NAI"},
                    target="pixiv",
                )
            )

        self.assertTrue(result["ok"])
        self.assertTrue(save.call_args.args[0]["enabled"])
        start.assert_called_once_with("pixiv", watch=True)

    def test_delivery_report_distinguishes_passed_and_exhausted_completion(self) -> None:
        completed = {
            "works": 100,
            "details": 100,
            "covers": 100,
            "detail_pending": 0,
            "preview_pending": 0,
            "preview_exhausted": 0,
            "work_remaining": False,
            "search_done": True,
            "completion_state": "completed",
        }
        with patch.object(crawler_watchdog, "crawl_work_snapshot", return_value=completed):
            passed = crawler_watchdog.crawler_delivery_report()
        self.assertEqual(passed["verdict"], "passed")
        self.assertTrue(passed["quality"]["passed"])

        with patch.object(
            crawler_watchdog,
            "crawl_work_snapshot",
            return_value={**completed, "covers": 97, "preview_exhausted": 3},
        ):
            attention = crawler_watchdog.crawler_delivery_report()
        self.assertEqual(attention["verdict"], "needs_attention")
        self.assertFalse(attention["quality"]["passed"])


if __name__ == "__main__":
    unittest.main()
