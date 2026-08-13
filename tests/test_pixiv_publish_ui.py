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


class PixivPublishUiTests(unittest.TestCase):
    def test_confirmation_summarizes_every_irreversible_publish_field(self) -> None:
        data = _run_node(
            """
            const ui = require('./web/shared/pixiv-publish-ui.js');
            const text = ui.buildConfirmation({
              action: '仅上传',
              account: '主账号 · alice',
              imageCount: 3,
              title: '雨夜',
              tags: ['arknights', 'r18'],
              rating: 'R-18',
              pipeline: '自动补齐：超分 / 强制打码 / 清元数据',
            });
            console.log(JSON.stringify({ text }));
            """
        )
        text = data["text"]
        for expected in (
            "动作：仅上传",
            "账号：主账号 · alice",
            "图片：3 张",
            "标题：雨夜",
            "Tags：arknights / r18",
            "分级：R-18",
            "后处理：自动补齐：超分 / 强制打码 / 清元数据",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_busy_state_locks_both_publish_actions_and_exposes_accessibility_state(self) -> None:
        data = _run_node(
            """
            const ui = require('./web/shared/pixiv-publish-ui.js');
            function button() {
              return {
                disabled: false,
                attrs: {},
                setAttribute(name, value) { this.attrs[name] = value; },
                removeAttribute(name) { delete this.attrs[name]; },
              };
            }
            const launch = button();
            const upload = button();
            ui.setBusy([launch, upload], true);
            const locked = [launch.disabled, upload.disabled, launch.attrs['aria-busy'], upload.attrs['aria-busy']];
            ui.setBusy([launch, upload], false);
            const unlocked = [launch.disabled, upload.disabled, launch.attrs['aria-busy'], upload.attrs['aria-busy']];
            console.log(JSON.stringify({ locked, unlocked }));
            """
        )
        self.assertEqual(data["locked"], [True, True, "true", "true"])
        self.assertEqual(data["unlocked"], [False, False, None, None])

    def test_workbench_integrates_confirmation_module_before_publish_entry(self) -> None:
        html = (ROOT / "web" / "pixiv.html").read_text(encoding="utf-8")
        src = (ROOT / "web" / "pixiv.js").read_text(encoding="utf-8")
        module_ref = "/assets/shared/pixiv-publish-ui.js"
        self.assertIn(module_ref, html)
        self.assertLess(html.index(module_ref), html.index("/assets/pixiv.js"))
        self.assertIn("window.PixivPublishUI.buildConfirmation", src)
        self.assertIn("window.PixivPublishUI.setBusy", src)

    def test_large_local_group_catalog_uses_a_realistic_timeout(self) -> None:
        src = "".join(
            (ROOT / "web" / name).read_text(encoding="utf-8")
            for name in ("pixiv.js", "pixiv-groups.js")
        )
        self.assertIn(
            'window.ApiClient.raw("/api/pixiv/groups", { timeoutMs: 60000 })',
            src,
        )


if __name__ == "__main__":
    unittest.main()
