from __future__ import annotations

import unittest

from butler.tooling import ToolRegistry, ToolSpec, ToolingError


class RegistryTests(unittest.TestCase):
    def test_rejects_duplicate_name_version(self) -> None:
        registry = ToolRegistry()
        spec = ToolSpec(name="search_gallery", version="1", description="search", risk="read", allowed_agents=("shared",))
        registry.register(spec)
        with self.assertRaises(ToolingError):
            registry.register(spec)

    def test_lists_tools_for_agent(self) -> None:
        registry = ToolRegistry()
        registry.register(ToolSpec(name="search_gallery", version="1", description="s", risk="read", allowed_agents=("shared",)))
        registry.register(ToolSpec(name="generate_image", version="1", description="g", risk="cost", allowed_agents=("tomori",)))
        self.assertEqual([item.name for item in registry.list_for_agent("sakiko")], ["search_gallery"])
        self.assertEqual([item.name for item in registry.list_for_agent("tomori")], ["search_gallery", "generate_image"])
