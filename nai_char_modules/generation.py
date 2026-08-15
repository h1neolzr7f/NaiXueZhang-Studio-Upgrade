"""NovelAI request compilation and free-generation safety rules.

This module deliberately knows nothing about galleries or character replacement.
Its small interface hides the complete mapping from a Studio Draft comment to the
provider request shape used by ``nai_api``.
"""

from __future__ import annotations

import copy
from typing import Any

MAX_FREE_LONG_EDGE = 1216
MAX_FREE_STEPS = 28
MAX_FREE_PIXELS = 1024 * 1024

# Keys consumed by the current txt2img compile path. Anything else is reported,
# not silently dropped, and is not sent as a second NovelAI client.
KNOWN_COMMENT_KEYS = frozenset(
    {
        "prompt",
        "uc",
        "negative_prompt",
        "Source",
        "model",
        "width",
        "height",
        "steps",
        "scale",
        "sampler",
        "seed",
        "params_version",
        "qualityToggle",
        "autoSmea",
        "controlnet_strength",
        "controlnet_model",
        "reference_image_multiple",
        "reference_information_extracted_multiple",
        "reference_strength_multiple",
        "inpaintImg2ImgStrength",
        "characterPrompts",
        "v4_prompt",
        "v4_negative_prompt",
        "noise_schedule",
        "cfg_rescale",
        "dynamic_thresholding",
        "dynamic_thresholding_percentile",
        "dynamic_thresholding_mimic_scale",
        "skip_cfg_above_sigma",
        "skip_cfg_below_sigma",
        "prefer_brownian",
        "sm",
        "sm_dyn",
        "request_type",
        "image",
        "mask",
        "action",
        "requested_action",
        "xianyun_vibe",
        "vibe_transfer",
        "vibeTransfer",
        "vibe",
    }
)
SUPPORTED_ACTIONS = frozenset({"generate", "img2img", "inpaint", "infill"})
UNCOMPILED_INPUT_KEYS = ("image", "mask")
UNCOMPILED_VIBE_KEYS = ("xianyun_vibe", "vibe_transfer", "vibeTransfer", "vibe")


def _infer_model(source: str, explicit: str = "") -> str:
    """Prefer an explicit model field, then Source string, then current product default."""
    model = str(explicit or "").strip()
    if model.startswith("nai-diffusion-"):
        return model
    value = source or ""
    lower = value.lower()
    if "V4.5" in value or "v4.5" in lower:
        return "nai-diffusion-4-5-full"
    if "V4" in value or "v4" in lower:
        return "nai-diffusion-4-full"
    # Product default when metadata is silent.
    return "nai-diffusion-4-5-full"


