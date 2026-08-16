from __future__ import annotations

import ast
import unittest
from pathlib import Path

from butler.tooling import (
    ToolContext,
    ToolExecutor,
    ToolRegistry,
    bind_kernel_tools,
)


ROOT = Path(__file__).resolve().parents[2]


class KernelToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        bind_kernel_tools(self.registry, self.executor)
        self.context = ToolContext.build(
            self.registry, agent_id="tomori", source="kernel", round_index=1
        )

    def test_compile_preview_does_not_call_generate_image(self) -> None:
        result = self.executor.execute(
            name="compile_nai_preview",
            arguments={
                "comment": {
                    "prompt": "1girl",
                    "width": 832,
                    "height": 1216,
                    "steps": 28,
                    "action": "img2img",
                    "image": "raw",
                    "future_vendor_field": 1,
                }
            },
            context=self.context,
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["action"], "img2img")
        self.assertEqual(result["data"]["requested_action"], "img2img")
        self.assertIn("future_vendor_field", result["data"]["unknown_fields"])
        source = (ROOT / "butler" / "tooling" / "kernel_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("generate_image", source)
        self.assertNotIn("planning.py", source)

    def test_compile_preview_is_idempotent_for_same_arguments(self) -> None:
        called = {"n": 0}
        original = self.executor._handlers["compile_nai_preview"]

        def wrapped(arguments, context):
            called["n"] += 1
            return original(arguments, context)

        self.executor.bind("compile_nai_preview", wrapped)
        args = {"comment": {"prompt": "1girl", "width": 832, "height": 1216, "steps": 28}}
        first = self.executor.execute(name="compile_nai_preview", arguments=args, context=self.context)
        second = self.executor.execute(name="compile_nai_preview", arguments=args, context=self.context)
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(second["status"], "succeeded")
        self.assertEqual(called["n"], 1)

    def test_gallery_preview_finds_exact_dups_without_butler_store(self) -> None:
        result = self.executor.execute(
            name="gallery_index_preview",
            arguments={
                "items": [
                    {"work_id": 1, "source_sha256": "abc"},
                    {"work_id": 2, "source_sha256": "abc"},
                    {"work_id": 3, "source_sha256": "zzz"},
                ]
            },
            context=self.context,
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["text_dirty"], 3)
        self.assertEqual(len(result["data"]["duplicates"]), 1)
        self.assertEqual(result["data"]["embed"]["provider"], "local_none")

    def test_planning_module_still_does_not_import_kernel(self) -> None:
        tree = ast.parse((ROOT / "butler" / "planning.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("butler.tooling"):
                imported.append(node.module or "")
            if isinstance(node, ast.Import):
                imported.extend(
                    alias.name for alias in node.names if alias.name.startswith("butler.tooling")
                )
        self.assertEqual(imported, [])
        text = (ROOT / "butler" / "planning.py").read_text(encoding="utf-8")
        self.assertNotIn("bind_kernel_tools", text)
        self.assertNotIn("InteractiveLoop", text)
