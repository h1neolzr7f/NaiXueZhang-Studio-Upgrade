"""First-party NAI V4/V5 prompt flow for Studio and Butler drafts.

Borrow only the writing *behavior* used by community V5 skills:

- known copyright characters stay identity-minimal
- appearance/clothing stay in character slots; action/camera/scene stay in base
- demand is graded so a formed request is not padded

This module does not load third-party Skill files, does not add a plugin
loader, and does not implement manga/storyboard regional prompting.
"""

from __future__ import annotations

import re
from typing import Any

from char_tag_db import (
    classify_caption_buckets,
    is_appearance_tag,
    is_body_tag,
    is_character_tag,
    is_gender_tag,
    split_prompt_tags,
)

DEMAND_FORMED = "A"
DEMAND_SUBJECT = "B"
DEMAND_DIRECTION = "C"
DEMAND_BLANK = "D"

_COUNT_RE = re.compile(r"^(?P<n>\d+)(?P<kind>girls?|boys?|others?)$", re.I)
_QUALITY_TAGS = frozenset(
    {
        "masterpiece",
        "best quality",
        "amazing quality",
        "great quality",
        "high quality",
        "highres",
        "absurdres",
        "very aesthetic",
        "newest",
    }
)
_CAMERA_HINTS = (
    "from above",
    "from below",
    "from side",
    "from behind",
    "from front",
    "cowboy shot",
    "full body",
    "upper body",
    "close-up",
    "close up",
    "portrait",
    "looking at viewer",
    "looking at another",
    "looking away",
    "eye contact",
    "pov",
    "wide shot",
    "medium shot",
)
_SCENE_HINTS = (
    "indoors",
    "outdoors",
    "background",
    "scenery",
    "bedroom",
    "classroom",
    "rooftop",
    "street",
    "night",
    "rain",
    "sunset",
    "interior",
    "cityscape",
    "forest",
    "beach",
)
_OUTFIT_OVERRIDE_RE = re.compile(
    r"换装|换衣|睡衣|校服|指定衣服|穿上|改成.+衣|outfit|costume|wearing|pajamas|uniform",
    re.I,
)
_LOOK_FEATURE_RE = re.compile(
    r"\b(hair|eyes|skin|breasts?|chest)\b",
    re.I,
)
_EXPRESSION_KEEP_RE = re.compile(
    r"\b(smile|grin|blush|frown|angry|sad|crying|tears|expression|closed eyes|open mouth)\b",
    re.I,
)
_CLOTHING_HINTS = (
    "dress",
    "skirt",
    "shirt",
    "jacket",
    "coat",
    "uniform",
    "armor",
    "cape",
    "hoodie",
    "sweater",
    "kimono",
    "sailor",
    "gloves",
    "boots",
    "socks",
    "stockings",
    "thighhigh",
    "pantyhose",
    "bikini",
    "swimsuit",
    "panties",
    "bra",
    "hat",
    "ribbon",
    "necktie",
    "bow",
    "shoes",
    "heels",
    "pajamas",
    "pyjamas",
)
_SUBJECT_FROM_COUNT = {
    "girl": "girl",
    "girls": "girl",
    "boy": "boy",
    "boys": "boy",
    "other": "other",
    "others": "other",
}
_SLOT_SUBJECTS = frozenset({"girl", "boy", "other"})
_NOT_IDENTITY = _SLOT_SUBJECTS | frozenset(
    {
        "1girl",
        "1boy",
        "1other",
        "solo",
        "multiple girls",
        "multiple boys",
        "multiple others",
    }
)


def playbook_optimizer_rules() -> str:
    """Short first-party rules injected into the LLM optimizer. Not a third-party Skill."""

    return (
        "按 NAI V4/V5 槽位写，不要写成 SD/Comfy 语法。"
        "主提示词只写人数、镜头、动作、场景、光影和质量词；外貌、发型、瞳色、服装、配饰写进 char_captions。"
        "模型已认识的版权角色默认只保留角色身份和 girl/boy，不要写默认头发、眼睛、胸围和默认衣服；用户明确换装时才写服装。"
        "人数 tag（如 2girls）只出现在主提示词一次；角色槽只写 girl 或 boy。"
        "已成型的需求不要擅自加戏；只有主体时只补必要的场景和光，不要另起一套故事。"
        "不要输出漫画分镜或区域格子方案。"
    )


