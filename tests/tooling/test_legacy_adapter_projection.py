from __future__ import annotations

import unittest

from butler.tooling import project_legacy_specs


class LegacyAdapterTests(unittest.TestCase):
    def test_read_and_draft_are_interactive_but_paid_tools_are_not(self) -> None:
        specs = {spec.name: spec for spec in project_legacy_specs()}
        self.assertTrue(specs["search_gallery"].interactive_executable)
        self.assertTrue(specs["prepare_studio"].interactive_executable)
        self.assertFalse(specs["generate_image"].interactive_executable)
        self.assertFalse(specs["start_crawler"].interactive_executable)
        self.assertFalse(specs["delete_generated_item"].interactive_executable)
        self.assertFalse(specs["prepare_pixiv_submission"].interactive_executable)
        self.assertEqual(specs["generate_image"].risk, "cost")
        self.assertEqual(specs["delete_generated_item"].risk, "destructive")
