from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowPagesUiTests(unittest.TestCase):
    def test_studio_exposes_one_ordered_source_prompt_generate_path(self) -> None:
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        workflow = re.search(
            r'<nav[^>]+class="workflow-steps"[^>]+aria-label="生图步骤"[^>]*>'
            r"(?P<body>.*?)</nav>",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(workflow)
        body = workflow.group("body")
        expected = (
            ('href="#studioAssetStep"', "1", "选择来源"),
            ('href="#studioPromptStep"', "2", "编辑咒语"),
            ('href="#studioGenerateStep"', "3", "检查并生成"),
        )
        cursor = -1
        for href, number, label in expected:
            with self.subTest(label=label):
                position = body.index(href)
                self.assertGreater(position, cursor)
                cursor = position
                self.assertIn(f">{number}<", body)
                self.assertIn(label, body)

    def test_studio_has_one_optimization_action_driven_by_the_mode_select(self) -> None:
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")

        self.assertIn('id="studioOptimizeMode"', html)
        self.assertIn('id="studioOptimize"', html)
        self.assertIn("应用所选优化", html)
        self.assertIn("生成库 ↗", html)
        self.assertNotIn("图库 ↗", html)
        for duplicate_id in (
            "studioReOptimize",
            "studioSanitize",
            "studioAnimaV2",
        ):
            with self.subTest(duplicate_id=duplicate_id):
                self.assertNotIn(f'id="{duplicate_id}"', html)
        self.assertIn(
            '$("studioOptimize")?.addEventListener("click", () => '
            "onOptimize(currentOptimizeMode()))",
            script,
        )

    def test_studio_keeps_optional_queue_and_references_out_of_the_primary_path(self) -> None:
        html = (ROOT / "web" / "studio.html").read_text(encoding="utf-8")
        self.assertIn('/assets/workflow-pages.css', html)
        for disclosure_id, label in (
            ("studioQueueDisclosure", "从待生成队列导入"),
            ("studioReferenceDisclosure", "添加参考图（可选）"),
        ):
            with self.subTest(disclosure_id=disclosure_id):
                match = re.search(
                    rf'<details[^>]+id="{disclosure_id}"[^>]*>(?P<body>.*?)</details>',
                    html,
                    re.DOTALL,
                )
                self.assertIsNotNone(match)
                self.assertNotIn(" open", match.group(0).split(">", 1)[0])
                self.assertIn(f"<summary>{label}</summary>", match.group("body"))
        self.assertIn('id="studioResumeBanner"', html)
        self.assertIn('id="studioRetryFailed"', html)
        script = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
        self.assertIn("jobCancelledByRestart", script)
        self.assertIn("不按张扣付费 Anlas", script)
        self.assertIn("不按张扣付费 Anlas", html)
        self.assertNotIn("按张扣 Anlas。", html)

    def test_remix_empty_state_offers_a_primary_gallery_path_and_secondary_id_path(self) -> None:
        html = (ROOT / "web" / "remix.html").read_text(encoding="utf-8")
        empty = re.search(
            r'<section[^>]+id="remixEmpty"[^>]*>(?P<body>.*?)</section>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(empty)
        body = empty.group("body")
        self.assertIn("选择一件作品开始换角", body)
        self.assertIn('href="/"', body)
        self.assertIn("去图库选择作品", body)
        self.assertIn('id="remixWorkId"', html)
        self.assertIn('type="text"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn("或者，直接输入作品 ID", html)
        self.assertIn('id="remixStatus"', html)
        self.assertIn('role="status"', html)

    def test_generated_page_prioritizes_results_and_a_clear_next_action(self) -> None:
        html = (ROOT / "web" / "generated.html").read_text(encoding="utf-8")
        self.assertIn('/assets/workflow-pages.css', html)
        self.assertIn(
            '<a class="workflow-primary-link" href="/studio">继续生图</a>',
            html,
        )
        operations = re.search(
            r'<details[^>]+id="genOperations"[^>]*>(?P<body>.*?)</details>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(operations)
        self.assertNotIn(" open", operations.group(0).split(">", 1)[0])
        self.assertIn("<summary>后处理与任务状态</summary>", operations.group("body"))
        self.assertIn('id="genQueuePanel"', html)
        self.assertIn('id="genRetryFailedBtn"', html)
        self.assertIn("/api/nai/jobs/retry", html)
        self.assertIn('id="genTrash"', html)
        self.assertIn("不会自动清空或过期", html)
        self.assertIn("/api/generated/trash", html)
        self.assertIn("/api/pipeline/cancel", html)
        self.assertLess(html.index('id="genQueuePanel"'), html.index('id="genOperations"'))
        self.assertIn("生成任务队列", html)
        self.assertIn('<h2 class="gen-results-title">最近生成</h2>', html)

        empty = re.search(
            r'<section[^>]+id="genEmpty"[^>]*>(?P<body>.*?)</section>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(empty)
        self.assertIn("还没有生成结果", empty.group("body"))
        self.assertIn('href="/studio"', empty.group("body"))
        self.assertIn("deferred_unattempted_count", html)
        self.assertIn('["busy", "cooldown"]', html)
        self.assertIn("blocked_retry_count", html)
        self.assertIn("结果/扣费未知，已阻止自动重试", html)
        self.assertIn("打开生图工作台", empty.group("body"))
        self.assertIn('id="openGeneratedFolderBtn"', html)
        self.assertIn('revealGenerated("folder")', html)
        self.assertIn('if (kind !== "folder" && !target)', html)
        self.assertIn("/api/storage/open?target=generated", html)
        self.assertIn('alert("打开文件夹失败")', html)
        self.assertIn("没有可重试的任务", html)
        self.assertIn("data.ok === false", html)


if __name__ == "__main__":
    unittest.main()
