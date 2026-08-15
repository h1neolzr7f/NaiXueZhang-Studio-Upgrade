"""NAI compile-layer parameter snapshots and boundaries.

Read-only lock for ``nai_char_modules.generation.build_generate_payload``.
Does not call NovelAI or change ``force_free`` defaults. img2img/infill
compile is locked here once image/mask rules are met.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import nai_api
import nai_char
from nai_char_modules import generation


ROOT = Path(__file__).resolve().parents[1]
COMPILE_META_KEYS = ("requested_action", "unsupported_fields", "unknown_fields")
HTTP_BODY_KEYS = ("input", "model", "action", "parameters", "use_new_shared_trial")


def _txt2img_comment(**overrides: object) -> dict:
    comment: dict = {
        "prompt": "1girl",
        "uc": "lowres",
        "width": 832,
        "height": 1216,
        "steps": 28,
        "scale": 5,
        "sampler": "k_euler_ancestral",
        "seed": 123,
    }
    comment.update(overrides)
    return comment


def _http_body_from_compile(payload: dict) -> dict:
    """Mirror ``nai/generate.py`` official POST body construction. No network."""

    params = {key: value for key, value in (payload.get("parameters") or {}).items() if value is not None}
    return {
        "input": payload["input"],
        "model": payload["model"],
        "action": payload["action"],
        "parameters": params,
        "use_new_shared_trial": False,
    }


class NaiParamSnapshotTests(unittest.TestCase):
    def test_force_free_default_stays_true_on_compile_and_transport(self) -> None:
        compile_sig = inspect.signature(generation.build_generate_payload)
        transport_sig = inspect.signature(nai_api.generate_image)
        self.assertIs(compile_sig.parameters["force_free"].default, True)
        self.assertIs(transport_sig.parameters["force_free"].default, True)
        omitted = generation.build_generate_payload(
            _txt2img_comment(width=2048, height=2048, steps=50)
        )
        self.assertLessEqual(omitted["steps"], generation.MAX_FREE_STEPS)
        self.assertTrue(omitted["resized_for_free"])

    def test_public_facade_is_the_same_compile_function(self) -> None:
        self.assertIs(nai_char.build_generate_payload, generation.build_generate_payload)
        self.assertEqual(nai_api.generate_image.__module__, "nai.generate")

    def test_golden_txt2img_payload_snapshot(self) -> None:
        payload = generation.build_generate_payload(_txt2img_comment())
        self.assertEqual(
            {key: payload[key] for key in (
                "input",
                "model",
                "action",
                "requested_action",
                "unsupported_fields",
                "unknown_fields",
                "request_type",
                "free_eligible",
                "resized_for_free",
                "width",
                "height",
                "steps",
            )},
            {
                "input": "1girl",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "requested_action": "generate",
                "unsupported_fields": [],
                "unknown_fields": [],
                "request_type": "PromptGenerateRequest",
                "free_eligible": True,
                "resized_for_free": False,
                "width": 832,
                "height": 1216,
                "steps": 28,
            },
        )
        parameters = payload["parameters"]
        self.assertEqual(parameters["params_version"], 3)
        self.assertEqual(parameters["width"], 832)
        self.assertEqual(parameters["height"], 1216)
        self.assertEqual(parameters["scale"], 5.0)
        self.assertEqual(parameters["sampler"], "k_euler_ancestral")
        self.assertEqual(parameters["steps"], 28)
        self.assertEqual(parameters["n_samples"], 1)
        self.assertEqual(parameters["ucPreset"], 0)
        self.assertTrue(parameters["qualityToggle"])
        self.assertFalse(parameters["autoSmea"])
        self.assertEqual(parameters["negative_prompt"], "lowres")
        self.assertEqual(parameters["uc"], "lowres")
        self.assertFalse(parameters["legacy"])
        self.assertFalse(parameters["legacy_uc"])
        self.assertFalse(parameters["legacy_v3_extend"])
        self.assertTrue(parameters["add_original_image"])
        self.assertEqual(parameters["controlnet_strength"], 1.0)
        self.assertIsNone(parameters["controlnet_model"])
        self.assertEqual(parameters["reference_image_multiple"], [])
        self.assertEqual(parameters["reference_information_extracted_multiple"], [])
        self.assertEqual(parameters["reference_strength_multiple"], [])
        self.assertTrue(parameters["normalize_reference_strength_multiple"])
        self.assertEqual(parameters["inpaintImg2ImgStrength"], 1.0)
        self.assertEqual(parameters["characterPrompts"], [])
        self.assertEqual(parameters["noise_schedule"], "karras")
        self.assertEqual(parameters["cfg_rescale"], 0)
        self.assertFalse(parameters["dynamic_thresholding"])
        self.assertEqual(parameters["dynamic_thresholding_percentile"], 0.999)
        self.assertEqual(parameters["dynamic_thresholding_mimic_scale"], 10.0)
        self.assertIsNone(parameters["skip_cfg_above_sigma"])
        self.assertEqual(parameters["skip_cfg_below_sigma"], 0.0)
        self.assertTrue(parameters["prefer_brownian"])
        self.assertFalse(parameters["deliberate_euler_ancestral_bug"])
        self.assertIsNone(parameters["sm"])
        self.assertIsNone(parameters["sm_dyn"])
        self.assertTrue(parameters["use_coords"])
        self.assertEqual(parameters["seed"], 123)
        self.assertEqual(
            parameters["v4_prompt"],
            {"caption": {"base_caption": "1girl", "char_captions": []}, "use_coords": True},
        )
        self.assertEqual(
            parameters["v4_negative_prompt"],
            {"caption": {"base_caption": "lowres", "char_captions": []}, "use_coords": True},
        )
        self.assertNotIn("image", parameters)
        self.assertNotIn("mask", parameters)
        self.assertNotIn("anlas", parameters)
        self.assertNotIn("anlas_spent", payload)

    def test_model_matrix_explicit_wins_and_silent_defaults_to_v45_full(self) -> None:
        cases = (
            ({}, "nai-diffusion-4-5-full"),
            ({"Source": "NovelAI Diffusion V4.5"}, "nai-diffusion-4-5-full"),
            ({"Source": "NovelAI Diffusion V4"}, "nai-diffusion-4-full"),
            ({"Source": "NovelAI Diffusion V4.5", "model": "nai-diffusion-4-5-curated"}, "nai-diffusion-4-5-curated"),
            ({"model": "nai-diffusion-4-full"}, "nai-diffusion-4-full"),
            ({"model": "not-a-nai-id", "Source": "NovelAI Diffusion V4"}, "nai-diffusion-4-full"),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra, expected=expected):
                payload = generation.build_generate_payload(_txt2img_comment(**extra))
                self.assertEqual(payload["model"], expected)
                self.assertEqual(payload["action"], "generate")

    def test_quality_uc_sampler_and_rescale_pass_through(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(
                qualityToggle=False,
                negative_prompt="worst quality",
                uc="ignored-when-negative-present",
                sampler="k_euler",
                cfg_rescale=0.4,
                noise_schedule="exponential",
                steps=23,
            )
        )
        parameters = payload["parameters"]
        self.assertFalse(parameters["qualityToggle"])
        self.assertEqual(parameters["uc"], "worst quality")
        self.assertEqual(parameters["negative_prompt"], "worst quality")
        self.assertEqual(parameters["sampler"], "k_euler")
        self.assertEqual(parameters["cfg_rescale"], 0.4)
        self.assertEqual(parameters["noise_schedule"], "exponential")
        self.assertEqual(parameters["steps"], 23)
        self.assertTrue(payload["free_eligible"])

    def test_character_slots_and_precise_reference_stay_txt2img(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(
                characterPrompts=[{"prompt": "amiya", "uc": "", "center": {"x": 0.2, "y": 0.3}}],
                v4_prompt={
                    "use_coords": True,
                    "caption": {
                        "base_caption": "1girl",
                        "char_captions": [
                            {"char_caption": "amiya", "centers": [{"x": 0.2, "y": 0.3}]},
                        ],
                    },
                },
                reference_image_multiple=["https://example.invalid/ref.png"],
                reference_information_extracted_multiple=[0.9],
                reference_strength_multiple=[0.6],
            )
        )
        parameters = payload["parameters"]
        self.assertEqual(payload["action"], "generate")
        self.assertEqual(payload["requested_action"], "generate")
        self.assertEqual(payload["unsupported_fields"], [])
        self.assertFalse(payload["free_eligible"])
        self.assertEqual(parameters["characterPrompts"][0]["prompt"], "amiya")
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["char_captions"],
            [{"char_caption": "", "centers": [{"x": 0.2, "y": 0.3}]}],
        )
        self.assertEqual(parameters["reference_image_multiple"], ["https://example.invalid/ref.png"])
        self.assertEqual(parameters["reference_information_extracted_multiple"], [0.9])
        self.assertEqual(parameters["reference_strength_multiple"], [0.6])
        self.assertNotIn("image", parameters)

    def test_img2img_inpaint_compile_while_vibe_stays_unsupported(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(
                action="inpaint",
                image="base64-or-bytes",
                mask="base64-mask",
                inpaintImg2ImgStrength=0.42,
                xianyun_vibe={"reference_images": ["https://example.invalid/vibe.png"]},
                vibe_transfer={"enabled": True},
                vibeTransfer={"enabled": True},
                vibe={"enabled": True},
            )
        )
        self.assertEqual(payload["action"], "infill")
        self.assertEqual(payload["requested_action"], "inpaint")
        self.assertEqual(
            payload["unsupported_fields"],
            [
                "xianyun_vibe",
                "vibe_transfer",
                "vibeTransfer",
                "vibe",
            ],
        )
        self.assertEqual(payload["unknown_fields"], [])
        self.assertFalse(payload["free_eligible"])
        self.assertEqual(payload["parameters"]["inpaintImg2ImgStrength"], 0.42)
        self.assertEqual(payload["parameters"]["image"], "base64-or-bytes")
        self.assertEqual(payload["parameters"]["mask"], "base64-mask")
        self.assertEqual(payload["parameters"]["strength"], 0.42)
        self.assertNotIn("xianyun_vibe", payload["parameters"])
        self.assertNotIn("vibe_transfer", payload["parameters"])
        self.assertNotIn("vibeTransfer", payload["parameters"])
        self.assertNotIn("vibe", payload["parameters"])

    def test_requested_action_wins_and_unknown_action_is_coerced(self) -> None:
        preferred = generation.build_generate_payload(
            _txt2img_comment(action="generate", requested_action="img2img")
        )
        self.assertEqual(preferred["action"], "generate")
        self.assertEqual(preferred["requested_action"], "img2img")
        self.assertIn("action:img2img", preferred["unsupported_fields"])

        coerced = generation.build_generate_payload(_txt2img_comment(action="upscale"))
        self.assertEqual(coerced["action"], "generate")
        self.assertEqual(coerced["requested_action"], "generate")
        self.assertEqual(coerced["unsupported_fields"], [])
        self.assertEqual(coerced["unknown_fields"], [])

        infill = generation.build_generate_payload(_txt2img_comment(action="INFILL"))
        self.assertEqual(infill["requested_action"], "infill")
        self.assertEqual(infill["action"], "generate")
        self.assertIn("action:infill", infill["unsupported_fields"])

        compiled = generation.build_generate_payload(
            _txt2img_comment(action="img2img", image="raw")
        )
        self.assertEqual(compiled["action"], "img2img")
        self.assertEqual(compiled["requested_action"], "img2img")
        self.assertNotIn("action:img2img", compiled["unsupported_fields"])
        self.assertEqual(compiled["parameters"]["image"], "raw")

    def test_unknown_vendor_keys_are_listed_and_not_sent(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(future_vendor_field={"keep": True}, _aitag_source={"title": "x"})
        )
        self.assertEqual(payload["unknown_fields"], ["_aitag_source", "future_vendor_field"])
        self.assertNotIn("future_vendor_field", payload["parameters"])
        self.assertNotIn("_aitag_source", payload["parameters"])

    def test_compile_metadata_does_not_enter_official_http_body(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(
                action="img2img",
                image="raw",
                future_vendor_field=1,
                controlnet_model=None,
            )
        )
        body = _http_body_from_compile(payload)
        self.assertEqual(set(body), set(HTTP_BODY_KEYS))
        self.assertEqual(body["action"], "img2img")
        self.assertFalse(body["use_new_shared_trial"])
        for key in COMPILE_META_KEYS:
            self.assertIn(key, payload)
            self.assertNotIn(key, body)
            self.assertNotIn(key, body["parameters"])
        self.assertEqual(body["parameters"]["image"], "raw")
        self.assertNotIn("controlnet_model", body["parameters"])
        self.assertNotIn("anlas_spent", body)
        self.assertNotIn("future_vendor_field", body["parameters"])

    def test_generate_py_body_literal_only_has_official_keys(self) -> None:
        tree = ast.parse((ROOT / "nai" / "generate.py").read_text(encoding="utf-8"))
        bodies: list[set[str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != "body":
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            keys = {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if "use_new_shared_trial" in keys:
                bodies.append(keys)
        self.assertEqual(bodies, [set(HTTP_BODY_KEYS)])


class NaiSizeSeedBoundaryTests(unittest.TestCase):
    def test_fit_opus_free_size_table(self) -> None:
        cases = (
            (0, 0, (832, 1216, True)),
            (-8, 1216, (832, 1216, True)),
            (832, 1216, (832, 1216, False)),
            (1216, 832, (1216, 832, False)),
            (1024, 1024, (1024, 1024, False)),
            (1216, 1216, (1024, 1024, True)),
            (2048, 2048, (1024, 1024, True)),
        )
        for width, height, expected in cases:
            with self.subTest(width=width, height=height):
                self.assertEqual(generation.fit_opus_free_size(width, height), expected)

    def test_force_free_caps_steps_and_pixels(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(width=2048, height=2048, steps=50),
            force_free=True,
        )
        self.assertEqual(payload["width"], 1024)
        self.assertEqual(payload["height"], 1024)
        self.assertEqual(payload["steps"], 28)
        self.assertTrue(payload["resized_for_free"])
        self.assertTrue(payload["free_eligible"])
        self.assertLessEqual(payload["width"] * payload["height"], generation.MAX_FREE_PIXELS)

    def test_paid_size_below_double_long_edge_is_kept(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(width=1472, height=1472, steps=36),
            force_free=False,
        )
        self.assertEqual((payload["width"], payload["height"], payload["steps"]), (1472, 1472, 36))
        self.assertFalse(payload["free_eligible"])
        self.assertFalse(payload["resized_for_free"])

    def test_paid_size_above_double_long_edge_is_still_fitted(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(width=2500, height=2500, steps=36),
            force_free=False,
        )
        self.assertEqual((payload["width"], payload["height"]), (1024, 1024))
        self.assertEqual(payload["steps"], 36)
        self.assertTrue(payload["resized_for_free"])
        self.assertFalse(payload["free_eligible"])

    def test_zero_width_uses_default_then_free_fit(self) -> None:
        payload = generation.build_generate_payload(_txt2img_comment(width=0, height=0))
        self.assertEqual((payload["width"], payload["height"]), (832, 1216))
        self.assertFalse(payload["resized_for_free"])

    def test_negative_size_without_force_free_is_not_clamped(self) -> None:
        payload = generation.build_generate_payload(
            _txt2img_comment(width=-10, height=1216),
            force_free=False,
        )
        self.assertEqual(payload["width"], -10)
        self.assertEqual(payload["height"], 1216)
        self.assertFalse(payload["resized_for_free"])

    def test_seed_boundaries(self) -> None:
        kept_random = generation.build_generate_payload(_txt2img_comment(seed=-1))
        kept_zero = generation.build_generate_payload(_txt2img_comment(seed=0))
        omitted_negative = generation.build_generate_payload(_txt2img_comment(seed=-2))
        omitted_text = generation.build_generate_payload(_txt2img_comment(seed="nope"))
        omitted_blank = generation.build_generate_payload(_txt2img_comment(seed=""))
        omitted_none = generation.build_generate_payload(_txt2img_comment(seed=None))
        self.assertEqual(kept_random["parameters"]["seed"], -1)
        self.assertEqual(kept_zero["parameters"]["seed"], 0)
        self.assertNotIn("seed", omitted_negative["parameters"])
        self.assertNotIn("seed", omitted_text["parameters"])
        self.assertNotIn("seed", omitted_blank["parameters"])
        self.assertNotIn("seed", omitted_none["parameters"])


class NaiTransportIsolationTests(unittest.TestCase):
    def test_only_generate_module_posts_official_image_endpoint(self) -> None:
        hits: list[str] = []
        skip_parts = {".venv", "runtime", "node_modules", "data", "__pycache__", "tests"}
        for path in ROOT.rglob("*.py"):
            if any(part in skip_parts for part in path.parts):
                continue
            if "/ai/generate-image" not in path.read_text(encoding="utf-8"):
                continue
            hits.append(str(path.relative_to(ROOT)).replace("\\", "/"))
        self.assertEqual(hits, ["nai/generate.py"])

    def test_nai_api_does_not_redefine_generate_image(self) -> None:
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
        imported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "nai.generate"
            and any(alias.name == "generate_image" for alias in node.names)
            for node in source.body
        )
        self.assertTrue(imported)

    def test_director_stays_on_augment_endpoint(self) -> None:
        text = (ROOT / "nai" / "director.py").read_text(encoding="utf-8")
        self.assertIn("/ai/augment-image", text)
        self.assertNotIn("/ai/generate-image", text)
