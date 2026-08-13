"""纯文本/方舟角色身份识别与提取（从 nai_char.py 拆出）。"""

from __future__ import annotations

from char_tag_db import pick_character_summary
from char_tag_db import split_prompt_tags
from functools import lru_cache
from nai_char_modules.slots import _format_char_slot, _sync_slot_contract_after_gender
from nai_char_modules.tag_constants import GENDER_NOISE as _GENDER_NOISE
from paths import DeferredDataPath, data_dir
from slot_gender import apply_slot_genders
from typing import Any
from pathlib import Path
import json
import re

DATA_DIR = DeferredDataPath(lambda: data_dir())


@lru_cache(maxsize=1)
def _ark_library_tags() -> dict[str, dict[str, Any]]:
    try:
        from ark_char_library import build_library

        data = build_library(force=False)
        items = list(data.get("female") or []) + list(data.get("male") or [])
        return {
            str(item.get("tag") or "").strip().lower(): item
            for item in items
            if str(item.get("tag") or "").strip()
        }
    except Exception:
        return {}


def _ark_lookup_key(tag: str) -> str:
    return str(tag or "").strip().lower().replace(" ", "_")


@lru_cache(maxsize=1)
def _danbooru_recognition_characters() -> set[str]:
    path = DATA_DIR / "danbooru_recognition.json"
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    tags = raw.get("characters") if isinstance(raw, dict) else []
    if not isinstance(tags, list):
        return set()
    return {str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}


def _clean_plain_identity_tag(tag: str) -> tuple[str, str, str]:
    from char_tag_db import weighted_tag_inner

    raw = str(tag or "").strip()
    inner = weighted_tag_inner(raw)
    target = (inner or raw).strip()
    target = target.strip("{}[] ").strip()
    while target.startswith("(") and target.endswith(")") and len(target) > 2:
        target = target[1:-1].strip()
    low = target.lower()
    compact = low.replace(" ", "_")
    return raw, low, compact


def _plain_identity_variants(tag: str) -> list[str]:
    """Return prompt and Danbooru spellings for a character identity.

    NAI prompts commonly use ``penance(Arknights)`` while Danbooru indexes use
    ``penance_(arknights)``.  Keep both spellings so recognition and later
    replacement agree on one canonical identity.
    """
    _raw, low, compact = _clean_plain_identity_tag(tag)
    out: list[str] = []
    for value in (
        low,
        compact,
        re.sub(r"(?<!_)\(", "_(", low),
        re.sub(r"(?<!_)\(", "_(", compact),
    ):
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _plain_identity_canonical_tag(tag: str) -> str:
    official_chars = _danbooru_recognition_characters()
    variants = _plain_identity_variants(tag)
    for value in reversed(variants):
        if value in official_chars:
            return value
    _raw, low, compact = _clean_plain_identity_tag(tag)
    return compact or low


def _is_strict_plain_character_tag(tag: str) -> bool:
    from char_tag_db import (
        is_action_phrase,
        is_appearance_tag,
        is_appearance_weight_block,
        is_body_tag,
        is_copyright_tag,
        is_gender_tag,
        is_generic_character_tag,
        is_identity_meta_noise,
        is_identity_noise_tag,
        weighted_tag_inner,
    )

    raw, low, compact = _clean_plain_identity_tag(tag)
    if (
        not low
        or low in _GENDER_NOISE
        or compact in _GENDER_NOISE
        or "artist:" in low
        or low.startswith(("artist ", "copyright:", "character:", "general:"))
        or low.startswith(("year ", "year_"))
        or is_gender_tag(low)
        or is_generic_character_tag(low)
        or is_identity_meta_noise(low)
        or is_identity_noise_tag(low)
    ):
        return False

    ark_key = _ark_lookup_key(low)
    if ark_key in _ark_library_tags():
        return True

    official_chars = _danbooru_recognition_characters()
    if any(value in official_chars for value in _plain_identity_variants(tag)):
        return True

    if (
        is_copyright_tag(low)
        or is_body_tag(low)
        or is_appearance_tag(low)
        or is_appearance_weight_block(raw)
    ):
        return False

    inner = weighted_tag_inner(raw)
    if inner:
        if raw.lstrip().startswith("-"):
            return False
        if is_action_phrase(inner):
            return False

    return False


