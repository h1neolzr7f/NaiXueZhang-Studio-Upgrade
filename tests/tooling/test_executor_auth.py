from __future__ import annotations

import unittest

from butler.tooling import ToolContext, ToolExecutor, ToolRegistry, ToolSpec, project_legacy_specs


class ExecutorAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        for spec in project_legacy_specs():
            self.registry.register(spec)
        self.executor = ToolExecutor(self.registry)
        self.executor.bind("search_gallery", lambda arguments, context: {"hits": [arguments.get("q", "")]})

    def test_empty_agent_is_fail_closed(self) -> None:
        with self.assertRaises(Exception):
            ToolContext.build(self.registry, agent_id="", source="chat", round_index=1)

    def test_sakiko_cannot_use_tomori_draft_tool(self) -> None:
        context = ToolContext.build(self.registry, agent_id="sakiko", source="chat", round_index=1)
        result = self.executor.execute(name="prepare_studio", arguments={}, context=context)
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["error"]["code"], "permission_denied")

    def test_schema_rejects_missing_required_field(self) -> None:
        self.registry.register(
            ToolSpec(
                name="inspect_named",
                version="1",
                description="x",
                risk="read",
                allowed_agents=("shared",),
                input_schema={"type": "object", "required": ["work_id"], "additionalProperties": False, "properties": {"work_id": {"type": "integer"}}},
            )
        )
        self.executor.bind("inspect_named", lambda arguments, context: arguments)
        context = ToolContext.build(self.registry, agent_id="tomori", source="chat", round_index=1)
        result = self.executor.execute(name="inspect_named", arguments={}, context=context)
        self.assertEqual(result["error"]["code"], "schema_invalid")

    def test_redacts_tokens_and_truncates(self) -> None:
        self.registry.register(
            ToolSpec(
                name="inspect_logs",
                version="1",
                description="logs",
                risk="read",
                allowed_agents=("shared",),
                result_size_limit=20,
            )
        )
        self.executor.bind("inspect_logs", lambda arguments, context: {"text": "sk-abcdefghijklmnopqrstuvwxyz " * 20})
        context = ToolContext.build(self.registry, agent_id="sakiko", source="chat", round_index=1)
        result = self.executor.execute(name="inspect_logs", arguments={}, context=context)
        self.assertTrue(result["truncated"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", str(result["data"]))
