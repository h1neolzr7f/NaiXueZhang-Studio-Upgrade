"""闲云 payload / vibe translation helpers."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import mimetypes
import random
import re
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image, UnidentifiedImageError

from generated_gallery import register_generated, _group_key
from local_secrets import (
    PREFIX as SECRET_PREFIX,
    SecretProtectionUnavailable,
    protect_secret,
    unprotect_secret,
)
from atomic_io import atomic_write_text
from nai_char import build_generate_payload, prompt_snapshot_from_comment
from nai_prompt_profiles import apply_prompt_profile_to_comment
from usage_ledger import record_usage
from nai.constants import (
    PROVIDER_NOVELAI,
    PROVIDER_UNKNOWN,
    PROVIDER_XIANYUN,
)
from nai.errors import GenerationProviderError
from nai.facade import api


def _clean_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}



def _read_image_reference(raw: Any) -> Any:
    if isinstance(raw, dict):
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if key in {
                "image",
                "image_url",
                "image_base64",
                "base64",
                "path",
                "file",
                "url",
                "reference_image",
                "referenceImage",
            }:
                out[key] = api._read_image_reference(value)
            else:
                out[key] = value
        return api._clean_none_values(out)
    if not isinstance(raw, str):
        return raw

    text = raw.strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://", "data:image/")):
        return text
    try:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_file():
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{encoded}"
    except Exception:
        pass
    return text



def _as_list(value: Any) -> list[Any]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]



def _truthy_config(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)



def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, "", [], {}):
            return mapping.get(key)
    return None



def _collect_xianyun_vibe_candidates(
    patched_comment: dict[str, Any] | None,
    payload_info: dict[str, Any],
    body: dict[str, Any],
) -> list[Any]:
    params = body.get("parameters") or {}
    candidates: list[Any] = []
    sources = [patched_comment or {}, payload_info, params]
    config_keys = (
        "xianyun_vibe",
        "xianyun_vibe_transfer",
        "vibe_transfer",
        "vibeTransfer",
        "vibe",
        "character_transfer",
        "characterTransfer",
    )
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in config_keys:
            value = source.get(key)
            if value not in (None, "", False, [], {}):
                candidates.append(value)

        nai_images = api._first_present(
            source,
            (
                "reference_image_multiple",
                "reference_images",
                "referenceImages",
                "reference_image",
                "referenceImage",
            ),
        )
        nai_strength = api._first_present(
            source,
            ("reference_strength_multiple", "reference_strength", "referenceStrength"),
        )
        if nai_images is not None or nai_strength is not None:
            candidates.append(
                {
                    "images": nai_images,
                    "strength": nai_strength,
                    "information_extracted": api._first_present(
                        source,
                        (
                            "reference_information_extracted_multiple",
                            "information_extracted",
                            "informationExtracted",
                        ),
                    ),
                }
            )
    return candidates



def _normalize_xianyun_vibe_config(config: Any) -> dict[str, Any]:
    if isinstance(config, str):
        config = {"images": [config]}
    elif isinstance(config, list):
        config = {"images": config}
    elif not isinstance(config, dict):
        return {}

    if "enabled" in config and not api._truthy_config(config.get("enabled")):
        return {}

    raw_images = api._first_present(
        config,
        (
            "images",
            "image",
            "image_url",
            "image_urls",
            "image_base64",
            "reference_image",
            "reference_images",
            "referenceImage",
            "referenceImages",
            "reference_image_multiple",
            "vibe_image",
            "vibe_images",
            "path",
        ),
    )
    references = [
        api._read_image_reference(item)
        for item in api._as_list(raw_images)
        if item not in (None, "", False)
    ]
    if not references:
        return {}

    strength = api._first_present(
        config,
        (
            "strength",
            "reference_strength",
            "referenceStrength",
            "reference_strength_multiple",
            "character_strength",
            "characterStrength",
        ),
    )
    if strength is None:
        strength = 0.6
    strengths = api._as_list(strength)
    if references and len(strengths) == 1:
        strengths = strengths * len(references)

    info = api._first_present(
        config,
        (
            "information_extracted",
            "informationExtracted",
            "reference_information_extracted",
            "reference_information_extracted_multiple",
        ),
    )
    if info is None:
        info = 1.0
    information = api._as_list(info)
    if references and len(information) == 1:
        information = information * len(references)

    payload = {
        "enabled": True,
        "images": references,
        "strength": strength,
        "reference_image_multiple": references,
        "reference_strength_multiple": strengths,
        "reference_information_extracted_multiple": information,
    }
    for key in (
        "mode",
        "preset",
        "model",
        "mask",
        "mask_image",
        "maskImage",
        "character_id",
        "characterId",
    ):
        if key in config and config.get(key) not in (None, "", [], {}):
            payload[key] = api._read_image_reference(config.get(key))
    return api._clean_none_values(payload)



def _xianyun_vibe_payload(
    patched_comment: dict[str, Any] | None,
    payload_info: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for candidate in api._collect_xianyun_vibe_candidates(patched_comment, payload_info, body):
        vibe = api._normalize_xianyun_vibe_config(candidate)
        if not vibe:
            continue
        merged.update(vibe)

    if not merged:
        return {}

    references = merged.get("reference_image_multiple") or merged.get("images") or []
    strengths = merged.get("reference_strength_multiple") or []
    information = merged.get("reference_information_extracted_multiple") or []
    transfer = api._clean_none_values(
        {
            "enabled": True,
            "images": references,
            "reference_image_multiple": references,
            "reference_strength_multiple": strengths,
            "reference_information_extracted_multiple": information,
            "strength": merged.get("strength"),
        }
    )
    return api._clean_none_values(
        {
            "reference_image_multiple": references,
            "reference_strength_multiple": strengths,
            "reference_information_extracted_multiple": information,
            "reference_images": references,
            "referenceImages": references,
            "vibe_transfer": transfer,
            "vibeTransfer": transfer,
            "character_transfer": transfer,
            "characterTransfer": transfer,
        }
    )



def _xianyun_raw_extra(patched_comment: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(patched_comment, dict):
        return {}
    extra: dict[str, Any] = {}
    for key in ("xianyun_extra", "xianyun_payload", "xianyun_request"):
        value = patched_comment.get(key)
        if isinstance(value, dict):
            extra.update(value)
    return api._clean_none_values(extra)



def _xianyun_body_from_payload(
    payload_info: dict[str, Any],
    body: dict[str, Any],
    patched_comment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = body.get("parameters") or {}
    negative = str(
        params.get("negative_prompt")
        or params.get("uc")
        or ""
    )
    seed = params.get("seed")
    if seed is None:
        seed = random.randint(0, 999_999_999)
    req = {
        "model": body.get("model") or payload_info.get("model") or "nai-diffusion-4-full",
        "positivePrompt": body.get("input") or "",
        "negativePrompt": negative,
        "scale": float(params.get("scale") or 5),
        "steps": int(params.get("steps") or payload_info.get("steps") or 28),
        "width": int(params.get("width") or payload_info.get("width") or 832),
        "height": int(params.get("height") or payload_info.get("height") or 1216),
        "promptGuidanceRescale": float(params.get("cfg_rescale") or 0),
        "noise_schedule": params.get("noise_schedule") or "karras",
        "seed": str(seed),
        "sampler": params.get("sampler") or "k_euler_ancestral",
        "sm": bool(params.get("sm") or False),
        "sm_dyn": bool(params.get("sm_dyn") or False),
        "decrisp": False,
        "variety": False,
        "v4_prompt_char_captions": (
            ((params.get("v4_prompt") or {}).get("caption") or {}).get("char_captions")
            if isinstance(params.get("v4_prompt"), dict)
            else None
        ),
        "v4_negative_prompt_char_captions": (
            ((params.get("v4_negative_prompt") or {}).get("caption") or {}).get("char_captions")
            if isinstance(params.get("v4_negative_prompt"), dict)
            else None
        ),
        "use_coords": bool(
            (params.get("v4_prompt") or {}).get("use_coords", True)
            if isinstance(params.get("v4_prompt"), dict)
            else True
        ),
    }
    req.update(api._xianyun_vibe_payload(patched_comment, payload_info, body))
    req.update(api._xianyun_raw_extra(patched_comment))
    return req

