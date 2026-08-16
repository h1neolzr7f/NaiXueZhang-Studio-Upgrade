from __future__ import annotations

import ast
import base64
import io
import unittest
from pathlib import Path

from PIL import Image

import nai_api
import nai_char
from nai.generate import generate_image as generate_impl
from nai_char_modules import generation


ROOT = Path(__file__).resolve().parents[1]


class NaiGenerateCompileLockTests(unittest.TestCase):
    def test_public_facades_are_the_same_compile_and_client(self) -> None:
        self.assertIs(nai_char.build_generate_payload, generation.build_generate_payload)
        self.assertIs(nai_api.generate_image, generate_impl)

    def test_v45_source_maps_to_full_not_curated(self) -> None:
        self.assertEqual(generation._infer_model("NovelAI Diffusion V4.5"), "nai-diffusion-4-5-full")
        self.assertEqual(generation._infer_model("", "nai-diffusion-4-5-curated"), "nai-diffusion-4-5-curated")

    def test_v4_source_maps_to_v4_full_and_explicit_model_wins(self) -> None:
        self.assertEqual(generation._infer_model("NovelAI Diffusion V4"), "nai-diffusion-4-full")
        comment = {
            "prompt": "1girl",
            "Source": "NovelAI Diffusion V4.5",
            "model": "nai-diffusion-4-5-curated",
            "width": 832,
            "height": 1216,
            "steps": 28,
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["model"], "nai-diffusion-4-5-curated")

    def test_payload_is_txt2img_generate_without_encoding_urls(self) -> None:
        comment = {
            "prompt": "1girl",
            "uc": "lowres",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "scale": 5,
            "sampler": "k_euler_ancestral",
            "seed": 123,
            "reference_image_multiple": ["https://example.invalid/ref.png"],
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "generate")
        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        parameters = payload["parameters"]
        self.assertEqual(parameters.get("reference_image_multiple"), ["https://example.invalid/ref.png"])
        self.assertNotIn("image", parameters)
        self.assertNotIn("mask", parameters)

    def test_smea_is_not_free_eligible(self) -> None:
        comment = {"prompt": "1girl", "width": 832, "height": 1216, "steps": 23, "sm": True}
        payload = generation.build_generate_payload(comment, force_free=True)
        self.assertFalse(payload["free_eligible"])
        dyn = generation.build_generate_payload({**comment, "sm": False, "sm_dyn": True}, force_free=True)
        self.assertFalse(dyn["free_eligible"])
        auto = generation.build_generate_payload({**comment, "sm": False, "autoSmea": True}, force_free=True)
        self.assertFalse(auto["free_eligible"])

    def test_reference_or_image_is_not_free_eligible(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "image": "raw-bytes-or-url",
        }
        info = generation.build_generate_payload(comment)
        self.assertEqual(info["action"], "generate")
        self.assertFalse(info["free_eligible"])

    def test_mask_and_image_compile_to_infill(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "image": "base64-or-bytes",
            "mask": "base64-mask",
            "inpaintImg2ImgStrength": 0.55,
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "infill")
        self.assertEqual(payload["requested_action"], "generate")
        self.assertFalse(payload["free_eligible"])
        self.assertEqual(payload["parameters"]["image"], "base64-or-bytes")
        self.assertEqual(payload["parameters"]["mask"], "base64-mask")
        self.assertEqual(payload["parameters"]["inpaintImg2ImgStrength"], 0.55)
        self.assertEqual(payload["parameters"]["strength"], 0.55)
        self.assertNotIn("image", payload["unsupported_fields"])
        self.assertNotIn("mask", payload["unsupported_fields"])

    def test_inpaint_mask_is_resized_to_image_pixels(self) -> None:
        def _png(width: int, height: int, mode: str = "RGB", color=0) -> str:
            buffer = io.BytesIO()
            Image.new(mode, (width, height), color).save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")

        image = _png(64, 64, "RGB", (12, 34, 56))
        mask = _png(16, 16, "L", 255)
        payload = generation.build_generate_payload(
            {
                "prompt": "1girl",
                "width": 64,
                "height": 64,
                "steps": 28,
                "image": image,
                "mask": mask,
            }
        )
        self.assertEqual(payload["action"], "infill")
        decoded = Image.open(io.BytesIO(base64.b64decode(payload["parameters"]["mask"])))
        self.assertEqual(decoded.size, (64, 64))
        self.assertEqual(generation.align_inpaint_mask("base64-or-bytes", "base64-mask"), "base64-mask")

    def test_force_free_resizes_and_caps_steps(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 2048,
            "height": 2048,
            "steps": 50,
        }
        payload = generation.build_generate_payload(comment, force_free=True)
        self.assertTrue(payload["resized_for_free"])
        self.assertLessEqual(payload["steps"], generation.MAX_FREE_STEPS)
        self.assertLessEqual(max(payload["width"], payload["height"]), generation.MAX_FREE_LONG_EDGE)
        self.assertLessEqual(payload["width"] * payload["height"], generation.MAX_FREE_PIXELS)
        self.assertTrue(payload["free_eligible"])

    def test_paid_size_below_double_long_edge_is_kept(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 1472,
            "height": 1472,
            "steps": 36,
        }
        payload = generation.build_generate_payload(comment, force_free=False)
        self.assertEqual(payload["width"], 1472)
        self.assertEqual(payload["height"], 1472)
        self.assertEqual(payload["steps"], 36)
        self.assertFalse(payload["free_eligible"])
        self.assertFalse(payload["resized_for_free"])

    def test_seed_minus_one_is_kept_and_invalid_seed_is_omitted(self) -> None:
        kept = generation.build_generate_payload(
            {"prompt": "1girl", "width": 832, "height": 1216, "steps": 28, "seed": -1}
        )
        omitted = generation.build_generate_payload(
            {"prompt": "1girl", "width": 832, "height": 1216, "steps": 28, "seed": "nope"}
        )
        self.assertEqual(kept["parameters"]["seed"], -1)
        self.assertNotIn("seed", omitted["parameters"])

    def test_v4_negative_captions_are_padded_to_character_slots(self) -> None:
        comment = {
            "prompt": "1girl",
            "uc": "lowres",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "v4_prompt": {
                "use_coords": True,
                "caption": {
                    "base_caption": "1girl",
                    "char_captions": [
                        {"char_caption": "amiya", "centers": [{"x": 0.2, "y": 0.3}]},
                        {"char_caption": "kaltsit", "centers": [{"x": 0.8, "y": 0.7}]},
                    ],
                },
            },
        }
        payload = generation.build_generate_payload(comment)
        negatives = payload["parameters"]["v4_negative_prompt"]["caption"]["char_captions"]
        self.assertEqual(len(negatives), 2)
        self.assertEqual(negatives[0]["centers"][0], {"x": 0.2, "y": 0.3})
        self.assertEqual(negatives[1]["centers"][0], {"x": 0.8, "y": 0.7})
        self.assertEqual(negatives[0]["char_caption"], "")

    def test_only_nai_generate_module_calls_official_image_endpoint(self) -> None:
        hits: list[str] = []
        skip_parts = {".venv", "runtime", "node_modules", "data", "__pycache__", "tests"}
        for path in ROOT.rglob("*.py"):
            if any(part in skip_parts for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            if "/ai/generate-image" not in text:
                continue
            relative = str(path.relative_to(ROOT)).replace("\\", "/")
            hits.append(relative)
        self.assertEqual(hits, ["nai/generate.py"])

    def test_unknown_and_uncompiled_fields_are_reported_not_dropped(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "action": "img2img",
            "image": "base64-or-bytes",
            "mask": "base64-mask",
            "xianyun_vibe": {"reference_images": ["https://example.invalid/vibe.png"]},
            "future_vendor_field": {"keep": True},
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "infill")
        self.assertEqual(payload["requested_action"], "img2img")
        self.assertEqual(payload["parameters"]["image"], "base64-or-bytes")
        self.assertEqual(payload["parameters"]["mask"], "base64-mask")
        self.assertNotIn("image", payload["unsupported_fields"])
        self.assertNotIn("mask", payload["unsupported_fields"])
        self.assertNotIn("action:img2img", payload["unsupported_fields"])
        self.assertIn("xianyun_vibe", payload["unsupported_fields"])
        self.assertIn("future_vendor_field", payload["unknown_fields"])
        self.assertNotIn("future_vendor_field", payload["parameters"])
        self.assertNotIn("xianyun_vibe", payload["parameters"])

    def test_explicit_img2img_without_mask_compiles_image(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "action": "img2img",
            "image": "base64-or-bytes",
            "strength": 0.42,
            "noise": 0.05,
            "extra_noise_seed": 99,
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "img2img")
        self.assertEqual(payload["requested_action"], "img2img")
        self.assertEqual(payload["unsupported_fields"], [])
        self.assertEqual(payload["parameters"]["image"], "base64-or-bytes")
        self.assertNotIn("mask", payload["parameters"])
        self.assertEqual(payload["parameters"]["strength"], 0.42)
        self.assertEqual(payload["parameters"]["noise"], 0.05)
        self.assertEqual(payload["parameters"]["extra_noise_seed"], 99)
        self.assertFalse(payload["free_eligible"])

    def test_image_alone_stays_txt2img_and_is_reported(self) -> None:
        comment = {
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
            "image": "raw-bytes-or-url",
        }
        payload = generation.build_generate_payload(comment)
        self.assertEqual(payload["action"], "generate")
        self.assertIn("image", payload["unsupported_fields"])
        self.assertNotIn("image", payload["parameters"])

    def test_generate_image_does_not_define_a_second_http_client(self) -> None:
        source = ast.parse((ROOT / "nai_api.py").read_text(encoding="utf-8"))
        assigned = [
            node.targets[0].id
            for node in source.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "generate_image"
        ]
        self.assertEqual(assigned, [])
        imported = False
        for node in source.body:
            if isinstance(node, ast.ImportFrom) and node.module == "nai.generate":
                imported = any(alias.name == "generate_image" for alias in node.names)
        self.assertTrue(imported)
