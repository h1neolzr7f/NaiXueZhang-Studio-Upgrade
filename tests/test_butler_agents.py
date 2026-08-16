from __future__ import annotations

import unittest
from unittest.mock import patch

from butler.agents import (
    SAKIKO_TOOLS,
    TOMORI_TOOLS,
    filter_plan_for_agent,
    normalize_agent,
    public_agents,
    reject_foreign_tool,
    reset_current_agent,
    set_current_agent,
)
from butler.planning import _scoped_planner_prompt
import butler_service


class ButlerAgentTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_current_agent("")

    def test_normalize_agent_aliases(self) -> None:
        self.assertEqual(normalize_agent("客服小祥"), "sakiko")
        self.assertEqual(normalize_agent("丰川祥子"), "sakiko")
        self.assertEqual(normalize_agent("tomori"), "tomori")
        self.assertEqual(normalize_agent("灯"), "tomori")
        self.assertEqual(normalize_agent("凑企鹅"), "tomori")
        self.assertEqual(normalize_agent("助手凑企鹅"), "tomori")
        self.assertEqual(normalize_agent("高松灯"), "tomori")
        self.assertEqual(normalize_agent("unknown"), "")

    def test_public_agents_expose_situational_costumes(self) -> None:
        agents = {item["id"]: item for item in public_agents()}
        self.assertIn("sakiko", agents)
        self.assertIn("tomori", agents)
        self.assertEqual(agents["tomori"]["name"], "助手凑企鹅")
        self.assertEqual(agents["sakiko"]["desk"], "ops")
        self.assertEqual(agents["tomori"]["desk"], "studio")
        self.assertGreaterEqual(len(agents["sakiko"]["costumes"]), 4)
        self.assertGreaterEqual(len(agents["tomori"]["costumes"]), 8)
        self.assertTrue(any(item["id"] == "causal" for item in agents["sakiko"]["costumes"]))
        self.assertTrue(any(item["id"] == "live_default" for item in agents["tomori"]["costumes"]))

    def test_sakiko_prompt_stays_on_maintenance_tools(self) -> None:
        token = set_current_agent("sakiko")
        try:
            prompt = _scoped_planner_prompt("把这几张图批量提取线稿")
        finally:
            reset_current_agent(token)
        self.assertIn("客服小祥", prompt)
        self.assertNotIn("batch_director", prompt)
        self.assertNotIn("generate_image", prompt)
        self.assertLess(len(prompt), len(butler_service.BUTLER_SYSTEM_PROMPT) * 0.9)

    def test_tomori_prompt_stays_on_generation_tools(self) -> None:
        token = set_current_agent("tomori")
        try:
            prompt = _scoped_planner_prompt("启动采集并改一下请求间隔")
        finally:
            reset_current_agent(token)
        self.assertIn("助手凑企鹅", prompt)
        self.assertIn("高松灯", prompt)
        self.assertNotIn("start_crawler", prompt)
        self.assertNotIn("configure_crawler", prompt)
        self.assertNotIn("product_guide", prompt)
        self.assertIn("generate_image", prompt)

    def test_foreign_tools_are_dropped_from_the_plan(self) -> None:
        token = set_current_agent("sakiko")
        try:
            plan = filter_plan_for_agent(
                {
                    "reply": "先出图",
                    "actions": [{"tool": "generate_image", "arguments": {"prompt": "x"}}],
                }
            )
            reason = reject_foreign_tool("generate_image")
        finally:
            reset_current_agent(token)
        self.assertEqual(plan["actions"], [])
        self.assertIn("助手凑企鹅", plan["reply"])
        self.assertIsNotNone(reason)

    def test_persona_tool_sets_do_not_overlap_the_other_desk(self) -> None:
        self.assertIn("audit_gallery", SAKIKO_TOOLS)
        self.assertIn("start_crawler", SAKIKO_TOOLS)
        self.assertIn("product_guide", SAKIKO_TOOLS)
        self.assertIn("rebuild_knowledge_catalog", SAKIKO_TOOLS)
        self.assertIn("generate_image", TOMORI_TOOLS)
        self.assertIn("batch_director", TOMORI_TOOLS)
        self.assertIn("add_to_queue", TOMORI_TOOLS)
        self.assertNotIn("generate_image", SAKIKO_TOOLS)
        self.assertNotIn("add_to_queue", SAKIKO_TOOLS)
        self.assertNotIn("start_crawler", TOMORI_TOOLS)
        self.assertNotIn("product_guide", TOMORI_TOOLS)
        self.assertNotIn("modify_setting", TOMORI_TOOLS)
        shared = SAKIKO_TOOLS & TOMORI_TOOLS
        self.assertTrue(shared <= {
            "search_gallery",
            "inspect_work",
            "inspect_capabilities",
            "inspect_production",
            "list_generated",
            "list_queue",
            "compare_gallery_candidates",
            "gallery_index_preview",
        })

    def test_execute_auto_refuses_foreign_tools(self) -> None:
        token = set_current_agent("sakiko")
        try:
            with self.assertRaisesRegex(ValueError, "助手凑企鹅"):
                butler_service._execute_auto({"tool": "generate_image", "arguments": {"prompt": "x"}})
        finally:
            reset_current_agent(token)

    def test_request_plan_filters_hallucinated_tools_for_the_active_agent(self) -> None:
        token = set_current_agent("sakiko")
        try:
            with patch.object(
                butler_service,
                "chat_json",
                return_value={
                    "reply": "开始生成",
                    "actions": [{"tool": "generate_image", "arguments": {}}],
                },
            ):
                plan = butler_service.request_plan("帮我生成一张图")
        finally:
            reset_current_agent(token)
        self.assertEqual(plan["actions"], [])
        self.assertIn("助手凑企鹅", plan["reply"])


if __name__ == "__main__":
    unittest.main()
