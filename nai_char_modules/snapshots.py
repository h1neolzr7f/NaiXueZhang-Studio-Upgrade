"""Prompt metadata normalization and durable display snapshots."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def parse_comment(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_nested_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text == "[object Object]":
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except (SyntaxError, ValueError):
        return {}


def normalize_comment(comment: dict) -> dict:
    if not isinstance(comment, dict):
        return {}
    normalized = dict(comment)
    for key in ("v4_prompt", "v4_negative_prompt"):
        if key in normalized:
            normalized[key] = _parse_nested_dict(normalized.get(key))
    return normalized


def effective_comment(ai_json: dict) -> dict:
    parsed = parse_comment(ai_json.get("Comment"))
    return normalize_comment(parsed if parsed else ai_json)


def prompt_snapshot_from_comment(comment: dict) -> dict[str, Any]:
    v4 = comment.get("v4_prompt") or {}
    caption = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    base = str(caption.get("base_caption") or comment.get("prompt") or "")
    characters: list[dict[str, Any]] = []
    for index, item in enumerate(caption.get("char_captions") or []):
        if not isinstance(item, dict):
            continue
        centers = item.get("centers") or [{"x": 0.5, "y": 0.5}]
        center = centers[0] if isinstance(centers[0], dict) else {"x": 0.5, "y": 0.5}
        characters.append(
            {
                "index": index,
                "caption": str(item.get("char_caption") or ""),
                "center": center,
            }
        )
    return {
        "base_caption": base[:2000],
        "char_captions": characters,
        "uc": str(comment.get("uc") or "")[:800],
        "seed": comment.get("seed"),
        "steps": comment.get("steps"),
        "width": comment.get("width"),
        "height": comment.get("height"),
    }


def comment_from_png(path: Path | str) -> dict[str, Any] | None:
    png_path = Path(path)
    if not png_path.exists():
        return None
    try:
        from PIL import Image

        with Image.open(png_path) as image:
            raw = (image.text or {}).get("Comment")
        comment = parse_comment(raw) if raw else {}
        if comment:
            return comment
    except Exception as exc:
        _logger.warning("PNG 内嵌 Comment 解析失败（%s）: %s", png_path, exc)
        return None
    try:
        from nai_image_metadata import parse_nai_image

        parsed = parse_nai_image(png_path)
        if not parsed.accepted:
            return None
        restored = (parsed.canonical_metadata() or {}).get("Comment")
        return restored if isinstance(restored, dict) and restored else None
    except Exception as exc:
        _logger.warning("PNG stealth/NAI Comment 回退失败（%s）: %s", png_path, exc)
        return None


def prompt_snapshot_from_png(path: Path | str) -> dict[str, Any] | None:
    comment = comment_from_png(path)
    if not comment:
        return None
    snapshot = prompt_snapshot_from_comment(comment)
    return snapshot if snapshot.get("base_caption") or snapshot.get("char_captions") else None
