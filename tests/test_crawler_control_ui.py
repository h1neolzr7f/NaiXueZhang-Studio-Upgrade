from __future__ import annotations

import unittest
from pathlib import Path


class CrawlerControlUiTests(unittest.TestCase):
    def test_progress_page_exposes_beginner_safe_resume_and_stop_controls(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "web" / "progress.html"
        ).read_text(encoding="utf-8")
        intake_script = (
            Path(__file__).resolve().parents[1] / "web" / "pixiv-intake-control.js"
        ).read_text(encoding="utf-8")

        self.assertNotIn('data-target="site"', source)
        self.assertNotIn('data-target="qqgroup"', source)
        self.assertNotIn('data-target="all"', source)
        self.assertIn('data-target="pixiv"', source)
        self.assertIn("/api/crawler/pixiv/task", intake_script)
        self.assertIn("/api/crawler/pixiv/report", intake_script)
        self.assertIn("从现有断点继续，不清空数据库", source)
        self.assertIn("甩手采集（推荐）", source)
        self.assertIn("/api/crawler/autopilot", source)
        self.assertIn("/api/crawler/report", source)
        self.assertIn("采集交付报告", source)
        self.assertIn('id="pixivResetSearch"', source)
        self.assertIn('id="pixivTaskPresets"', source)
        self.assertIn("reset_search", intake_script)
        self.assertIn("renderPresets", intake_script)


if __name__ == "__main__":
    unittest.main()