def outfit_override_requested(intent: str, texts: dict[str, Any] | None = None) -> bool:
    parts = [str(intent or "")]
    if isinstance(texts, dict):
        parts.extend(
            [
                str(texts.get("prompt") or ""),
                str(texts.get("base_caption") or ""),
                " ".join(str(item or "") for item in list(texts.get("char_captions") or [])),
            ]
        )
    return bool(_OUTFIT_OVERRIDE_RE.search(" ".join(parts)))


def classify_demand(intent: str = "", texts: dict[str, Any] | None = None) -> str:
    payload = texts if isinstance(texts, dict) else {}
    blob = " ".join(
        part
        for part in (
            str(intent or "").strip(),
            str(payload.get("prompt") or "").strip(),
            str(payload.get("base_caption") or "").strip(),
            " ".join(str(item or "") for item in list(payload.get("char_captions") or [])),
        )
        if part
    )
    if not blob:
        return DEMAND_BLANK
    buckets = classify_caption_buckets(blob)
    has_identity = bool(buckets.get("identity")) or any(
        is_character_tag(tag) for tag in split_prompt_tags(blob)
    )
    has_action = bool(buckets.get("action"))
    has_scene = any(hint in blob.casefold() for hint in _SCENE_HINTS)
    if has_identity and (has_action or has_scene or len(str(intent or "").strip()) >= 24):
        return DEMAND_FORMED
    if has_identity:
        return DEMAND_SUBJECT
    if str(intent or "").strip() or blob:
        return DEMAND_DIRECTION
    return DEMAND_BLANK


def apply_v5_playbook(
    texts: dict[str, Any],
    *,
    intent: str = "",
    promote_slots: bool = True,
) -> dict[str, Any]:
    """Return cleaned texts plus a machine-readable report. Never calls NAI."""

    source = {
        "prompt": str((texts or {}).get("prompt") or "").strip(),
        "base_caption": str((texts or {}).get("base_caption") or (texts or {}).get("prompt") or "").strip(),
        "uc": str((texts or {}).get("uc") or "").strip(),
        "char_captions": [
            str(item or "").strip()
            for item in list((texts or {}).get("char_captions") or [])
            if str(item or "").strip() or item == ""
        ],
    }
    keep_outfit = outfit_override_requested(intent, source)
    demand = classify_demand(intent, source)
    base_tags = split_prompt_tags(source["base_caption"] or source["prompt"])
    slot_tags = [split_prompt_tags(caption) for caption in source["char_captions"]]
    if promote_slots and not any(slot_tags):
        slot_tags = _promote_slots_from_base(base_tags)
        if slot_tags:
            identities = { _tag_key(tag) for group in slot_tags for tag in group if _is_identity(tag) }
            base_tags = [tag for tag in base_tags if _tag_key(tag) not in identities]

    moved_to_slots: list[str] = []
    moved_to_base: list[str] = []
    stripped: list[str] = []

    isolated_base, isolated_slots, moved_to_slots, moved_to_base = _isolate_slots(base_tags, slot_tags)
    cleaned_slots: list[list[str]] = []
    for tags in isolated_slots:
        kept, dropped = _minimize_known_character(tags, keep_outfit=keep_outfit)
        cleaned_slots.append(kept)
        stripped.extend(dropped)

    normalized_base, normalized_slots = _normalize_counts(isolated_base, cleaned_slots)
    normalized_base = _quality_last(normalized_base)

    base_text = _join_tags(normalized_base)
    slot_texts = [_join_tags(tags) for tags in normalized_slots if tags]
    result_texts = {
        "prompt": base_text,
        "base_caption": base_text,
        "uc": source["uc"],
        "char_captions": slot_texts,
    }
    return {
        "texts": result_texts,
        "demand": demand,
        "outfit_override": keep_outfit,
        "copyright_minimal": bool(stripped),
        "stripped": _unique(stripped),
        "moved_to_slots": _unique(moved_to_slots),
        "moved_to_base": _unique(moved_to_base),
        "notes": _report_notes(demand, stripped, moved_to_slots, moved_to_base, keep_outfit),
    }


