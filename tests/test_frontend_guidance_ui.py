from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


class FrontendGuidanceUiTests(unittest.TestCase):
    def test_pixiv_publish_guard_rejects_duplicate_until_release(self) -> None:
        result = _run_node(
            """
            const ui = require('./web/shared/pixiv-publish-ui.js');
            const guard = ui.createSubmissionGuard();
            const first = guard.tryAcquire();
            const duplicate = guard.tryAcquire();
            const locked = guard.isLocked();
            guard.release();
            const afterRelease = guard.tryAcquire();
            console.log(JSON.stringify({ first, duplicate, locked, afterRelease }));
            """
        )
        self.assertEqual(
            result,
            {"first": True, "duplicate": False, "locked": True, "afterRelease": True},
        )

    def test_pixiv_exposes_a_six_step_landmark_and_publish_safety_state(self) -> None:
        html = (ROOT / "web" / "pixiv.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "pixiv.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "pixiv.js").read_text(encoding="utf-8")

        self.assertIn('class="px-workflow-steps"', html)
        for step in range(1, 7):
            self.assertIn(f'data-workflow-step="{step}"', html)
            self.assertIn(f'id="pixiv-step-{step}"', html)
        self.assertIn('class="px-publish-checklist"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("publishSubmissionGuard.tryAcquire()", js)
        self.assertIn("publishSubmissionGuard.release()", js)
        self.assertIn(".px-workflow-steps", css)
        self.assertIn("@media (max-width: 480px)", css)

    def test_settings_are_grouped_and_explain_empty_token_and_knowledge_states(self) -> None:
        html = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "settings.css").read_text(encoding="utf-8")
        js = (ROOT / "web" / "settings.js").read_text(encoding="utf-8")

        self.assertIn('class="settings-group-nav"', html)
        for group in ("personal", "services", "insights"):
            self.assertIn(f'data-settings-group="{group}"', html)
        for empty_id in ("tokenEmptyState", "knowledgeEmptyState"):
            self.assertIn(f'id="{empty_id}"', html)
            self.assertIn(f'$("' + empty_id + '")', js)
        self.assertIn(".settings-empty-state", css)
        self.assertIn("@media (max-width: 480px)", css)

    def test_butler_and_director_have_first_screen_start_guides(self) -> None:
        butler_html = (ROOT / "web" / "butler.html").read_text(encoding="utf-8")
        butler_css = (ROOT / "web" / "butler.css").read_text(encoding="utf-8")
        director_html = (ROOT / "web" / "director.html").read_text(encoding="utf-8")
        director_css = (ROOT / "web" / "director.css").read_text(encoding="utf-8")

        self.assertIn('id="butlerStartGuide"', butler_html)
        self.assertIn("先选一个目标", butler_html)
        self.assertIn("只填入，不会立即执行", butler_html)
        self.assertIn(".butler-start-guide", butler_css)

        self.assertIn('id="directorStartGuide"', director_html)
        self.assertIn("从这里开始", director_html)
        self.assertIn("预检不扣费", director_html)
        self.assertIn(".director-start-guide", director_css)


if __name__ == "__main__":
    unittest.main()
