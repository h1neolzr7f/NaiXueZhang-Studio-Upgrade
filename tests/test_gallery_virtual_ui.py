from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GalleryVirtualUiTests(unittest.TestCase):
    def test_eager_card_uses_thumbnail_url_not_boolean_flag(self) -> None:
        script = r"""
        const fs = require("fs");
        const vm = require("vm");
        const image = { src: "" };
        const card = { querySelector: () => image };
        const window = {};
        const document = { getElementById: () => null };
        vm.runInNewContext(
          fs.readFileSync("web/shared/gallery-virtual.js", "utf8"),
          { window, document, WeakMap },
        );
        window.GalleryVirtual.observeCard(card, "/data/gallery/qqgroup/thumb.webp", true);
        console.log(JSON.stringify({ src: image.src }));
        """
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(
            json.loads(result.stdout)["src"],
            "/data/gallery/qqgroup/thumb.webp",
        )


if __name__ == "__main__":
    unittest.main()