def apply_playbook_to_comment_texts(
    texts: dict[str, Any],
    *,
    intent: str = "",
) -> dict[str, Any]:
    """Convenience wrapper used by optimizer and Butler draft prep."""

    report = apply_v5_playbook(texts, intent=intent, promote_slots=True)
    return report


def _promote_slots_from_base(base_tags: list[str]) -> list[list[str]]:
    identities = [tag for tag in base_tags if _is_identity(tag)]
    if not identities:
        return []
    slots: list[list[str]] = []
    for identity in identities:
        subject = _infer_subject(base_tags)
        slot = [subject, identity] if subject else [identity]
        slots.append(slot)
    return slots


def _isolate_slots(
    base_tags: list[str], slot_tags: list[list[str]]
) -> tuple[list[str], list[list[str]], list[str], list[str]]:
    if not slot_tags:
        return list(base_tags), [], [], []

    keep_base: list[str] = []
    extra_for_slots: list[str] = []
    moved_to_slots: list[str] = []
    for tag in base_tags:
        if _is_identity(tag) or _is_look_or_clothes(tag):
            extra_for_slots.append(tag)
            moved_to_slots.append(tag)
        else:
            keep_base.append(tag)

    new_slots: list[list[str]] = []
    moved_to_base: list[str] = []
    for index, tags in enumerate(slot_tags):
        kept: list[str] = []
        for tag in tags:
            if _belongs_in_base(tag):
                keep_base.append(tag)
                moved_to_base.append(tag)
            else:
                kept.append(tag)
        if index == 0:
            kept.extend(extra_for_slots)
        new_slots.append(kept)
    if extra_for_slots and not slot_tags:
        new_slots.append(extra_for_slots)
    return keep_base, new_slots, moved_to_slots, moved_to_base


def _minimize_known_character(tags: list[str], *, keep_outfit: bool) -> tuple[list[str], list[str]]:
    if not any(_is_identity(tag) for tag in tags):
        return list(tags), []
    kept: list[str] = []
    dropped: list[str] = []
    for tag in tags:
        if _is_default_look(tag) or (not keep_outfit and _is_clothing(tag)):
            dropped.append(tag)
            continue
        kept.append(tag)
    return kept, dropped