def _normalized_v4_payloads(
    patched_comment: dict,
    *,
    base_caption: str,
    negative_prompt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    v4 = copy.deepcopy(patched_comment.get("v4_prompt") or {})
    if not isinstance(v4, dict):
        v4 = {}
    caption = copy.deepcopy(v4.get("caption") or {})
    if not isinstance(caption, dict):
        caption = {}
    caption["base_caption"] = str(caption.get("base_caption") or base_caption or "")
    character_captions = caption.get("char_captions")
    caption["char_captions"] = character_captions if isinstance(character_captions, list) else []
    v4["caption"] = caption
    v4["use_coords"] = bool(v4.get("use_coords", True))

    negative = copy.deepcopy(patched_comment.get("v4_negative_prompt") or {})
    if not isinstance(negative, dict):
        negative = {}
    negative_caption = copy.deepcopy(negative.get("caption") or {})
    if not isinstance(negative_caption, dict):
        negative_caption = {}
    negative_caption["base_caption"] = str(
        negative_caption.get("base_caption") or negative_prompt or ""
    )
    negative_characters = negative_caption.get("char_captions")
    if not isinstance(negative_characters, list):
        negative_characters = []
    if caption["char_captions"] and len(negative_characters) < len(caption["char_captions"]):
        padded = list(negative_characters)
        for item in caption["char_captions"][len(padded):]:
            centers = item.get("centers") if isinstance(item, dict) else None
            center = centers[0] if centers else {"x": 0.5, "y": 0.5}
            padded.append({"char_caption": "", "centers": [center]})
        negative_characters = padded
    negative_caption["char_captions"] = negative_characters
    negative["caption"] = negative_caption
    negative["use_coords"] = bool(negative.get("use_coords", v4.get("use_coords", True)))
    return v4, negative


def requested_action(patched_comment: dict) -> str:
    """Return the action the comment asked for. Compile still defaults to generate."""

    raw = str(
        patched_comment.get("requested_action") or patched_comment.get("action") or "generate"
    ).strip().lower()
    if raw in SUPPORTED_ACTIONS:
        return raw
    return "generate"


def collect_unknown_fields(patched_comment: dict) -> list[str]:
    return sorted(str(key) for key in patched_comment if str(key) not in KNOWN_COMMENT_KEYS)


def collect_unsupported_fields(patched_comment: dict) -> list[str]:
    """Fields that exist on the comment but are not compiled into the HTTP action."""

    unsupported: list[str] = []
    action = requested_action(patched_comment)
    if action != "generate":
        unsupported.append(f"action:{action}")
    for key in UNCOMPILED_INPUT_KEYS:
        if patched_comment.get(key):
            unsupported.append(key)
    for key in UNCOMPILED_VIBE_KEYS:
        if patched_comment.get(key):
            unsupported.append(key)
    return unsupported


def fit_opus_free_size(width: int, height: int) -> tuple[int, int, bool]:
    """Fit a size into the free-generation long-edge and pixel budgets."""

    if width <= 0 or height <= 0:
        return 832, 1216, True
    long_edge = max(width, height)
    pixel_count = width * height
    if long_edge <= MAX_FREE_LONG_EDGE and pixel_count <= MAX_FREE_PIXELS:
        return width, height, False
    scale = min(
        MAX_FREE_LONG_EDGE / long_edge,
        (MAX_FREE_PIXELS / pixel_count) ** 0.5,
    )
    new_width = max(64, int(width * scale // 64) * 64)
    new_height = max(64, int(height * scale // 64) * 64)
    while new_width * new_height > MAX_FREE_PIXELS:
        if new_width >= new_height and new_width > 64:
            new_width -= 64
        elif new_height > 64:
            new_height -= 64
        else:
            break
    return new_width, new_height, True


def build_generate_payload(
    patched_comment: dict,
    *,
    force_free: bool = True,
) -> dict[str, Any]:
    """Compile a Studio Draft comment into the current NovelAI request shape."""

    width = int(patched_comment.get("width") or 832)
    height = int(patched_comment.get("height") or 1216)
    steps = int(patched_comment.get("steps") or 28)
    resized = False
    if force_free:
        width, height, resized = fit_opus_free_size(width, height)
        steps = min(steps, MAX_FREE_STEPS)
    elif max(width, height) > MAX_FREE_LONG_EDGE * 2:
        width, height, _ = fit_opus_free_size(width, height)
        resized = True

    source = str(patched_comment.get("Source") or "")
    model = _infer_model(source, str(patched_comment.get("model") or ""))
    v4 = patched_comment.get("v4_prompt") or {}
    caption = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    base = str(caption.get("base_caption") or patched_comment.get("prompt") or "")
    negative_prompt = str(
        patched_comment.get("negative_prompt") or patched_comment.get("uc") or ""
    )
    v4_prompt, v4_negative_prompt = _normalized_v4_payloads(
        patched_comment,
        base_caption=base,
        negative_prompt=negative_prompt,
    )

    parameters: dict[str, Any] = {
        "params_version": int(patched_comment.get("params_version") or 3),
        "width": width,
        "height": height,
        "scale": float(patched_comment.get("scale") or 5),
        "sampler": str(patched_comment.get("sampler") or "k_euler_ancestral"),
        "steps": steps,
        "n_samples": 1,
        "ucPreset": 0,
        "qualityToggle": patched_comment.get("qualityToggle", True),
        "autoSmea": patched_comment.get("autoSmea", False),
        "negative_prompt": negative_prompt,
        "legacy": False,
        "legacy_uc": False,
        "legacy_v3_extend": False,
        "add_original_image": True,
        "controlnet_strength": float(patched_comment.get("controlnet_strength") or 1),
        "controlnet_model": patched_comment.get("controlnet_model"),
        "reference_image_multiple": patched_comment.get("reference_image_multiple") or [],
        "reference_information_extracted_multiple": (
            patched_comment.get("reference_information_extracted_multiple") or []
        ),
        "reference_strength_multiple": patched_comment.get("reference_strength_multiple") or [],
        "normalize_reference_strength_multiple": True,
        "inpaintImg2ImgStrength": float(patched_comment.get("inpaintImg2ImgStrength") or 1),
        "characterPrompts": patched_comment.get("characterPrompts") or [],
        "uc": negative_prompt,
        "v4_prompt": v4_prompt,
        "v4_negative_prompt": v4_negative_prompt,
        "noise_schedule": patched_comment.get("noise_schedule") or "karras",
        "cfg_rescale": patched_comment.get("cfg_rescale", 0),
        "dynamic_thresholding": patched_comment.get("dynamic_thresholding", False),
        "dynamic_thresholding_percentile": patched_comment.get(
            "dynamic_thresholding_percentile", 0.999
        ),
        "dynamic_thresholding_mimic_scale": patched_comment.get(
            "dynamic_thresholding_mimic_scale", 10.0
        ),
        "skip_cfg_above_sigma": patched_comment.get("skip_cfg_above_sigma"),
        "skip_cfg_below_sigma": patched_comment.get("skip_cfg_below_sigma", 0.0),
        "prefer_brownian": patched_comment.get("prefer_brownian"),
        "deliberate_euler_ancestral_bug": False,
        "sm": patched_comment.get("sm"),
        "sm_dyn": patched_comment.get("sm_dyn"),
    }
    if parameters["prefer_brownian"] is None:
        parameters["prefer_brownian"] = True
    parameters["use_coords"] = bool(v4_prompt.get("use_coords", True))
    seed = patched_comment.get("seed")
    if seed is not None and str(seed).strip() != "":
        try:
            seed_value = int(seed)
            if seed_value == -1 or seed_value >= 0:
                parameters["seed"] = seed_value
        except (TypeError, ValueError):
            pass

    has_image_input = bool(
        patched_comment.get("reference_image_multiple")
        or patched_comment.get("reference_information_extracted_multiple")
        or patched_comment.get("image")
        or patched_comment.get("mask")
    )
    free_eligible = (
        force_free
        and steps <= MAX_FREE_STEPS
        and max(width, height) <= MAX_FREE_LONG_EDGE
        and width * height <= MAX_FREE_PIXELS
        and not has_image_input
    )
    return {
        "input": base,
        "model": model,
        # Production HTTP path stays txt2img until a dedicated img2img/inpaint
        # compile lands. Requested/unsupported fields are reported, not dropped.
        "action": "generate",
        "requested_action": requested_action(patched_comment),
        "unsupported_fields": collect_unsupported_fields(patched_comment),
        "unknown_fields": collect_unknown_fields(patched_comment),
        "request_type": patched_comment.get("request_type") or "PromptGenerateRequest",
        "parameters": parameters,
        "free_eligible": free_eligible,
        "resized_for_free": resized,
        "width": width,
        "height": height,
        "steps": steps,
    }
