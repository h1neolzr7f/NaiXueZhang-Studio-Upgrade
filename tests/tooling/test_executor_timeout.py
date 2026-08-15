from __future__ import annotations

import time
import unittest

from butler.tooling import ToolContext, ToolExecutor, ToolRegistry, ToolSpec


class ExecutorTimeoutCancelTests(unittest.TestCase):
    def test_timeout_does_not_return_handler_data(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="slow_search",
                version="1",
                description="slow",
                risk="read",
                allowed_agents=("shared",),
                timeout_ms=50,
            )
        )
        executor = ToolExecutor(registry)

        def slow(arguments, context):
            time.sleep(1)
            return {"secret": "should-not-leak"}

        executor.bind("slow_search", slow)
        context = ToolContext.build(registry, agent_id="tomori", source="chat", round_index=1)
        result = executor.execute(name="slow_search", arguments={}, context=context)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["error"]["code"], "timeout")
        self.assertEqual(result["data"], {})

    def test_cancelled_context_is_fail_closed(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="search_gallery",
                version="1",
                description="search",
                risk="read",
                allowed_agents=("shared",),
            )
        )
        executor = ToolExecutor(registry)
        called = {"n": 0}

        def handler(arguments, context):
            called["n"] += 1
            return {"ok": True}

        executor.bind("search_gallery", handler)
        context = ToolContext.build(
            registry, agent_id="tomori", source="chat", round_index=1, cancelled=True
        )
        result = executor.execute(name="search_gallery", arguments={}, context=context)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"]["code"], "cancelled")

    def test_boolean_and_array_schema_types(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="inspect_named",
                version="1",
                description="x",
                risk="read",
                allowed_agents=("shared",),
                input_schema={
                    "type": "object",
                    "required": ["ok", "ids"],
                    "additionalProperties": False,
                    "properties": {"ok": {"type": "boolean"}, "ids": {"type": "array"}},
                },
            )
        )
        executor = ToolExecutor(registry)
        executor.bind("inspect_named", lambda arguments, context: arguments)
        context = ToolContext.build(registry, agent_id="tomori", source="chat", round_index=1)
        bad = executor.execute(
            name="inspect_named", arguments={"ok": "yes", "ids": []}, context=context
        )
        self.assertEqual(bad["error"]["code"], "schema_invalid")
        good = executor.execute(
            name="inspect_named", arguments={"ok": True, "ids": [1]}, context=context
        )
        self.assertEqual(good["status"], "succeeded")