def _plain_character_identity_tags(base_caption: str) -> list[str]:
    """Return explicit character identities from a plain prompt in prompt order."""
    from char_tag_db import identity_tag_display, split_prompt_tags, weighted_tag_inner

    out: list[str] = []
    seen: set[str] = set()
    for raw_tag in split_prompt_tags(base_caption):
        tag = str(raw_tag or "").strip()
        if not tag or tag.lstrip().startswith("-"):
            continue
        inner = weighted_tag_inner(tag) or tag
        unwrapped = inner.strip().strip("{}[] ")
        candidates = [tag]
        if "," in unwrapped:
            candidates = [
                part.strip().strip("{}[] ")
                for part in unwrapped.split(",")
                if part.strip().strip("{}[] ")
            ] + candidates
        for candidate in candidates:
            if not _is_strict_plain_character_tag(candidate):
                # A1111 风格权重块里角色名常粘连特征括号，如
                # ``chloe(princess connect!)(1st costume,sweaty untied costume``：
                # 截取 name(series) 前缀后再判定，避免把整块当噪音漏掉。
                # 角色名内还可能嵌套权重括号（如 ``Sagisawa Fumika ({{{{idol heroes}}}})``），
                # 需先剥离 ``{}`` 再截取；danbooru 名单里有的角色只有裸名
                # （如 sagisawa_fumika，无系列后缀），因此还要尝试不带系列的裸名。
                stripped = re.sub(r"[{}]+", "", candidate).strip()
                for probe in (stripped, candidate):
                    m = re.match(r"^[^,()]+\([^()]*\)", probe)
                    if m:
                        probe = m.group(0)
                    if _is_strict_plain_character_tag(probe):
                        candidate = probe
                        break
                    bare = re.match(r"^[^,()]+", probe)
                    if bare and _is_strict_plain_character_tag(bare.group(0).strip()):
                        candidate = bare.group(0).strip()
                        break
                if not _is_strict_plain_character_tag(candidate):
                    continue
            canonical = _plain_identity_canonical_tag(candidate)
            _raw, low, compact = _clean_plain_identity_tag(canonical)
            if low in seen or compact in seen:
                continue
            display = identity_tag_display(canonical).strip().lower()
            for key in (low, compact, display, display.replace(" ", "_")):
                if key:
                    seen.add(key)
            out.append(canonical)
    return out


def _plain_library_display_label(item: dict[str, Any], fallback_tag: str) -> str:
    from char_tag_db import identity_tag_display, pick_character_summary

    label = str(item.get("label") or "").strip()
    if label.lower() not in {"ai生成", "ai generated", "unknown", "unnamed"}:
        return label
    canonical = str(item.get("tag") or fallback_tag or "").strip()
    return (
        pick_character_summary(canonical, [canonical])
        or identity_tag_display(canonical)
        or canonical
    )


def _plain_identity_followup_features(tag: str, base_caption: str) -> str:
    """Extract A1111-style ``name(series)(feature1, feature2`` feature
    parentheses that trail the character identity, so those features
    (hair color, outfit, ...) travel with the slot on replacement."""
    variants = list(_plain_identity_variants(tag))
    for v in list(variants):
        variants.append(v.replace("_(", "("))
        variants.append(v.replace("_(", "(").replace("_", " "))
        variants.append(v.replace("_", " "))
    for variant in variants:
        idx = base_caption.find(variant)
        if idx < 0:
            continue
        tail = base_caption[idx + len(variant):]
        m = re.match(r"\s*\(\s*([^()]*?)(?:\{\{|\}\}|$)", tail)
        if not m:
            continue
        parts = [
            p.strip().strip("{}[] ")
            for p in m.group(1).split(",")
            if p.strip().strip("{}[] ")
        ]
        cleaned = ", ".join(parts)
        if cleaned:
            return cleaned
    return ""


