from __future__ import annotations

import unittest

from butler.tooling import InteractiveLoop, ToolExecutor, ToolRegistry, ToolingError, project_legacy_specs


class LoopLimitTests(unittest.TestCase):
    def test_four_round_limit_and_result_changes_next_choice(self) -> None:
        registry = ToolRegistry()
        for spec in project_legacy_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        executor.bind("search_gallery", lambda arguments, context: {"hits": ["a", "b", "c", "d", "e", "f"]})
        executor.bind("inspect_work", lambda arguments, context: {"prompt": "1girl"})
        seen: list[str] = []

        def planner(context, results):
            seen.append(context.agent_id)
            if not results:
                return {"tool": "search_gallery", "arguments": {"q": "arknights"}, "call_id": "c1"}
            if results[-1]["tool_name"] == "search_gallery":
                return {"tool": "inspect_work", "arguments": {"work_id": 1}, "call_id": "c2"}
            return None

        loop = InteractiveLoop(registry, executor, planner)
        out = loop.run(agent_id="tomori")
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["rounds"], 2)
        self.assertEqual([item["tool_name"] for item in out["results"]], ["search_gallery", "inspect_work"])

    def test_fifth_round_is_rejected(self) -> None:
        registry = ToolRegistry()
        for spec in project_legacy_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        executor.bind("search_gallery", lambda arguments, context: {"ok": True})

        def planner(context, results):
            return {"tool": "search_gallery", "arguments": {}, "call_id": f"c{context.round_index}"}

        loop = InteractiveLoop(registry, executor, planner)
        with self.assertRaises(ToolingError) as exc:
            loop.run(agent_id="tomori")
        self.assertEqual(exc.exception.envelope.code, "loop_limit")

    def test_desk_switch_rebuilds_allow_list(self) -> None:
        registry = ToolRegistry()
        for spec in project_legacy_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        executor.bind("search_gallery", lambda arguments, context: {"ok": True})
        agent = {"id": "sakiko"}
        seen_agents: list[str] = []

        def planner(context, results):
            seen_agents.append(context.agent_id)
            if context.agent_id == "sakiko":
                agent["id"] = "tomori"
                return {"tool": "search_gallery", "arguments": {}, "call_id": "c1"}
            return None

        out = InteractiveLoop(registry, executor, planner).run(agent_id=lambda: agent["id"])
        self.assertEqual(seen_agents, ["sakiko", "tomori"])
        self.assertEqual(out["rounds"], 1)

    def test_cost_tool_stops_loop_without_running_handler(self) -> None:
        registry = ToolRegistry()
        for spec in project_legacy_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        called = {"n": 0}

        def forbidden(arguments, context):
            called["n"] += 1
            return {"ok": True}

        executor.bind("generate_image", forbidden)
        executor.bind("search_gallery", lambda arguments, context: {"hits": []})

        def planner(context, results):
            if not results:
                return {"tool": "search_gallery", "arguments": {"q": "arknights"}, "call_id": "c1"}
            return {
                "tool": "generate_image",
                "arguments": {"work_id": 9},
                "call_id": "c2",
                "reason": "user asked to generate",
            }

        out = InteractiveLoop(registry, executor, planner).run(agent_id="tomori")
        self.assertEqual(called["n"], 0)
        self.assertEqual(out["status"], "workflow_requested")
        self.assertEqual(out["rounds"], 2)
        self.assertEqual(out["results"][-1]["workflow_request"]["risk"], "cost")
