from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CompanionDockUiTests(unittest.TestCase):
    def test_edge_docks_are_sakiko_left_tomori_right_without_bare_fetch(self) -> None:
        js = (ROOT / "web" / "shared" / "companion-dock.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "shared" / "companion-dock.css").read_text(encoding="utf-8")
        nav = (ROOT / "web" / "shared" / "site-nav.js").read_text(encoding="utf-8")
        self.assertIn("/assets/shared/companion-dock.js?v=", nav)
        self.assertIn("path === \"/butler\"", nav)
        self.assertIn('id: "sakiko"', js)
        self.assertIn("助手凑企鹅", js)
        self.assertIn('side: "left"', js)
        self.assertIn('side: "right"', js)
        self.assertIn("左侧 · 客服", js)
        self.assertIn("右侧 · 生成", js)
        self.assertIn("sakiko/causal/model.json", js)
        self.assertIn("tomori/casual/model.json", js)
        self.assertIn("/api/butler/chat", js)
        self.assertIn("/api/companion/events", js)
        self.assertIn("/api/companion/handoff", js)
        self.assertIn("agent: agentId", js)
        self.assertIn("menus: { items: [] }", js)
        self.assertIn("createWidget", js)
        self.assertIn("live2d-touch.js?v=", js)
        self.assertIn("window.Live2dTouch", js)
        self.assertIn("bindTouch", js)
        self.assertIn("companion-bubble", js)
        self.assertIn("companion-stage-aura", js)
        self.assertIn("companion-peek-tab", js)
        self.assertIn("is-loading", js)
        self.assertIn("}, 900);", js)
        self.assertIn("dockHasFocus", js)
        self.assertIn("destroy: true", js)
        self.assertIn("innerHeight", js)
        self.assertIn("align-self: center", css)
        self.assertIn("rotate(45deg)", css)
        self.assertIn("width: 16px", css)
        self.assertIn("pointer-events: auto", css)
        self.assertIn("bottom: 176px", css)
        self.assertIn(".companion-log:empty", css)
        self.assertIn("min(520px, 42vw)", css)
        self.assertIn("body.butler-body .companion-docks", css)
        self.assertIsNone(re.search(r"\bfetch\s*\(", js))
        self.assertIn("window.ApiClient", js)

    def test_live2d_tap_plays_motion_and_synthesized_sfx(self) -> None:
        js = (ROOT / "web" / "shared" / "live2d-touch.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "shared" / "live2d-touch.css").read_text(encoding="utf-8")
        self.assertIn("tap_body", js)
        self.assertIn("flick_head", js)
        self.assertIn("AudioContext", js)
        self.assertIn("playSfx", js)
        self.assertIn("live2d-spark", css)
        self.assertIn("点击互动", js)
        self.assertIsNone(re.search(r"\bfetch\s*\(", js))

    def test_full_conversations_are_under_more_not_primary(self) -> None:
        nav = (ROOT / "web" / "shared" / "site-nav.js").read_text(encoding="utf-8")
        primary = nav.split("const NAV_SECONDARY", 1)[0]
        self.assertNotIn("butler-sakiko", primary)
        self.assertIn("group: \"对话\"", nav)
        self.assertIn("/butler?agent=sakiko", nav)
        self.assertIn("/butler?agent=tomori", nav)


if __name__ == "__main__":
    unittest.main()
