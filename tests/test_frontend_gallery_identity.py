from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LARGE_QQ_WORK_ID = "1060330205301688249"


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


class FrontendGalleryIdentityTests(unittest.TestCase):
    def test_work_bridge_keeps_large_work_id_and_gallery_context_exact(self) -> None:
        data = _run_node(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const stored = new Map();
            const sessionStorage = {{
              setItem(key, value) {{ stored.set(key, value); }},
              getItem(key) {{ return stored.get(key) || null; }},
            }};
            const window = {{
              location: {{
                origin: "http://127.0.0.1:8787",
                href: "http://127.0.0.1:8787/?gallery=qqgroup&group=account%3A42",
              }},
            }};
            vm.runInNewContext(
              fs.readFileSync("web/shared/work-bridge.js", "utf8"),
              {{ window, sessionStorage, URL, Date }},
            );
            const saved = window.WorkBridge.save({{
              workId: "{LARGE_QQ_WORK_ID}",
              pageIndex: 0,
              from: "gallery",
            }});
            console.log(JSON.stringify({{
              saved,
              loaded: window.WorkBridge.load(),
              detail: window.WorkBridge.withGalleryContext("/i/{LARGE_QQ_WORK_ID}"),
              studio: window.WorkBridge.buildUrl("/studio", "{LARGE_QQ_WORK_ID}", 0),
            }}));
            """
        )
        self.assertEqual(data["saved"]["workId"], LARGE_QQ_WORK_ID)
        self.assertEqual(data["loaded"]["workId"], LARGE_QQ_WORK_ID)
        for key in ("detail", "studio"):
            with self.subTest(key=key):
                self.assertIn("gallery=qqgroup", data[key])
                self.assertIn("group=account%3A42", data[key])
        self.assertIn(f"from={LARGE_QQ_WORK_ID}", data["studio"])

    def test_gallery_actions_treat_work_ids_as_opaque_strings(self) -> None:
        core = (ROOT / "web" / "app-core.js").read_text(encoding="utf-8")
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        for function_name in (
            "setFavoriteIds",
            "isFavorited",
            "toggleFavorite",
            "isQueued",
            "loadQueue",
            "toggleQueue",
        ):
            match = re.search(
                rf"(?:async\s+)?function\s+{function_name}\b.*?\n\}}",
                core,
                re.DOTALL,
            )
            self.assertIsNotNone(match, function_name)
            body = match.group(0)
            self.assertIn("normalizeWorkId", body, function_name)
            self.assertNotIn("Number(workId)", body, function_name)

        self.assertNotIn("const id = parseInt(idStr, 10)", app)
        self.assertIn("normalizeWorkId(decodeURIComponent(idStr))", app)
        self.assertIn("compareWorkIdsDesc", core)
        self.assertNotIn("Number(b.id || 0) - Number(a.id || 0)", core)

    def test_card_and_detail_urls_keep_selected_gallery(self) -> None:
        # app.js 已按域拆分（app-detail.js / app-online-remix.js），合并断言
        app = "".join(
            (ROOT / "web" / name).read_text(encoding="utf-8")
            for name in ("app.js", "app-detail.js", "app-online-remix.js")
        )
        self.assertIn(
            "withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(w.id))}`))",
            app,
        )
        self.assertIn(
            "withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(workId))}`))",
            app,
        )

    def test_char_swap_and_comparison_keep_large_qq_identity(self) -> None:
        data = _run_node(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const storage = {{
              value: "",
              getItem() {{ return this.value; }},
              setItem(_key, value) {{ this.value = value; }},
            }};
            const window = {{ localStorage: storage }};
            vm.runInNewContext(
              fs.readFileSync("web/shared/comparison-workspace.js", "utf8"),
              {{ window, Date }},
            );
            const workspace = new window.ComparisonWorkspace.ComparisonWorkspace(storage);
            workspace.add({{
              gallery_id: "qqgroup",
              work_id: "{LARGE_QQ_WORK_ID}",
              page_index: 2,
            }});
            console.log(JSON.stringify(workspace.snapshot()[0]));
            """
        )
        self.assertEqual(data["work_id"], LARGE_QQ_WORK_ID)
        self.assertEqual(
            data["candidate_id"],
            f"gallery:qqgroup:{LARGE_QQ_WORK_ID}:p2",
        )
        self.assertIn(
            f"/i/{LARGE_QQ_WORK_ID}?gallery=qqgroup",
            data["url"],
        )

        for relative in (
            "web/plugins/char-swap/state.js",
            "web/plugins/char-swap/draft_helpers.js",
            "web/plugins/char-swap/batch.js",
            "web/plugins/char-swap/plugin.js",
            "web/remix.js",
            "web/shared/gallery-detail-hooks.js",
            "web/shared/prompt-preview.js",
            "web/studio.js",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("Number(workId)", source)
                self.assertNotIn("Number(detail.workId)", source)
                self.assertNotIn("parseInt(params.get(\"from\")", source)

        panel = (ROOT / "web" / "plugins" / "char-swap" / "panel.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('searchParams.get("gallery")', panel)
        self.assertIn('params.set("gallery_id", galleryId)', panel)


if __name__ == "__main__":
    unittest.main()