def _normalize_counts(
    base_tags: list[str], slot_tags: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    counts = [tag for tag in base_tags if _count_kind(tag)]
    if not counts:
        inferred = _infer_count_from_slots(slot_tags)
        if inferred:
            counts = [inferred]
    base = [tag for tag in base_tags if not _count_kind(tag)]
    if counts:
        base.insert(0, counts[0])
    new_slots: list[list[str]] = []
    for tags in slot_tags:
        subject = ""
        cleaned: list[str] = []
        for tag in tags:
            kind = _count_kind(tag)
            if kind:
                subject = _SUBJECT_FROM_COUNT.get(kind, "")
                continue
            if _tag_key(tag) in {"girl", "boy", "other"} and not subject:
                subject = _tag_key(tag)
                continue
            cleaned.append(tag)
        if not subject:
            subject = _infer_subject(tags) or _infer_subject(base_tags)
        ordered = ([subject] if subject else []) + cleaned
        new_slots.append(_unique(ordered))
    return _unique(base), new_slots


def _quality_last(tags: list[str]) -> list[str]:
    body = [tag for tag in tags if _tag_key(tag) not in _QUALITY_TAGS]
    tail = [tag for tag in tags if _tag_key(tag) in _QUALITY_TAGS]
    return body + tail


def _belongs_in_base(tag: str) -> bool:
    low = _tag_key(tag)
    if low in _SLOT_SUBJECTS:
        return False
    if _count_kind(tag):
        return True
    if low in _QUALITY_TAGS:
        return True
    if any(hint == low or hint in low for hint in _CAMERA_HINTS):
        return True
    if any(hint == low or f" {hint} " in f" {low} " for hint in _SCENE_HINTS):
        return True
    buckets = classify_caption_buckets(tag)
    if buckets.get("action") and not _is_look_or_clothes(tag) and not _is_identity(tag):
        return True
    return False


def _is_identity(tag: str) -> bool:
    if _count_kind(tag) or _tag_key(tag) in _NOT_IDENTITY:
        return False
    if is_character_tag(tag):
        return True
    buckets = classify_caption_buckets(tag)
    return bool(buckets.get("identity"))


def _is_look_or_clothes(tag: str) -> bool:
    return _is_default_look(tag) or _is_clothing(tag)


def _is_default_look(tag: str) -> bool:
    if _EXPRESSION_KEEP_RE.search(tag) and "hair" not in _tag_key(tag):
        return False
    if is_body_tag(tag) and re.search(r"\bbreasts?\b", _tag_key(tag)):
        return True
    if is_appearance_tag(tag) and _LOOK_FEATURE_RE.search(_tag_key(tag).replace("_", " ")):
        return True
    return bool(_LOOK_FEATURE_RE.search(_tag_key(tag).replace("_", " ")))


def _is_clothing(tag: str) -> bool:
    low = _tag_key(tag).replace("_", " ")
    if any(hint in low for hint in _CLOTHING_HINTS):
        return True
    return is_appearance_tag(tag) and any(hint in low for hint in ("wear", "cloth", "outfit"))


def _count_kind(tag: str) -> str:
    match = _COUNT_RE.match(_tag_key(tag).replace(" ", ""))
    if not match:
        return ""
    return match.group("kind").lower()


def _infer_count_from_slots(slot_tags: list[list[str]]) -> str:
    girls = sum(1 for tags in slot_tags if _infer_subject(tags) == "girl")
    boys = sum(1 for tags in slot_tags if _infer_subject(tags) == "boy")
    if girls >= 2:
        return f"{girls}girls"
    if boys >= 2:
        return f"{boys}boys"
    if girls == 1 and boys == 0:
        return "1girl"
    if boys == 1 and girls == 0:
        return "1boy"
    if girls and boys:
        return f"{girls + boys}girls" if girls >= boys else f"{girls + boys}boys"
    return ""


def _infer_subject(tags: list[str]) -> str:
    for tag in tags:
        kind = _count_kind(tag)
        if kind:
            return _SUBJECT_FROM_COUNT.get(kind, "")
        key = _tag_key(tag)
        if key in {"girl", "boy", "other"}:
            return key
        if is_gender_tag(tag):
            if key in {"1girl", "girl", "female"}:
                return "girl"
            if key in {"1boy", "boy", "male"}:
                return "boy"
    return ""


def _join_tags(tags: list[str]) -> str:
    return ", ".join(tag for tag in tags if str(tag).strip())


def _tag_key(tag: str) -> str:
    return str(tag or "").strip().strip("{}[]").strip().casefold()


def _unique(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        key = _tag_key(tag)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _report_notes(
    demand: str,
    stripped: list[str],
    moved_to_slots: list[str],
    moved_to_base: list[str],
    keep_outfit: bool,
) -> str:
    bits = [f"需求分档 {demand}"]
    if stripped:
        bits.append("已去掉版权角色的默认外貌/服装")
    if moved_to_slots:
        bits.append("外貌已移入角色槽")
    if moved_to_base:
        bits.append("动作/镜头已移回主提示词")
    if keep_outfit:
        bits.append("按换装要求保留服装")
    return "；".join(bits)