def _chars_from_plain_character_prompt(
    base_caption: str,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Create virtual slots for explicit Danbooru/local character tags in a plain prompt."""
    from char_tag_db import identity_tag_display, pick_character_summary

    identity_tags = _plain_character_identity_tags(base_caption)
    if not identity_tags:
        return None

    library = _ark_library_tags()
    chars: list[dict[str, Any]] = []
    all_ark_library = True
    for i, tag in enumerate(identity_tags[:8]):
        _raw, low, compact = _clean_plain_identity_tag(tag)
        ark_key = _ark_lookup_key(low or compact)
        item = library.get(ark_key)
        if item:
            identity = list(item.get("identity") or [item.get("tag") or tag])
            caption = ", ".join(str(x) for x in identity if str(x or "").strip())
            gender = str(item.get("gender") or "").strip().lower()
            display_label = _plain_library_display_label(item, tag)
            ch = _format_char_slot(
                i,
                {
                    "char_caption": caption,
                    "uc_caption": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "summary": display_label,
                },
                caption,
                gender_hint=gender,
            )
            bundle = ch.get("bundle") if isinstance(ch.get("bundle"), dict) else {}
            ch["summary"] = display_label or str(ch.get("summary") or "")
            ch["identity_tags"] = [str(item.get("tag") or identity[0] or tag)]
            ch["display_name"] = ch["summary"] or ch["identity_tags"][0]
            ch["ark_library_match"] = True
            ch["ark_library_tag"] = str(item.get("tag") or "")
            ch["plain_character_tag"] = ch["identity_tags"][0]
            ch["bundle"] = {
                **bundle,
                "gender": gender or bundle.get("gender") or "unknown",
                "identity": identity,
            }
            chars.append(ch)
            continue

        all_ark_library = False
        caption = _plain_identity_canonical_tag(tag)
        # A1111 风格 ``name(series)(feature1, feature2`` 括号特征并入槽位，
        # 让「设为源 → 替换」时发色/服装等特征跟随角色一起替换。
        followup = _plain_identity_followup_features(tag, base_caption)
        if followup:
            caption = f"{caption}, {followup}"
        ch = _format_char_slot(
            i,
            {
                "char_caption": caption,
                "uc_caption": "",
                "center": {"x": 0.5, "y": 0.5},
            },
            caption,
        )
        bundle = ch.get("bundle") if isinstance(ch.get("bundle"), dict) else {}
        summary = (
            pick_character_summary(caption, list(bundle.get("identity") or []))
            or identity_tag_display(caption)
            or caption
        )
        ch["summary"] = summary
        ch["identity_tags"] = [_plain_identity_canonical_tag(tag)]
        ch["display_name"] = summary
        ch["plain_character_tag"] = caption
        ch["bundle"] = {
            **bundle,
            "identity": list(bundle.get("identity") or [caption]),
        }
        chars.append(ch)

    if not chars:
        return None
    apply_slot_genders(chars, base_caption=base_caption)
    _sync_slot_contract_after_gender(chars)
    layout = "plain_ark_library" if all_ark_library else "plain_character_tags"
    return chars, base_caption, layout


def _chars_from_plain_ark_prompt(
    base_caption: str,
) -> tuple[list[dict[str, Any]], str] | None:
    """Create a virtual slot when a plain prompt contains explicit local Ark tags."""
    from char_tag_db import is_character_tag, split_prompt_tags

    library = _ark_library_tags()
    if not library:
        return None
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in split_prompt_tags(base_caption):
        low = str(tag or "").strip().lower()
        key = _ark_lookup_key(low)
        if not key or key in seen:
            continue
        if not key.endswith("_(arknights)") or not is_character_tag(low):
            continue
        item = library.get(key)
        if not item:
            continue
        seen.add(key)
        matches.append(item)
    if not matches:
        return None

    chars: list[dict[str, Any]] = []
    for i, item in enumerate(matches[:6]):
        identity = list(item.get("identity") or [item.get("tag")])
        caption = ", ".join(str(x) for x in identity if str(x or "").strip())
        gender = str(item.get("gender") or "").strip().lower()
        display_label = _plain_library_display_label(
            item,
            str(item.get("tag") or ""),
        )
        ch = _format_char_slot(
            i,
            {
                "char_caption": caption,
                "uc_caption": "",
                "center": {"x": 0.5, "y": 0.5},
                "summary": display_label,
            },
            caption,
            gender_hint=gender,
        )
        bundle = ch.get("bundle") if isinstance(ch.get("bundle"), dict) else {}
        ch["summary"] = display_label or str(ch.get("summary") or "")
        ch["identity_tags"] = [str(item.get("tag") or identity[0] or "")]
        ch["display_name"] = ch["summary"] or ch["identity_tags"][0]
        ch["ark_library_match"] = True
        ch["ark_library_tag"] = str(item.get("tag") or "")
        ch["bundle"] = {
            **bundle,
            "gender": gender or bundle.get("gender") or "unknown",
            "identity": identity,
        }
        chars.append(ch)
    apply_slot_genders(chars, base_caption=base_caption)
    _sync_slot_contract_after_gender(chars)
    return chars, base_caption


def _chars_from_generic_plain_prompt(
    base_caption: str,
) -> tuple[list[dict[str, Any]], str] | None:
    """Create virtual slots for generic plain prompts containing gender indicators (e.g. 1girl, 1boy)."""
    from char_tag_db import split_prompt_tags, weighted_tag_inner

    # A negative NAI weight applies to the whole ``-N::...::`` block.  The
    # historical comma splitter flattened its inner ``3girls`` token and
    # accidentally created three replaceable roles.  Remove negative blocks
    # before deriving positive character counts, then unwrap positive weights.
    positive_caption = re.sub(
        r"(?<![\w.])-\d+(?:\.\d+)?::.*?::",
        "",
        str(base_caption or ""),
        flags=re.DOTALL,
    )
    tags: list[str] = []
    for raw_tag in split_prompt_tags(positive_caption):
        raw = str(raw_tag or "").strip()
        if not raw or raw.lstrip().startswith("-"):
            continue
        target = weighted_tag_inner(raw) or raw
        for part in str(target).split(","):
            normalized = part.strip().lower().strip("{}[]() :")
            if normalized:
                tags.append(normalized)
    
    female_count = 0
    male_count = 0
    
    # Identify explicit count tags first
    if "1girl" in tags:
        female_count = 1
    elif "2girls" in tags:
        female_count = 2
    elif "3girls" in tags:
        female_count = 3
    elif "4girls" in tags:
        female_count = 4
    elif "girls" in tags:
        female_count = 2
        
    if "1boy" in tags:
        male_count = 1
    elif "2boys" in tags:
        male_count = 2
    elif "3boys" in tags:
        male_count = 3
    elif "4boys" in tags:
        male_count = 4
    elif "boys" in tags:
        male_count = 2

    # Fallback to general gendered tags if no count tags are present
    if female_count == 0 and male_count == 0:
        has_female = False
        has_male = False
        from slot_gender import _token_gender
        for t in tags:
            g = _token_gender(t)
            if g == "female":
                has_female = True
            elif g == "male":
                has_male = True
        if has_female:
            female_count = 1
        if has_male:
            male_count = 1

    # Fallback to 1 female slot as the default if absolutely no gender/character tag was detected
    if female_count == 0 and male_count == 0:
        female_count = 1

    chars: list[dict[str, Any]] = []
    idx = 0
    
    for i in range(female_count):
        slot_tag = "1girl"
        char_caption = slot_tag
        if "solo" in tags and female_count == 1 and male_count == 0:
            char_caption = f"{slot_tag}, solo"
            
        ch = _format_char_slot(
            idx,
            {
                "char_caption": char_caption,
                "uc_caption": "",
                "center": {"x": 0.35 + 0.15 * idx, "y": 0.5},
                "summary": f"女槽 #{i+1}" if female_count > 1 else "女槽",
            },
            char_caption,
            gender_hint="female",
        )
        ch["summary"] = f"女槽 #{i+1}" if female_count > 1 else "女槽"
        ch["identity_tags"] = []
        ch["display_name"] = ch["summary"]
        ch["bundle"] = {
            "gender": "female",
            "identity": [],
            "body": [],
            "appearance": [],
            "creature": [],
            "action": []
        }
        chars.append(ch)
        idx += 1

    for i in range(male_count):
        slot_tag = "1boy"
        char_caption = slot_tag
        if "solo" in tags and male_count == 1 and female_count == 0:
            char_caption = f"{slot_tag}, solo"
            
        ch = _format_char_slot(
            idx,
            {
                "char_caption": char_caption,
                "uc_caption": "",
                "center": {"x": 0.35 + 0.15 * idx, "y": 0.5},
                "summary": f"男槽 #{i+1}" if male_count > 1 else "男槽",
            },
            char_caption,
            gender_hint="male",
        )
        ch["summary"] = f"男槽 #{i+1}" if male_count > 1 else "男槽"
        ch["identity_tags"] = []
        ch["display_name"] = ch["summary"]
        ch["bundle"] = {
            "gender": "male",
            "identity": [],
            "body": [],
            "appearance": [],
            "creature": [],
            "action": []
        }
        chars.append(ch)
        idx += 1

    apply_slot_genders(chars, base_caption=base_caption)
    _sync_slot_contract_after_gender(chars)
    return chars, base_caption
