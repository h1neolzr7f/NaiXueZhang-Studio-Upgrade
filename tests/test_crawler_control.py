from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import crawler_control


class CrawlerControlTests(unittest.TestCase):
    def tearDown(self) -> None:
        crawler_control.invalidate_process_cache()

    def test_process_ownership_requires_exact_absolute_script_path(self) -> None:
        target = crawler_control.CRAWLER_SCRIPT
        self.assertTrue(
            crawler_control._cmdline_owned_by(
                ["python.exe", "-u", str(target), "--phase", "all"],
                target,
            )
        )
        self.assertFalse(
            crawler_control._cmdline_owned_by(
                ["python.exe", str(Path("D:/other/aitag-mirror/crawler.py"))],
                target,
            )
        )
        self.assertFalse(
            crawler_control._cmdline_owned_by(
                ["python.exe", "tool.py", "crawler.py"],
                target,
            )
        )

    def test_process_ownership_is_case_insensitive_on_windows(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows path ownership is case-insensitive")
        target = crawler_control.SUPERVISOR_SCRIPT
        self.assertTrue(
            crawler_control._cmdline_owned_by(
                ["powershell.exe", "-File", str(target).upper()],
                target,
            )
        )

    def test_kill_rejects_reused_pid(self) -> None:
        identity = crawler_control._OwnedProcess(
            pid=4321,
            create_time=100.0,
            script_path=crawler_control.CRAWLER_SCRIPT,
        )
        process = Mock()
        process.create_time.return_value = 101.0
        with patch.object(crawler_control.psutil, "Process", return_value=process):
            stopped = crawler_control._kill_owned_processes([identity])
        self.assertEqual(stopped, [])
        process.kill.assert_not_called()

    def test_kill_revalidates_script_and_confirms_exit(self) -> None:
        identity = crawler_control._OwnedProcess(
            pid=4321,
            create_time=100.0,
            script_path=crawler_control.CRAWLER_SCRIPT,
        )
        process = Mock()
        process.create_time.return_value = 100.0
        process.cmdline.return_value = [
            "python.exe",
            "-u",
            str(crawler_control.CRAWLER_SCRIPT),
        ]
        with patch.object(crawler_control.psutil, "Process", return_value=process):
            stopped = crawler_control._kill_owned_processes([identity])
        self.assertEqual(stopped, [4321])
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)

    def test_generic_start_is_single_flight_when_pixiv_process_exists(self) -> None:
        with patch.object(
            crawler_control, "_list_pixiv_crawler_pids_uncached", return_value=[4321]
        ), patch.object(crawler_control, "_spawn_detached_ps") as spawn:
            result = crawler_control.start_crawler(use_supervisor=False)
        self.assertTrue(result["already_running"])
        self.assertEqual(result["pid"], 4321)
        spawn.assert_not_called()

    def test_qq_start_is_single_flight_when_process_exists(self) -> None:
        with patch.object(crawler_control, "_list_qq_crawler_pids_uncached", return_value=[987]), patch.object(
            crawler_control, "_spawn_detached_ps"
        ) as spawn:
            result = crawler_control.start_qq_crawler(watch=False)
        self.assertTrue(result["already_running"])
        spawn.assert_not_called()

    def test_pixiv_start_is_single_flight_when_process_exists(self) -> None:
        with patch.object(
            crawler_control,
            "_list_pixiv_crawler_pids_uncached",
            return_value=[654],
        ), patch.object(crawler_control, "_spawn_detached_ps") as spawn:
            result = crawler_control.start_pixiv_crawler(watch=False)
        self.assertTrue(result["already_running"])
        self.assertEqual(result["pid"], 654)
        spawn.assert_not_called()

    def test_all_target_starts_only_pixiv_direct_intake(self) -> None:
        with patch.object(
            crawler_control, "start_pixiv_crawler", return_value={"mode": "once"}
        ) as pixiv, patch.object(crawler_control, "start_qq_crawler") as qq, patch.object(
            crawler_control, "_start_legacy_site_crawler"
        ) as legacy:
            result = crawler_control.start_crawler_target("all", watch=False)
        self.assertEqual(result, {"pixiv": {"mode": "once"}})
        pixiv.assert_called_once_with(watch=False)
        qq.assert_not_called()
        legacy.assert_not_called()

    def test_generic_start_is_a_pixiv_compatibility_alias(self) -> None:
        with patch.object(
            crawler_control,
            "start_pixiv_crawler",
            return_value={"mode": "watch", "pid": 42},
        ) as pixiv:
            result = crawler_control.start_crawler(use_supervisor=True)
        self.assertEqual(result["pid"], 42)
        pixiv.assert_called_once_with(watch=True)

    def test_legacy_site_target_is_not_startable(self) -> None:
        with self.assertRaisesRegex(ValueError, "legacy site crawler is disabled"):
            crawler_control.start_crawler_target("site")

    def test_detached_crawler_redirects_output_to_durable_logs(self) -> None:
        process = Mock(pid=4321)
        with patch.object(crawler_control.subprocess, "Popen", return_value=process) as popen:
            pid = crawler_control._spawn_detached_ps(
                file_path="python.exe",
                arg_list=["-u", "crawler_qq.py", "--watch"],
                title="aitag-crawler-qq",
            )

        self.assertEqual(pid, 4321)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["python.exe", "-u", "crawler_qq.py", "--watch"])
        self.assertTrue(kwargs["creationflags"] & crawler_control._CREATE_NO_WINDOW)
        self.assertFalse(kwargs["creationflags"] & crawler_control._DETACHED_PROCESS)
        self.assertTrue(
            kwargs["creationflags"] & crawler_control._CREATE_NEW_PROCESS_GROUP
        )
        self.assertTrue(kwargs["close_fds"])
        self.assertTrue(str(kwargs["stdout"].name).endswith("aitag-crawler-qq.out.log"))
        self.assertTrue(str(kwargs["stderr"].name).endswith("aitag-crawler-qq.err.log"))


if __name__ == "__main__":
    unittest.main()
