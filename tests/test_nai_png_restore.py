"""PNG comment restore and unknown-field compile, without paid NovelAI calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from nai_char_modules import generation
from nai_char_modules.snapshots import comment_from_png, prompt_snapshot_from_png
from nai_image_metadata import parse_nai_image


def _write_nai_png(path: Path, comment: dict, *, software: str = "NovelAI") -> Path:
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", software)
    meta.add_text("Source", "NovelAI Diffusion V4.5")
    meta.add_text("Description", str(comment.get("prompt") or "1girl"))
    meta.add_text("Comment", json.dumps(comment, ensure_ascii=False))
    Image.new("RGB", (32, 48), (30, 40, 50)).save(path, pnginfo=meta)
    return path


class NaiPngRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_embedded_comment_unknown_fields_survive_parse_and_compile(self) -> None:
        path = _write_nai_png(
            self.dir / "restore_unknown.png",
            {
                "prompt": "1girl, amiya",
                "uc": "lowres",
                "width": 832,
                "height": 1216,
                "steps": 28,
                "seed": 42,
                "v4_prompt": {
                    "use_coords": True,
                    "caption": {
                        "base_caption": "1girl, amiya",
                        "char_captions": [
                            {"char_caption": "amiya", "centers": [{"x": 0.2, "y": 0.3}]},
                        ],
                    },
                },
                "future_vendor_field": {"keep": True, "nested": [1, 2]},
                "_aitag_source": {"title": "restore-test"},
            },
        )
        parsed = parse_nai_image(path)
        self.assertTrue(parsed.accepted)
        comment = parsed.canonical_metadata()["Comment"]
        self.assertEqual(comment["future_vendor_field"], {"keep": True, "nested": [1, 2]})
        self.assertEqual(comment["_aitag_source"], {"title": "restore-test"})
        self.assertEqual(comment["seed"], 42)

        restored = comment_from_png(path)
        self.assertEqual(restored["future_vendor_field"], comment["future_vendor_field"])
        snapshot = prompt_snapshot_from_png(path)
        assert snapshot is not None
        self.assertIn("amiya", snapshot["base_caption"])
        self.assertEqual(snapshot["seed"], 42)

        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "generate")
        self.assertEqual(payload["unknown_fields"], ["_aitag_source", "future_vendor_field"])
        self.assertNotIn("future_vendor_field", payload["parameters"])
        self.assertEqual(payload["parameters"]["seed"], 42)
        self.assertEqual(
            payload["parameters"]["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            "amiya",
        )

    def test_restored_mask_and_image_compile_to_infill(self) -> None:
        path = _write_nai_png(
            self.dir / "restore_inpaint.png",
            {
                "prompt": "1girl",
                "uc": "lowres",
                "width": 832,
                "height": 1216,
                "steps": 28,
                "action": "inpaint",
                "image": "base64-or-bytes",
                "mask": "base64-mask",
                "inpaintImg2ImgStrength": 0.4,
                "legacy_unknown": "keep-me",
            },
        )
        comment = comment_from_png(path)
        assert comment is not None
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "infill")
        self.assertEqual(payload["parameters"]["image"], "base64-or-bytes")
        self.assertEqual(payload["parameters"]["mask"], "base64-mask")
        self.assertIn("legacy_unknown", payload["unknown_fields"])
        self.assertNotIn("legacy_unknown", payload["parameters"])

    def test_stealth_fallback_restores_comment_when_text_chunk_missing(self) -> None:
        path = self.dir / "stealth_only.png"
        Image.new("RGB", (16, 16), (8, 8, 8)).save(path)
        stealth = {
            "Software": "NovelAI",
            "Source": "NovelAI Diffusion V4.5",
            "Description": "stealth prompt",
            "Comment": json.dumps(
                {
                    "prompt": "stealth prompt",
                    "uc": "lowres",
                    "seed": 7,
                    "width": 832,
                    "height": 1216,
                    "steps": 28,
                    "vendor_stealth_only": {"ok": True},
                }
            ),
        }
        with patch(
            "nai_image_metadata.extract_image_metadata",
            return_value=stealth,
        ):
            parsed = parse_nai_image(path)
            self.assertTrue(parsed.accepted)
            self.assertEqual(parsed.metadata_source, "stealth_pngcomp")
            comment = parsed.canonical_metadata()["Comment"]
            self.assertEqual(comment["vendor_stealth_only"], {"ok": True})
            restored = comment_from_png(path)
            assert restored is not None
            payload = generation.build_generate_payload(restored)
            self.assertIn("vendor_stealth_only", payload["unknown_fields"])
            self.assertEqual(payload["input"], "stealth prompt")
            self.assertEqual(payload["parameters"]["seed"], 7)

    def test_comfy_png_is_rejected_and_not_compiled(self) -> None:
        path = self.dir / "comfy.png"
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Software", "ComfyUI")
        meta.add_text("prompt", json.dumps({"1": {"class_type": "KSampler"}}))
        Image.new("RGB", (8, 8)).save(path, pnginfo=meta)
        parsed = parse_nai_image(path)
        self.assertFalse(parsed.accepted)
        self.assertEqual(parsed.reason, "comfy_metadata")
        self.assertIsNone(comment_from_png(path))
