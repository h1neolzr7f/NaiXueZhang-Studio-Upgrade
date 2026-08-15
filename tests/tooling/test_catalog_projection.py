from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from butler.agents import SAKIKO_TOOLS, TOMORI_TOOLS
from butler.tooling import ToolContext, ToolExecutor, ToolRegistry, project_legacy_specs
from butler.tooling.catalog_projection import (
    DESTRUCTIVE_TOOLS,
    PAID_TOOLS,
    WORKFLOW_ONLY_RISKS,
    default_catalog_path,
    project_catalog_risk,
    project_catalog_specs,
    read_catalog,
)


def _catalog_fingerprint(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


class CatalogProjectionTests(unittest.TestCase):
    def test_projects_more_catalog_tools_than_legacy_adapter(self) -> None:
        projected = {spec.name: spec for spec in project_catalog_specs()}
        legacy = {spec.name: spec for spec in project_legacy_specs()}
        self.assertGreater(len(projected), len(legacy))
        self.assertIn("search_character_references", projected)
        self.assertIn("batch_director", projected)
        self.assertIn("inspect_crawler", projected)
        self.assertIn("add_to_queue", projected)
        self.assertNotIn("delete_generated_item", projected)

    def test_does_not_write_catalog(self) -> None:
        path = default_catalog_path()
        before_hash, before_size = _catalog_fingerprint(path)
        before_text = path.read_text(encoding="utf-8")
        specs = project_catalog_specs()
        after_hash, after_size = _catalog_fingerprint(path)
        self.assertTrue(specs)
        self.assertEqual(before_hash, after_hash)
        self.assertEqual(before_size, after_size)
        self.assertEqual(before_text, path.read_text(encoding="utf-8"))
        source = Path(project_catalog_specs.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("write_text", source)
        self.assertNotIn("write_bytes", source)
        self.assertNotIn("unlink(", source)

    def test_in_memory_catalog_does_not_touch_repo_file(self) -> None:
        path = default_catalog_path()
        before_hash, _ = _catalog_fingerprint(path)
        specs = project_catalog_specs(
            {
                "tools": [
                    {
                        "name": "delete_generated_item",
                        "risk": "confirm",
                        "description": "删除成果",
                    }
                ]
            }
        )
        self.assertEqual([spec.name for spec in specs], ["delete_generated_item"])
        self.assertEqual(specs[0].risk, "destructive")
        self.assertFalse(specs[0].interactive_executable)
        self.assertEqual(_catalog_fingerprint(path)[0], before_hash)

    def test_auto_maps_to_read_and_stays_interactive(self) -> None:
        self.assertEqual(project_catalog_risk("inspect_crawler", "auto"), "read")
        self.assertEqual(project_catalog_risk("read_logs", "auto"), "read")
        self.assertEqual(project_catalog_risk("product_guide", "auto"), "read")
        specs = {spec.name: spec for spec in project_catalog_specs()}
        self.assertEqual(specs["inspect_crawler"].risk, "read")
        self.assertTrue(specs["inspect_crawler"].interactive_executable)
        self.assertTrue(specs["prepare_studio"].interactive_executable)
        self.assertTrue(specs["search_gallery"].interactive_executable)

    def test_unknown_catalog_risk_is_fail_closed_to_confirm(self) -> None:
        self.assertEqual(project_catalog_risk("mystery_tool", "shell"), "confirm")
        self.assertEqual(project_catalog_risk("mystery_tool", ""), "confirm")

    def test_paid_and_destructive_overrides(self) -> None:
        self.assertEqual(project_catalog_risk("generate_image", "confirm"), "cost")
        self.assertEqual(project_catalog_risk("batch_generate", "confirm"), "cost")
        self.assertEqual(project_catalog_risk("batch_director", "confirm"), "cost")
        self.assertEqual(project_catalog_risk("batch_generate_and_prepare_pixiv", "confirm"), "cost")
        self.assertEqual(project_catalog_risk("delete_generated_item", "confirm"), "destructive")
        self.assertEqual(project_catalog_risk("delete_generated_group", "read"), "destructive")

    def test_confirm_cost_destructive_are_not_interactive(self) -> None:
        specs = {spec.name: spec for spec in project_catalog_specs()}
        for name in ("add_to_queue", "start_crawler", "modify_setting", "prepare_pixiv_submission"):
            self.assertEqual(specs[name].risk, "confirm")
            self.assertFalse(specs[name].interactive_executable)
            self.assertEqual(specs[name].executor_domain, "durable")
        for name in PAID_TOOLS:
            self.assertEqual(specs[name].risk, "cost")
            self.assertFalse(specs[name].interactive_executable)
            self.assertEqual(specs[name].executor_domain, "durable")
        for spec in specs.values():
            if spec.risk in WORKFLOW_ONLY_RISKS:
                self.assertFalse(spec.interactive_executable)

    def test_allowed_agents_follow_desk_allowlists(self) -> None:
        specs = {spec.name: spec for spec in project_catalog_specs()}
        for spec in specs.values():
            expected = tuple(
                agent
                for agent, allow in (("sakiko", SAKIKO_TOOLS), ("tomori", TOMORI_TOOLS))
                if spec.name in allow
            )
            self.assertEqual(spec.allowed_agents, expected)
            self.assertTrue(spec.allowed_agents)
        self.assertEqual(specs["generate_image"].allowed_agents, ("tomori",))
        self.assertEqual(specs["start_crawler"].allowed_agents, ("sakiko",))
        self.assertEqual(specs["search_gallery"].allowed_agents, ("sakiko", "tomori"))

    def test_confirm_cost_destructive_only_emit_workflow_request(self) -> None:
        registry = ToolRegistry()
        for spec in project_catalog_specs():
            registry.register(spec)
        extra = project_catalog_specs(
            {
                "tools": [
                    {
                        "name": "delete_generated_item",
                        "risk": "confirm",
                        "description": "删除成果",
                    }
                ]
            }
        )[0]
        registry.register(extra)
        executor = ToolExecutor(registry)
        called: dict[str, int] = {}

        def forbidden(arguments, context):
            called[context.agent_id] = called.get(context.agent_id, 0) + 1
            return {"ok": True, "executed": True}

        for name in (*PAID_TOOLS, "add_to_queue", "start_crawler", "delete_generated_item"):
            executor.bind(name, forbidden)

        cases = (
            ("tomori", "generate_image", "cost"),
            ("tomori", "batch_director", "cost"),
            ("tomori", "add_to_queue", "confirm"),
            ("sakiko", "start_crawler", "confirm"),
            ("sakiko", "delete_generated_item", "destructive"),
        )
        for agent_id, name, risk in cases:
            context = ToolContext.build(registry, agent_id=agent_id, source="chat", round_index=1)
            result = executor.execute(name=name, arguments={"probe": True}, context=context)
            self.assertEqual(result["status"], "workflow_requested", name)
            request = result["workflow_request"]
            self.assertTrue(request["requires_confirmation"], name)
            self.assertEqual(request["risk"], risk, name)
            self.assertEqual(request["proposed_tool"], name)
            self.assertEqual(request["proposed_arguments"], {"probe": True})
            self.assertEqual(result["data"], {})
        self.assertEqual(called, {})

    def test_sakiko_cannot_execute_or_request_tomori_paid_tool(self) -> None:
        registry = ToolRegistry()
        for spec in project_catalog_specs():
            registry.register(spec)
        executor = ToolExecutor(registry)
        called = {"n": 0}

        def forbidden(arguments, context):
            called["n"] += 1
            return {"ok": True}

        executor.bind("generate_image", forbidden)
        context = ToolContext.build(registry, agent_id="sakiko", source="chat", round_index=1)
        result = executor.execute(name="generate_image", arguments={}, context=context)
        self.assertEqual(called["n"], 0)
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["error"]["code"], "permission_denied")
        self.assertIsNone(result["workflow_request"])

    def test_read_catalog_is_the_repo_file(self) -> None:
        payload = read_catalog()
        self.assertIn("tools", payload)
        self.assertEqual(default_catalog_path(), Path("data/butler_catalog.json").resolve())
        names = [item["name"] for item in payload["tools"] if isinstance(item, dict)]
        self.assertIn("generate_image", names)
        self.assertTrue(DESTRUCTIVE_TOOLS.isdisjoint(names))
