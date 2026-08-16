from __future__ import annotations

import unittest

from butler.tooling import ToolContext, ToolExecutor, ToolRegistry, project_legacy_specs


class WorkflowRequestTests(unittest.TestCase):
    def test_cost_tool_does_not_run_handler(self) -> None:
        registry = ToolRegistry()
        for spec in project_legacy_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        called = {"n": 0}

        def forbidden(arguments, context):
            called["n"] += 1
            return {"ok": True}

        executor.bind("generate_image", forbidden)
        context = ToolContext.build(registry, agent_id="tomori", source="chat", round_index=1)
        result = executor.execute(
            name="generate_image",
            arguments={"work_id": 7},
            context=context,
            reason="user asked to regenerate",
        )
        self.assertEqual(called["n"], 0)
        self.assertEqual(result["status"], "workflow_requested")
        request = result["workflow_request"]
        self.assertTrue(request["requires_confirmation"])
        self.assertEqual(request["risk"], "cost")
        self.assertEqual(request["estimated_cost"]["anlas_estimate"], "unknown")
        self.assertEqual(request["proposed_tool"], "generate_image")
