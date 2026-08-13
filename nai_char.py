"""NAI v4 角色槽位解析、克隆/替换、去尼净化与生图 payload 构建。"""

from __future__ import annotations

import copy
import ast
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from aitag_core.prompt import tokenize_prompt
from aitag_core.recognition import analyze_slot_caption, match_oc_preset
from aitag_core.storage import load_image_json
from aitag_core.transform import plan_replacement
from char_marker import marker_label, parse_char_marker_layout, rebuild_char_marker_prompt
from char_swap_config import load_config as load_char_swap_config
from char_tag_db import classify_caption_buckets, pick_character_summary
from slot_gender import apply_slot_genders, indices_for_gender, slot_gender_of
from gallery_catalog import normalize_gallery_id

# --- 拆分模块回填（facade 再导出，保持 from nai_char import X 兼容）---
from nai_char_modules.tag_constants import GENDER_NOISE as _GENDER_NOISE
from nai_char_modules.oc_caption import (
    _OC_BODY_TYPE_HINTS,
    _OC_EXPRESSION_KEEP,
    _OC_GENDER_SKIP,
    _OC_POSE_DEFER_HINTS,
    _OC_POSE_PRIORITY_HINTS,
    _action_display_tags,
    _appearance_display_tags,
    _identity_display_tags,
    _is_oc_like_caption,
    _oc_appearance_parts,
    _oc_caption_preview,
    _oc_display_tags,
    _slot_matches_oc_preset,
    _split_scene_for_oc_merge,
)
from nai_char_modules.slots import (
    _UNKNOWN_ROLE_DISPLAY,
    _format_char_slot,
    _infer_slot_gender,
    _slot_gender,
    _sync_slot_contract_after_gender,
    bundle_from_caption,
)
from nai_char_modules.plain_identity import (
    _ark_library_tags,
    _ark_lookup_key,
    _chars_from_generic_plain_prompt,
    _chars_from_plain_ark_prompt,
    _chars_from_plain_character_prompt,
    _clean_plain_identity_tag,
    _danbooru_recognition_characters,
    _is_strict_plain_character_tag,
    _plain_character_identity_tags,
    _plain_identity_canonical_tag,
    _plain_identity_followup_features,
    _plain_identity_variants,
    _plain_library_display_label,
)
from nai_char_modules.bundle_merge import (
    _APPEARANCE_WEIGHT_HINTS,
    _CREATURE_ACTION_DROP,
    _SCENE_BODY_HINTS,
    _apply_replaced_char_state,
    _enrich_bundle_appearance,
    _is_oc_bundle,
    _oc_preset_summary,
    _preserve_action_tags,
    _preserve_scene_tags,
    _preserved_target_action_tags,
    _split_creature_parts,
    _strip_swap_appearance,
    _weighted_block_is_appearance,
    merge_bundle,
    strip_creature_tags_from_caption,
)

ROOT = Path(__file__).resolve().parent
from paths import DeferredDataPath, data_dir

_logger = logging.getLogger(__name__)

DATA_DIR = DeferredDataPath(lambda: data_dir())

BATCH_TARGET_MAX = 250


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _presets() -> dict:
    return _load_json(DATA_DIR / "char_presets.json")


def _split_tags(text: str) -> list[str]:
    from char_tag_db import split_prompt_tags

    return split_prompt_tags(text)


def _join_tags(tags: list[str]) -> str:
    return ", ".join(tags)


def classify_tags(caption: str) -> dict[str, list[str]]:
    """使用本地 char_tag_index 分类，带 LRU 缓存。"""
    return classify_caption_buckets(caption)



_UNKNOWN_IDENTITY_NOISE = {
    "\u5973\u69fd",
    "\u7537\u69fd",
    "",
    "unknown",
    "unknown_character",
    "未知",
    "未知角色",
    "未知男角色",
    "未知女角色",
}

_ALL_FEMALE_TARGETS = frozenset({"all_female", "all_females", "all_female_slots"})
_ALL_MALE_TARGETS = frozenset({"all_male", "all_males", "all_male_slots"})


def _identity_match_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^\d+(?:\.\d+)?::", "", text)
    text = re.sub(r"::$", "", text)
    text = text.strip("{}[]() ")
    key = re.sub(r"\s+", "_", text)
    if key in _GENDER_NOISE or key in _UNKNOWN_IDENTITY_NOISE:
        return ""
    if key.startswith(("\u5973\u69fd", "\u7537\u69fd")):
        return ""
    return key


def _slot_identity_keys(ch: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    def add(value: Any) -> None:
        key = _identity_match_key(value)
        if key and not key.startswith("未知"):
            keys.add(key)

    add(ch.get("ark_library_tag"))
    add(ch.get("oc_label"))
    add(ch.get("summary"))
    add(ch.get("display_name"))
    for tag in ch.get("identity_tags") or []:
        add(tag)
    bundle = ch.get("bundle") if isinstance(ch.get("bundle"), dict) else {}
    for tag in bundle.get("identity") or []:
        add(tag)
    caption = str(ch.get("char_caption") or "")
    if caption:
        buckets = classify_tags(caption)
        for tag in buckets.get("identity") or []:
            add(tag)
        add(pick_character_summary(caption, buckets.get("identity") or []))
    return keys


def _payload_identity_keys(payload: dict[str, Any]) -> set[str]:
    raw = (
        payload.get("match_identity")
        or payload.get("source_identity")
        or payload.get("source_identity_keys")
        or payload.get("match_identity_keys")
    )
    if raw is None:
        return set()
    values = raw if isinstance(raw, list) else [raw]
    return {key for key in (_identity_match_key(v) for v in values) if key}


def _payload_has_identity_filter(payload: dict[str, Any]) -> bool:
    return any(
        payload.get(key) is not None
        for key in (
            "match_identity",
            "source_identity",
            "source_identity_keys",
            "match_identity_keys",
        )
    )


def _is_all_gender_target(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in _ALL_FEMALE_TARGETS or text in _ALL_MALE_TARGETS


def _requires_identity_guard(payload: dict[str, Any]) -> bool:
    """Only cross-page/source-matched all-gender replacement needs an identity guard."""
    return bool(payload.get("require_match_identity") or payload.get("require_identity_guard"))


def _format_transform_chars(
    chars: list[dict[str, Any]],
    base_caption: str,
    replaced_genders: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    out_chars = []
    for i, ch in enumerate(chars):
        cap = str(ch.get("char_caption") or "")
        out_chars.append(
            _format_char_slot(
                i,
                ch,
                cap,
                gender_hint=(replaced_genders or {}).get(i, ""),
            )
        )
    apply_slot_genders(out_chars, base_caption=str(base_caption or ""))
    _sync_slot_contract_after_gender(out_chars)
    return out_chars


def _unchanged_transform_result(
    data: dict[str, Any],
    *,
    mode: str,
    work_id: int,
    page_index: int,
    message: str,
    include_style_slots: bool = True,
) -> dict[str, Any]:
    style_slots = (
        extract_style_slots_from_comment(data["comment"])
        if include_style_slots
        else []
    )
    return {
        "ok": True,
        "skipped": True,
        "message": message,
        "mode": mode,
        "work_id": work_id,
        "page_index": page_index,
        "chars": copy.deepcopy(data["chars"]),
        "style_slots": style_slots,
        "style_bundle": combine_style_slots(style_slots),
        "patched_comment": copy.deepcopy(data["comment"]),
        "patched_ai_json": copy.deepcopy(data["ai_json"]),
        "base_caption": data["base_caption"],
        "params": data["params"],
    }










def _plain_ark_base_after_replacement(base_caption: str, original_chars: list[dict]) -> str:
    """Remove virtual Ark character tags from a plain prompt after slot replacement."""
    from char_tag_db import (
        classify_single_tag,
        is_appearance_tag,
        is_body_tag,
        is_character_tag,
        is_copyright_tag,
        is_creature_tag,
    )

    explicit_old_tags: set[str] = set()
    explicit_old_names: set[str] = set()
    for ch in original_chars or []:
        for key in ("ark_library_tag", "summary"):
            value = str(ch.get(key) or "").strip().lower()
            if value:
                explicit_old_tags.add(value)
                explicit_old_tags.add(value.replace(" ", "_"))
        for tag in ch.get("identity_tags") or []:
            value = str(tag or "").strip().lower()
            if value:
                explicit_old_tags.add(value)
            # 原始 prompt 里的权重块写法可能与槽的规范化写法不同
            # （chloe(princess connect!)(1st costume,...  vs  chloe_(princess_connect!)），
            # 用角色名变体做子串匹配，确保整个旧角色块被移除。
            for variant in _plain_identity_variants(tag):
                for candidate in (
                    variant,
                    variant.replace("_(", "("),
                    variant.replace("_(", "(").replace("_", " "),
                    variant.replace("_", " "),
                ):
                    name = candidate.strip().lower()
                    if name:
                        explicit_old_names.add(name)
        char_cap = str(ch.get("char_caption") or "").strip().lower()
        if char_cap:
            for tag in _split_tags(char_cap):
                val = tag.strip().lower()
                if val:
                    explicit_old_tags.add(val)

    kept: list[str] = []
    seen: set[str] = set()
    for tag in _split_tags(base_caption):
        low = str(tag).strip().lower()
        if not low or low in seen:
            continue
        if any(name and name in low for name in explicit_old_names):
            continue
        if low in explicit_old_tags:
            continue
        if "_(arknights)" in low or " (arknights)" in low:
            continue
        if low in _GENDER_NOISE:
            continue
        if is_creature_tag(tag):
            continue
        if is_copyright_tag(tag):
            continue
        tag_cat = classify_single_tag(tag)
        if low.startswith("artist:") or low.startswith("artist "):
            kept.append(tag)
            seen.add(low)
            continue
        if is_character_tag(tag) and tag_cat != "action":
            continue
        if is_body_tag(tag) or is_appearance_tag(tag):
            if tag_cat != "action":
                continue
        if tag_cat == "appearance":
            continue
        kept.append(tag)
        seen.add(low)
    return _join_tags(kept)


def _base_after_target_replacement(
    base_caption: str,
    *,
    replaced_old_captions: list[str],
    remaining_chars: list[dict],
) -> str:
    """Remove replaced character identities from v4 base while preserving other slots."""
    if not replaced_old_captions or not str(base_caption or "").strip():
        return base_caption

    from char_tag_db import identity_tag_display

    remove_tokens: set[str] = set()
    remove_names: set[str] = set()
    for caption in replaced_old_captions:
        for token in tokenize_prompt(caption):
            raw = str(token.text or token.raw or "").strip().lower()
            if not raw:
                continue
            compact = raw.replace(" ", "_")
            if "(arknights)" not in raw and "(oc)" not in raw:
                continue
            remove_tokens.add(raw)
            remove_tokens.add(compact)
            display = identity_tag_display(raw).strip().lower()
            if display:
                remove_tokens.add(display)
                remove_tokens.add(display.replace(" ", "_"))
                remove_names.add(display)
                remove_names.add(display.replace(" ", "_"))

    protected: set[str] = set()
    protected_names: set[str] = set()
    for ch in remaining_chars:
        caption = str(ch.get("char_caption") or "")
        for token in tokenize_prompt(caption):
            raw = str(token.text or token.raw or "").strip().lower()
            if not raw:
                continue
            protected.add(raw)
            protected.add(raw.replace(" ", "_"))
            display = identity_tag_display(raw).strip().lower()
            if display:
                protected.add(display)
                protected.add(display.replace(" ", "_"))
                protected_names.add(display)
                protected_names.add(display.replace(" ", "_"))

    kept: list[str] = []
    for tag in _split_tags(base_caption):
        low = str(tag or "").strip().lower()
        compact = low.replace(" ", "_")
        display = identity_tag_display(low).strip().lower()
        keys = {low, compact}
        if display:
            keys.add(display)
            keys.add(display.replace(" ", "_"))
        contains_removed_name = any(
            name and len(name) >= 3 and (name in low or name in compact)
            for name in remove_names
        )
        contains_protected_name = any(
            name and len(name) >= 3 and (name in low or name in compact)
            for name in protected_names
        )
        if (keys & remove_tokens and not keys & protected) or (
            contains_removed_name and not contains_protected_name
        ):
            continue
        kept.append(tag)
    return _join_tags(kept)


def clean_plain_ark_workbench_draft(
    comment: dict,
    work_id: int | None,
    page_index: int = 0,
    gallery_id: str = "site",
) -> dict:
    """Clean stale base tags when an old workbench draft came from a plain Ark prompt."""
    if not isinstance(comment, dict) or work_id is None:
        return comment
    gid = normalize_gallery_id(gallery_id)
    # Only local galleries have extractable metadata; skip aitag-online / unknown.
    if gid not in {"site", "codex", "qqgroup"}:
        return comment
    try:
        original = extract_chars(int(work_id), int(page_index or 0), gallery_id=gid)
    except Exception:
        return comment
    if original.get("prompt_layout") not in {
        "plain_ark_library",
        "plain_character_tags",
        "plain_generic",
    }:
        return comment

    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    if not char_caps:
        return comment

    base = str(cap.get("base_caption") or comment.get("prompt") or "")
    cleaned = _plain_ark_base_after_replacement(base, original.get("chars") or [])
    if cleaned == base:
        return comment

    patched = copy.deepcopy(comment)
    pv4 = patched.setdefault("v4_prompt", {})
    pcap = pv4.setdefault("caption", {})
    pcap["base_caption"] = cleaned
    patched["prompt"] = cleaned
    return patched


@lru_cache(maxsize=256)
def _extract_chars_cached(
    work_id: int,
    page_index: int = 0,
    gallery_id: str = "site",
) -> str:
    return json.dumps(
        _extract_chars_impl(work_id, page_index, gallery_id),
        ensure_ascii=False,
    )


def extract_chars(
    work_id: int,
    page_index: int = 0,
    gallery_id: str = "site",
) -> dict[str, Any]:
    from gallery_catalog import normalize_gallery_id

    gid = normalize_gallery_id(gallery_id)
    return json.loads(_extract_chars_cached(work_id, page_index, gid))


def clear_extract_chars_cache(work_id: int | None = None) -> None:
    _extract_chars_cached.cache_clear()


def _chars_from_char_marker_layout(
    layout: dict[str, Any],
) -> tuple[list[dict], str, dict[str, Any]]:
    """从 char1/char2 扁平写法解析虚拟角色槽。"""
    chars: list[dict] = []
    for i, sec in enumerate(layout.get("sections") or []):
        caption = str(sec.get("caption") or "")
        marker_num = int(sec.get("marker_num") or (i + 1))
        chars.append(
            _format_char_slot(
                i,
                {
                    "char_caption": caption,
                    "uc_caption": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "marker_num": marker_num,
                },
                caption,
            )
        )
    base_caption = str(layout.get("base_caption") or "")
    apply_slot_genders(chars, base_caption=base_caption)
    _sync_slot_contract_after_gender(chars)
    return chars, base_caption, layout


def _resolve_prompt_layout(
    comment: dict,
    cap: dict,
    char_caps: list,
) -> tuple[list[dict], str, str, dict[str, Any] | None]:
    """优先 v4 char_captions；否则解析 char1/char2 扁平写法。"""
    base_caption = str(cap.get("base_caption") or comment.get("prompt") or "")
    char_marker_layout: dict[str, Any] | None = None
    if char_caps:
        v4n = (comment.get("v4_negative_prompt") or {}).get("caption") or {}
        char_ucs = v4n.get("char_captions") or []
        chars: list[dict] = []
        for i, item in enumerate(char_caps):
            if not isinstance(item, dict):
                continue
            caption = str(item.get("char_caption") or "")
            centers = item.get("centers") or [{"x": 0.5, "y": 0.5}]
            uc_item = char_ucs[i] if i < len(char_ucs) else {}
            uc = str((uc_item or {}).get("char_caption") or "")
            chars.append(
                _format_char_slot(
                    i,
                    {
                        "char_caption": caption,
                        "uc_caption": uc,
                        "center": centers[0] if centers else {"x": 0.5, "y": 0.5},
                    },
                    caption,
                )
            )
        apply_slot_genders(chars, base_caption=base_caption)
        _sync_slot_contract_after_gender(chars)
        return chars, base_caption, "v4_slots", None

    layout = parse_char_marker_layout(base_caption)
    if layout:
        chars, scene_base, layout = _chars_from_char_marker_layout(layout)
        return chars, scene_base, "char_markers", layout

    character_plain = _chars_from_plain_character_prompt(base_caption)
    if character_plain:
        chars, scene_base, layout = character_plain
        return chars, scene_base, layout, None

    ark_plain = _chars_from_plain_ark_prompt(base_caption)
    if ark_plain:
        chars, scene_base = ark_plain
        return chars, scene_base, "plain_ark_library", None

    generic_plain = _chars_from_generic_plain_prompt(base_caption)
    if generic_plain:
        chars, scene_base = generic_plain
        return chars, scene_base, "plain_generic", None

    return [], base_caption, "plain", None


def _chars_from_comment(comment: dict) -> tuple[list[dict], str]:
    """从 Comment 草稿解析角色槽（用于在已有草稿上继续替换）。"""
    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    chars, base_caption, _layout, _marker = _resolve_prompt_layout(comment, cap, char_caps)
    return chars, base_caption


def _merge_extract_with_draft(data: dict, patched_comment: dict) -> dict[str, Any]:
    merged = copy.deepcopy(data)
    comment = copy.deepcopy(patched_comment)
    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    chars, base_caption, prompt_layout, char_marker_layout = _resolve_prompt_layout(
        comment, cap, char_caps
    )
    merged["comment"] = comment
    merged["chars"] = chars
    merged["base_caption"] = base_caption
    merged["prompt_layout"] = prompt_layout
    if char_marker_layout:
        merged["char_marker_layout"] = char_marker_layout
        merged["full_prompt"] = str(char_marker_layout.get("full_text") or "")
    else:
        merged.pop("char_marker_layout", None)
        merged.pop("full_prompt", None)
    return merged


def _extract_chars_impl(
    work_id: int,
    page_index: int = 0,
    gallery_id: str = "site",
) -> dict[str, Any]:
    if gallery_id == "site":
        ai_json = _load_image_json(work_id, page_index)
    else:
        ai_json = _load_image_json(work_id, page_index, gallery_id)
    comment = _get_effective_comment(ai_json)
    if not comment.get("Source") and ai_json.get("Source"):
        comment["Source"] = ai_json["Source"]
    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    chars, base_caption, prompt_layout, char_marker_layout = _resolve_prompt_layout(
        comment, cap, char_caps
    )

    style_slots = extract_style_slots_from_comment(comment)
    result: dict[str, Any] = {
        "work_id": work_id,
        "page_index": page_index,
        "base_caption": base_caption,
        "prompt_layout": prompt_layout,
        "style_slots": style_slots,
        "style_bundle": combine_style_slots(style_slots),
        "use_coords": bool(v4.get("use_coords", True)),
        "chars": chars,
        "params": {
            "width": int(comment.get("width") or 832),
            "height": int(comment.get("height") or 1216),
            "scale": float(comment.get("scale") or 5),
            "steps": int(comment.get("steps") or 28),
            "sampler": str(comment.get("sampler") or "k_euler_ancestral"),
            "seed": comment.get("seed"),
            "uc": str(comment.get("uc") or ""),
            "source": str(ai_json.get("Source") or comment.get("Source") or ""),
        },
        "comment": comment,
        "ai_json": ai_json,
    }
    if char_marker_layout:
        result["char_marker_layout"] = char_marker_layout
        result["full_prompt"] = str(char_marker_layout.get("full_text") or "")

    # OC预设匹配：如果slot的caption匹配已知OC的char_caption，设置oc_preview和oc_matched
    # 注意：不覆盖 summary/identity_tags 等核心字段，仅记录匹配信息供前端展示。
    # summary 应由 pick_character_summary 从 char_caption 推断，不受 OC 预设影响。
    try:
        cfg = load_char_swap_config()
        customs = []
        cp = cfg.get("custom_presets") or {}
        customs.extend(cp.get("female") or [])
        customs.extend(cp.get("male") or [])
        for ch in chars:
            cap = str(ch.get("char_caption") or "")
            ch["oc_matched"] = False
            ch["oc_label"] = ""
            for c in customs:
                if str(c.get("kind") or "").lower() == "oc":
                    oc_cap = str(c.get("char_caption") or "").strip()
                    oc_label = str(c.get("label") or "")
                    if _slot_matches_oc_preset(cap, c):
                        ch["oc_matched"] = True
                        ch["oc_label"] = oc_label
                        if "oc_preview" not in ch or not ch.get("oc_preview"):
                            ch["oc_preview"] = oc_cap[:120] + ("..." if len(oc_cap) > 120 else "")
                        break
    except Exception as exc:  # 不影响主流程，但留下可诊断的一行日志
        _logger.warning("OC 预设匹配失败，已跳过 oc_preview 标记: %s", exc)

    return result


_FORBIDDEN_CHAR_UC_TAGS = frozenset({
    "head", "face", "body", "human", "person", "figure", "torso", "upper body", "lower body"
})


def _clean_char_uc_text(text: str) -> str:
    from char_tag_db import split_prompt_tags
    parts = [p.strip() for p in split_prompt_tags(text) if p.strip()]
    cleaned = [p for p in parts if p.lower() not in _FORBIDDEN_CHAR_UC_TAGS]
    return ", ".join(cleaned)


def _patch_comment(
    comment: dict,
    chars: list[dict],
    base_caption: str,
    *,
    char_marker_layout: dict[str, Any] | None = None,
) -> dict:
    patched = copy.deepcopy(comment)
    v4 = patched.setdefault("v4_prompt", {})
    cap = v4.setdefault("caption", {})
    layout = char_marker_layout
    if layout and layout.get("layout") == "char_markers":
        updated = copy.deepcopy(layout)
        for i, sec in enumerate(updated.get("sections") or []):
            if i < len(chars):
                sec["caption"] = str(chars[i].get("char_caption") or sec.get("caption") or "")
        full_base = rebuild_char_marker_prompt(updated, chars)
        cap["base_caption"] = full_base
        cap["char_captions"] = []
        patched["prompt"] = full_base
        v4n = patched.setdefault("v4_negative_prompt", {"caption": {}})
        capn = v4n.setdefault("caption", {})
        capn["char_captions"] = []
        return patched
    else:
        cap["base_caption"] = base_caption
        cap["char_captions"] = [
            {
                "char_caption": c["char_caption"],
                "centers": [c.get("center") or {"x": 0.5, "y": 0.5}],
            }
            for c in chars
        ]
        patched["prompt"] = base_caption
    v4n = patched.setdefault("v4_negative_prompt", {"caption": {"char_captions": []}})
    capn = v4n.setdefault("caption", {})
    existing_uc = capn.get("char_captions") or []
    new_uc: list[dict] = []
    for i, c in enumerate(chars):
        uc_text = str(c.get("uc_caption") or "").strip()
        if not uc_text and i < len(existing_uc):
            uc_text = str((existing_uc[i] or {}).get("char_caption") or "")
        uc_text = _clean_char_uc_text(uc_text)
        if i < len(existing_uc) and isinstance(existing_uc[i], dict):
            item = copy.deepcopy(existing_uc[i])
            item["char_caption"] = uc_text
            new_uc.append(item)
        else:
            center = c.get("center") or {"x": 0.5, "y": 0.5}
            new_uc.append(
                {"char_caption": uc_text, "centers": [center]}
            )
    capn["char_captions"] = new_uc
    return patched


def _infer_preset_gender(payload: dict) -> str:
    gender = str(payload.get("gender") or "").strip().lower()
    if gender in {"male", "female"}:
        return gender
    mode = str(payload.get("mode") or "").lower()
    if "male" in mode:
        return "male"
    if "female" in mode:
        return "female"
    return "female"


def _merged_char_presets() -> dict[str, list]:
    from char_swap_config import load_config

    data = _presets()
    custom = load_config().get("custom_presets") or {}
    def marked(items: list, *, is_custom: bool, seen: set[str]) -> list[dict]:
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            label = unicodedata.normalize("NFKC", str(item.get("label") or "")).strip().casefold()
            preset_id = str(item.get("id") or "").strip().casefold()
            key = f"label:{label}" if label else f"id:{preset_id}"
            if key in seen:
                continue
            seen.add(key)
            result.append({
                **dict(item),
                "is_custom": is_custom,
                "source": "custom" if is_custom else "builtin",
            })
        return result

    def merged_gender(gender: str) -> list[dict]:
        seen: set[str] = set()
        return marked(list(custom.get(gender) or []), is_custom=True, seen=seen) + marked(
            list(data.get(gender, [])), is_custom=False, seen=seen
        )

    return {
        "female": merged_gender("female"),
        "male": merged_gender("male"),
    }


def _find_char_preset(preset_id: str, *, gender_hint: str | None = None) -> dict | None:
    pid = str(preset_id or "").strip()
    if not pid:
        return None
    merged = _merged_char_presets()
    pools: list[str] = []
    if gender_hint in {"male", "female"}:
        pools = [gender_hint, "male" if gender_hint == "female" else "female"]
    else:
        pools = ["female", "male"]

    # 1. Exact ID match
    for gender in pools:
        for item in merged.get(gender) or []:
            if str(item.get("id") or "") == pid:
                return item

    # 2. Case-insensitive or clean ID/label match
    pid_low = pid.lower()
    pid_clean = pid_low.removeprefix("custom_")
    for gender in pools:
        for item in merged.get(gender) or []:
            iid = str(item.get("id") or "").lower()
            label = str(item.get("label") or "").lower()
            clean_label = label.split("（")[0].split("(")[0].strip()
            if iid == pid_low or label == pid_low or clean_label == pid_low or iid.removeprefix("custom_") == pid_clean:
                return item

    # 3. Substring label match
    for gender in pools:
        for item in merged.get(gender) or []:
            label = str(item.get("label") or "").lower()
            if pid_low in label or label in pid_low:
                return item

    return None


def _non_negative_index(value: Any, *, label: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是非负整数")
    if isinstance(value, int):
        index = value
    else:
        text = str(value).strip()
        if not text.isdigit():
            raise ValueError(f"{label}必须是非负整数")
        index = int(text)
    if index < 0:
        raise ValueError(f"{label}必须是非负整数")
    return index


def _source_bundle_from_request(payload: dict) -> dict[str, Any]:
    char_obj = payload.get("character") if isinstance(payload.get("character"), dict) else {}
    preset_id = payload.get("preset_id") or char_obj.get("preset_id") or char_obj.get("id") or char_obj.get("name")
    if preset_id:
        item = _find_char_preset(
            str(preset_id),
            gender_hint=_infer_preset_gender(payload),
        )
        if item:
            if _is_oc_bundle(item) and not str(item.get("char_caption") or "").strip():
                raise ValueError(
                    f"OC 预设 {preset_id} 缺少 char_caption，请在设置里补全整段角色咒语"
                )
            # 允许 payload 提供运行时 override（服饰替换、添加、减少），优先级高于预设
            item = dict(item)  # copy
            for k in ("clothing", "extra", "remove"):
                if k in payload and str(payload.get(k) or "").strip():
                    item[k] = payload[k]
                elif k in char_obj and str(char_obj.get(k) or "").strip():
                    item[k] = char_obj[k]
            return item
        raise ValueError(f"未找到预设 {preset_id}")

    custom = payload.get("custom_bundle") or char_obj.get("custom_bundle")
    if custom and isinstance(custom, dict):
        item = dict(custom)
        for k in ("clothing", "extra", "remove"):
            if k in payload and str(payload.get(k) or "").strip():
                item[k] = payload[k]
        return item

    sw = payload.get("source_work_id") or char_obj.get("source_work_id")
    si = _non_negative_index(
        payload.get("source_char_index") or char_obj.get("source_char_index"),
        label="源角色槽位",
    )
    sp = _non_negative_index(
        payload.get("source_page_index") or char_obj.get("source_page_index"),
        label="源页码",
    )
    if sw:
        src = extract_chars(int(sw), sp)
        if si >= len(src["chars"]):
            raise ValueError("源角色槽位不存在")
        item = dict(src["chars"][si].get("bundle") or {})
        for k in ("clothing", "extra", "remove"):
            if k in payload and str(payload.get(k) or "").strip():
                item[k] = payload[k]
        return item

    custom_caption = (
        payload.get("custom_char_caption")
        or char_obj.get("custom_char_caption")
        or char_obj.get("char_caption")
    )
    if custom_caption:
        item = bundle_from_caption(str(custom_caption))
        for k in ("clothing", "extra", "remove"):
            if k in payload and str(payload.get(k) or "").strip():
                item[k] = payload[k]
        return item

    raise ValueError("需要 preset_id、source_work_id 或 custom_char_caption")


def _replacement_caption_from_plan(
    old_caption: str,
    source_bundle: dict[str, Any],
    *,
    slot_index: int,
    preserve_action: bool,
    force_gender: str | None,
) -> str:
    if _is_oc_bundle(source_bundle):
        # 群友 OC 不是普通“角色标签替换”：预设只提供外貌/服装，
        # 原图的姿势、神态、体型与场景才是构图核心。这里走旧版
        # merge_bundle 的 OC 专用合并逻辑，避免 planner 只保留 action
        # bucket 而丢掉 lie on back / torogao / slender 等场景信息。
        return merge_bundle(
            old_caption,
            source_bundle,
            preserve_action=True,
            force_gender=force_gender,
        )
    return plan_replacement(
        analyze_slot_caption(old_caption, gender_hint=force_gender or ""),
        source_bundle,
        slot_index=slot_index,
        preserve_action=preserve_action,
        force_gender=force_gender,
    ).output_caption


def transform(
    payload: dict,
    *,
    source_data: dict[str, Any] | None = None,
    include_style_slots: bool = True,
) -> dict[str, Any]:
    mode = str(payload.get("mode") or "replace")
    target_work_id = payload.get("target_work_id", payload.get("work_id"))
    if target_work_id is None:
        raise ValueError("需要 target_work_id")
    work_id = int(target_work_id)
    page_index = _non_negative_index(
        payload.get("target_page_index", payload.get("page_index")),
        label="目标页码",
    )
    # Replacement is expected to change identity/appearance, not the source
    # pose or interaction.  Keep the historical workbench default unless a
    # caller explicitly opts out.
    preserve_action = bool(payload.get("preserve_action", True))
    preserve_center = bool(payload.get("preserve_center", True))

    # ``prepare_work_draft`` already owns a detached extraction snapshot.  Reuse
    # it instead of decoding the same cached metadata a second time.  Direct
    # manual API calls keep the original extraction behaviour.
    gid = normalize_gallery_id(payload.get("gallery_id") or payload.get("gallery") or payload.get("target_gallery_id") or "site")
    data = source_data if isinstance(source_data, dict) else extract_chars(work_id, page_index, gallery_id=gid)
    draft_comment = payload.get("patched_comment")
    if isinstance(draft_comment, dict) and draft_comment.get("v4_prompt"):
        data = _merge_extract_with_draft(data, draft_comment)
    chars = copy.deepcopy(data["chars"])
    replaced_genders: dict[int, str] = {}
    replaced_old_captions: list[str] = []

    if mode == "clone":
        source_bundle = _source_bundle_from_request(payload)
        if len(chars) >= 6:
            raise ValueError("已达 6 个角色槽位上限")
        center = payload.get("center") or {"x": 0.5, "y": 0.5}
        new_caption = merge_bundle("", source_bundle, preserve_action=False)
        chars.append(
            {
                "char_caption": new_caption,
                "uc_caption": "",
                "center": center,
                "summary": source_bundle.get("identity", [""])[0] if source_bundle.get("identity") else "",
            }
        )
    elif mode == "creature_to_partner":
        source_bundle = _source_bundle_from_request(payload)
        from char_tag_db import is_creature_slot, resolve_creature_char_indices

        removed_creature: list[str] = []
        target_raw = payload.get("target_char_index")
        target_text = str(target_raw or "").strip().lower()
        if not target_text or target_text in {"auto_creature", "auto"}:
            drop_indices = set(resolve_creature_char_indices(chars))
        else:
            one = _non_negative_index(target_raw, label="目标角色槽位")
            if one >= len(chars):
                raise ValueError(f"目标角色槽位超出范围：{one}")
            cap = str(chars[one].get("char_caption") or "")
            if is_creature_slot(cap, summary=str(chars[one].get("summary") or "")):
                drop_indices = {one}
            else:
                drop_indices = set()

        new_base, removed_base = strip_creature_tags_from_caption(data["base_caption"])
        if removed_base:
            removed_creature.extend(removed_base)
        data["base_caption"] = new_base

        kept_chars: list[dict] = []
        for i, ch in enumerate(chars):
            cap = str(ch.get("char_caption") or "")
            if i in drop_indices:
                removed_creature.extend(_split_creature_parts(cap))
                continue
            new_cap, removed = strip_creature_tags_from_caption(cap)
            if removed:
                removed_creature.extend(removed)
            if not new_cap.strip():
                continue
            item = copy.deepcopy(ch)
            item["char_caption"] = new_cap
            kept_chars.append(item)

        if not kept_chars:
            raise ValueError("去除贵物/异种后无人类角色槽，请检查源图")

        partner_gender = _infer_preset_gender(payload)
        partner_cap = merge_bundle(
            "",
            source_bundle,
            preserve_action=False,
            force_gender=partner_gender if partner_gender in {"male", "female"} else None,
        )
        partner_center = payload.get("partner_center") or payload.get("center") or {
            "x": 0.38,
            "y": 0.55,
        }
        partner_summary = ""
        for tag in source_bundle.get("identity") or []:
            if "_(arknights)" in str(tag).lower():
                partner_summary = str(tag).split("_(")[0]
                break
        if not partner_summary and source_bundle.get("identity"):
            partner_summary = str(source_bundle["identity"][0])
        kept_chars.append(
            {
                "char_caption": partner_cap,
                "uc_caption": "",
                "center": partner_center,
                "summary": partner_summary,
                "creature_replaced": removed_creature,
            }
        )
        if len(kept_chars) > 6:
            raise ValueError("添加搭档后超过 6 个角色槽位上限")
        chars = kept_chars
    elif mode == "replace_multi":
        replacements = payload.get("replacements") or []
        if not isinstance(replacements, list) or not replacements:
            raise ValueError("请至少为一个槽位选择预设")
        applied = 0
        default_gender = _infer_preset_gender(payload)
        skip_missing = bool(payload.get("skip_missing_slots", False))
        for item in replacements:
            if not isinstance(item, dict):
                continue
            preset_id = str(item.get("preset_id") or "").strip()
            if not preset_id:
                continue
            slot_mode = str(item.get("mode") or payload.get("mode") or "").lower()
            slot_gender = str(item.get("gender") or default_gender or "").lower()
            if slot_mode == "replace_male" or slot_gender == "male":
                force_gender = "male"
            elif slot_mode == "replace_female" or slot_gender == "female":
                force_gender = "female"
            elif default_gender in {"male", "female"}:
                force_gender = default_gender
            else:
                force_gender = None
            idx = _resolve_multi_replacement_index(
                chars,
                item,
                force_gender=force_gender,
                skip_missing=skip_missing,
            )
            if idx is None:
                continue
            item_match_keys = _payload_identity_keys(item)
            # An explicit slot selects where to look; it must not bypass a
            # supplied source-identity guard.  Cross-page batch replacements
            # rely on this to avoid replacing a different character that
            # happens to occupy the same slot.
            if item_match_keys and not (
                _slot_identity_keys(chars[idx]) & item_match_keys
            ):
                continue
            sub_payload = {
                **payload,
                "preset_id": preset_id,
                "gender": force_gender or default_gender,
            }
            source_bundle = _source_bundle_from_request(sub_payload)
            old_caption = str(chars[idx]["char_caption"] or "")
            replaced_old_captions.append(old_caption)
            new_caption = _replacement_caption_from_plan(
                old_caption,
                source_bundle,
                slot_index=idx,
                preserve_action=preserve_action,
                force_gender=force_gender,
            )
            _apply_replaced_char_state(
                chars[idx],
                source_bundle,
                old_caption,
                new_caption,
                force_gender=force_gender,
            )
            if force_gender:
                replaced_genders[idx] = force_gender
            if not preserve_center and payload.get("center"):
                chars[idx]["center"] = payload.get("center")
            applied += 1
        if not applied:
            if skip_missing:
                return _unchanged_transform_result(
                    data,
                    mode=mode,
                    work_id=work_id,
                    page_index=page_index,
                    message="No matching source character on this page; skipped.",
                    include_style_slots=include_style_slots,
                )
            raise ValueError("请至少为一个槽位选择预设")
    elif mode in {"replace", "replace_male", "replace_female", "replace_creature"}:
        source_bundle = _source_bundle_from_request(payload)
        match_keys = _payload_identity_keys(payload)
        if _requires_identity_guard(payload) and not match_keys:
            return _unchanged_transform_result(
                data,
                mode=mode,
                work_id=work_id,
                page_index=page_index,
                message="All-page all-gender replacement requires a source identity; skipped.",
                include_style_slots=include_style_slots,
            )
        indices = _resolve_single_replace_indices(chars, payload, mode)
        if (
            _is_all_gender_target(payload.get("target_char_index"))
            and _payload_has_identity_filter(payload)
            and not match_keys
        ):
            return _unchanged_transform_result(
                data,
                mode=mode,
                work_id=work_id,
                page_index=page_index,
                message="No valid source identity for all-gender replacement; skipped.",
                include_style_slots=include_style_slots,
            )
        has_explicit_target_index = (
            payload.get("target_char_index") is not None
            and not _is_all_gender_target(payload.get("target_char_index"))
        )
        if match_keys and not has_explicit_target_index:
            indices = [
                idx
                for idx in indices
                if 0 <= idx < len(chars) and (_slot_identity_keys(chars[idx]) & match_keys)
            ]
            if not indices:
                return _unchanged_transform_result(
                    data,
                    mode=mode,
                    work_id=work_id,
                    page_index=page_index,
                    message="No matching source character on this page; skipped.",
                    include_style_slots=include_style_slots,
                )
        force_gender = (
            "male"
            if mode == "replace_male"
            else (
                "female"
                if mode in {"replace_female", "replace_creature"}
                else None
            )
        )
        for raw_idx in indices:
            idx = (
                _remap_gender_swap_index(chars, raw_idx, mode)
                if mode in {"replace_male", "replace_female"}
                else raw_idx
            )
            if idx >= len(chars):
                raise ValueError("目标角色槽位不存在")
            old_caption = str(chars[idx]["char_caption"] or "")
            replaced_old_captions.append(old_caption)
            new_caption = _replacement_caption_from_plan(
                old_caption,
                source_bundle,
                slot_index=idx,
                preserve_action=preserve_action,
                force_gender=force_gender,
            )
            _apply_replaced_char_state(
                chars[idx],
                source_bundle,
                old_caption,
                new_caption,
                force_gender=force_gender,
            )
            if force_gender:
                replaced_genders[idx] = force_gender
            if not preserve_center:
                chars[idx]["center"] = payload.get("center") or chars[idx]["center"]
    else:
        raise ValueError(f"未知 mode: {mode}")

    patched_base_caption = data["base_caption"]
    if data.get("prompt_layout") in {
        "plain_ark_library",
        "plain_character_tags",
        "plain_generic",
    }:
        patched_base_caption = _plain_ark_base_after_replacement(
            data["base_caption"],
            data.get("chars") or [],
        )
    elif data.get("prompt_layout") == "v4_slots":
        patched_base_caption = _base_after_target_replacement(
            data["base_caption"],
            replaced_old_captions=replaced_old_captions,
            remaining_chars=chars,
        )

    patched_comment = _patch_comment(
        data["comment"],
        chars,
        patched_base_caption,
        char_marker_layout=data.get("char_marker_layout"),
    )
    patched_ai = copy.deepcopy(data["ai_json"])
    patched_ai["Comment"] = patched_comment

    out_chars = _format_transform_chars(
        chars,
        str(data.get("base_caption") or ""),
        replaced_genders,
    )

    style_slots = (
        extract_style_slots_from_comment(patched_comment)
        if include_style_slots
        else []
    )
    return {
        "ok": True,
        "mode": mode,
        "work_id": work_id,
        "page_index": page_index,
        "chars": out_chars,
        "style_slots": style_slots,
        "style_bundle": combine_style_slots(style_slots),
        "patched_comment": patched_comment,
        "patched_ai_json": patched_ai,
        "base_caption": patched_base_caption,
        "params": data["params"],
    }


def sanitize_payload(payload: dict) -> dict[str, Any]:
    comment = payload.get("patched_comment")
    if not comment and payload.get("work_id"):
        gid = normalize_gallery_id(payload.get("gallery_id") or payload.get("gallery") or "site")
        data = extract_chars(int(payload["work_id"]), int(payload.get("page_index") or 0), gallery_id=gid)
        comment = data["comment"]
    if not comment:
        raise ValueError("需要 patched_comment 或 work_id")
    result = sanitize_comment(
        comment,
        racial=bool(payload.get("filter_racial", True)),
        gore=bool(payload.get("filter_gore", True)),
        creature=bool(payload.get("filter_creature", False)),
    )
    result["message"] = (
        f"已移除 {sum(len(x['removed']) for x in result['removed'])} 个 tag"
        if result["removed"]
        else "未发现需过滤 tag"
    )
    return result


def resolve_creature_char_index(chars: list[dict]) -> int | None:
    """返回首个贵物/动物槽；无专用槽时回退到贵物 tag 最多的混合槽。"""
    from char_tag_db import resolve_creature_char_indices

    indices = resolve_creature_char_indices(chars)
    if indices:
        return indices[0]
    best_i: int | None = None
    best_n = 0
    for i, ch in enumerate(chars):
        buckets = classify_tags(str(ch.get("char_caption") or ""))
        n = len(buckets.get("creature") or [])
        if ch.get("creature_tags"):
            n = max(n, len(ch["creature_tags"]))
        if n > best_n:
            best_n = n
            best_i = i
    return best_i if best_n > 0 else None


def resolve_all_female_indices(chars: list[dict]) -> list[int]:
    pool = indices_for_gender(chars, "female")
    if pool:
        return pool
    if len(chars) == 1 and slot_gender_of(chars[0]) != "male":
        return [0]
    return []


def resolve_all_male_indices(chars: list[dict]) -> list[int]:
    pool = indices_for_gender(chars, "male")
    if pool:
        return pool
    if len(chars) == 1 and slot_gender_of(chars[0]) == "male":
        return [0]
    return []


def _remap_gender_swap_index(chars: list[dict], idx: int, mode: str) -> int:
    """换男/女角若误指到异性槽且本图仅一个目标性别槽，则改指到该槽。"""
    want = (
        "male"
        if mode == "replace_male"
        else "female"
        if mode == "replace_female"
        else None
    )
    if not want or idx < 0 or idx >= len(chars):
        return idx
    if _slot_gender(chars[idx]) == want:
        return idx
    pool = (
        resolve_all_male_indices(chars)
        if want == "male"
        else resolve_all_female_indices(chars)
    )
    if len(pool) == 1:
        return pool[0]
    return idx


def _resolve_multi_replacement_index(
    chars: list[dict],
    item: dict,
    *,
    force_gender: str | None,
    skip_missing: bool,
) -> int | None:
    """按 gender_slot_index（第 N 个女/男槽）或 target_char_index 解析槽位。"""
    pool: list[int]
    if force_gender == "male":
        pool = resolve_all_male_indices(chars)
    elif force_gender == "female":
        pool = resolve_all_female_indices(chars)
    else:
        pool = list(range(len(chars)))

    gsi = item.get("gender_slot_index")
    if gsi is not None and str(gsi).strip() != "":
        ord_i = int(gsi)
        if ord_i < 0 or ord_i >= len(pool):
            if skip_missing:
                return None
            raise ValueError(f"本图第 {ord_i + 1} 个{force_gender or '角色'}槽不存在")
        return pool[ord_i]

    idx_raw = item.get("target_char_index")
    if idx_raw is None or str(idx_raw).strip() == "":
        if skip_missing:
            return None
        raise ValueError("未指定目标槽位")
    if isinstance(idx_raw, int) or (
        isinstance(idx_raw, str) and str(idx_raw).strip().isdigit()
    ):
        idx = int(idx_raw)
    else:
        raise ValueError(f"无效槽位: {idx_raw}")
    if idx < 0 or idx >= len(chars):
        if skip_missing:
            return None
        raise ValueError(f"槽位 #{idx + 1} 不存在")
    return idx


def _resolve_single_replace_indices(
    chars: list[dict],
    payload: dict[str, Any],
    mode: str,
) -> list[int]:
    """单槽换角；优先 gender_slot_index（第 N 个女/男槽），便于全部图片一致替换。"""
    gsi = payload.get("gender_slot_index")
    if gsi is not None and str(gsi).strip() != "":
        if mode == "replace_female":
            pool = resolve_all_female_indices(chars)
            label = "女"
        elif mode == "replace_male":
            pool = resolve_all_male_indices(chars)
            label = "男"
        else:
            pool = list(range(len(chars)))
            label = "角色"
        ord_i = int(gsi)
        if ord_i < 0 or ord_i >= len(pool):
            # 该性别槽不存在（如图上无男槽却按男槽序号替换，或怪物/未知槽被
            # 当成某性别槽）。回退到 target_char_index 解析，避免硬报错。
            tc = payload.get("target_char_index")
            if tc is None or str(tc).strip() == "":
                raise ValueError(f"本图第 {ord_i + 1} 个{label}角色槽不存在")
            return resolve_target_char_indices(
                chars,
                tc,
                mode=mode,
                prefer_creature=bool(payload.get("replace_creature", True)),
            )
        return [pool[ord_i]]
    return resolve_target_char_indices(
        chars,
        payload.get("target_char_index"),
        mode=mode,
        prefer_creature=bool(payload.get("replace_creature", True)),
    )


def resolve_target_char_indices(
    chars: list[dict],
    target: Any = None,
    *,
    mode: str = "replace",
    prefer_creature: bool = True,
) -> list[int]:
    text = str(target if target is not None else payload_char_index_default(mode)).strip().lower()
    if text in _ALL_FEMALE_TARGETS:
        indices = resolve_all_female_indices(chars)
        if not indices:
            raise ValueError("未检测到女角色槽位")
        return indices
    if text in _ALL_MALE_TARGETS:
        indices = resolve_all_male_indices(chars)
        if not indices:
            raise ValueError("未检测到男角色槽位")
        return indices
    return [
        pick_target_char_index(
            chars,
            target,
            mode=mode,
            prefer_creature=prefer_creature,
        )
    ]


def pick_target_char_index(
    chars: list[dict],
    target: Any = None,
    *,
    mode: str = "replace",
    prefer_creature: bool = True,
) -> int:
    text = str(target if target is not None else payload_char_index_default(mode)).strip().lower()
    if text == "auto_creature":
        idx = resolve_creature_char_index(chars)
        if idx is None:
            raise ValueError("未检测到含贵物/异种 tag 的角色槽")
        return idx
    if prefer_creature and text in {"auto", "auto_male", "auto_female"}:
        cidx = resolve_creature_char_index(chars)
        if cidx is not None:
            return cidx
    return resolve_char_index(chars, target, mode=mode)


def resolve_char_index(
    chars: list[dict],
    target: Any = None,
    *,
    mode: str = "replace",
) -> int:
    """解析目标槽位；支持 auto_male / auto_female / 数字。"""
    if not chars:
        raise ValueError("未检测到可用目标角色槽位")
    raw = target if target is not None else payload_char_index_default(mode)
    if isinstance(raw, bool):
        raise ValueError("目标角色槽位必须是非负整数或自动选择值")
    if isinstance(raw, int):
        if raw < 0 or raw >= len(chars):
            raise ValueError(f"目标角色槽位超出范围：{raw}")
        return raw
    text = str(raw).strip().lower()
    if text.isdigit():
        index = int(text)
        if index >= len(chars):
            raise ValueError(f"目标角色槽位超出范围：{index}")
        return index
    if text in {"auto", "auto_male"}:
        for i, ch in enumerate(chars):
            if _slot_gender(ch) == "male":
                return i
        return 1 if len(chars) > 1 else 0
    if text == "auto_female":
        for i, ch in enumerate(chars):
            if _slot_gender(ch) == "female":
                return i
        return 0
    raise ValueError(f"无法识别目标角色槽位：{raw!r}")


def payload_char_index_default(mode: str) -> str:
    if mode == "replace_male":
        return "auto_male"
    if mode == "replace_female":
        return "auto_female"
    return "0"


def extract_chars_from_comment(comment: dict) -> list[dict[str, Any]]:
    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    chars, _, _, _ = _resolve_prompt_layout(comment, cap, char_caps)
    return chars


def apply_style_payload(payload: dict) -> dict[str, Any]:
    comment = payload.get("patched_comment")
    if not comment and payload.get("work_id"):
        data = extract_chars(int(payload["work_id"]), int(payload.get("page_index") or 0))
        comment = data["comment"]
    if not comment:
        raise ValueError("需要 patched_comment 或 work_id")
    find = str(payload.get("find") or "").strip()
    replace = str(payload.get("replace") or "")
    mode = str(payload.get("mode") or "").strip().lower()
    cleared = 0
    added = 0
    style_applied = False
    if mode in {"preset", "replace_detected"}:
        patched, cleared, added, style_applied = apply_style_preset_to_comment(comment, replace)
        count = cleared + added
        if replace:
            msg = (
                f"已消除画风 {cleared} 处并加入新画风"
                if cleared
                else "未识别到可消除的画风，已应用新画风"
            )
        else:
            msg = f"已消除画风 {cleared} 处" if cleared else "当前已无可识别画风"
    elif mode == "append" or (not find and replace):
        patched, count = append_style_to_comment(comment, replace)
        added = count
        style_applied = bool(count)
        preview = replace if len(replace) <= 48 else replace[:48] + "…"
        msg = f"已追加画风到 base（{preview}）" if count else "画风已存在，未重复追加"
        if not count:
            style_applied = True
    elif not find:
        raise ValueError("需要填写要查找的画风片段")
    else:
        patched, count = replace_style_in_comment(
            comment,
            find,
            replace,
            case_insensitive=bool(payload.get("case_insensitive", True)),
        )
        msg = f"画风替换 {count} 处" if count else "未匹配到画风片段"
        style_applied = count > 0
    style_slots = extract_style_slots_from_comment(patched)
    return {
        "ok": True,
        "patched_comment": patched,
        "style_slots": style_slots,
        "style_bundle": combine_style_slots(style_slots),
        "replacements": count,
        "cleared": cleared,
        "added": added,
        "style_applied": style_applied,
        "message": msg,
        "chars": extract_chars_from_comment(patched),
    }


def batch_preview(payload: dict) -> dict[str, Any]:
    targets = payload.get("targets") or []
    if not targets:
        raise ValueError("targets 不能为空")
    if len(targets) > BATCH_TARGET_MAX:
        raise ValueError(f"单次最多 {BATCH_TARGET_MAX} 个作品")
    recipe = payload.get("recipe") or {}

    # 并行准备草稿，利用线程池加速批量 SQLite 读取
    import concurrent.futures

    def _prep_one(raw: dict[str, Any]) -> dict:
        work_id = int(raw["work_id"])
        gallery_id = str(raw.get("gallery_id") or "site")
        page_index = int(raw.get("page_index") or 0)
        prep = prepare_work_draft(
            work_id,
            page_index,
            recipe=recipe,
            patched_comment=raw.get("patched_comment"),
            gallery_id=gallery_id,
        )
        return {
            "gallery_id": gallery_id,
            "work_id": work_id,
            "page_index": page_index,
            "ok": prep.get("ok"),
            "skipped": prep.get("skipped"),
            "message": prep.get("message"),
            "summary": prep.get("summary"),
            "from_workbench": prep.get("from_workbench"),
            "style_replacements": prep.get("style_replacements", 0),
            "transform_applied": bool(prep.get("transform_applied")),
            "style_applied": bool(prep.get("style_applied")),
            "char_count": len(prep.get("chars") or []),
        }

    def _source_key(raw: dict[str, Any]) -> tuple[str, int, int, str]:
        """Keep duplicate output copies from repeating the same local preflight.

        A Generation Job can request several images from the same work page.
        Its seed differs per copy, but the local role/style transformation does
        not.  Include the complete optional draft in the key so deliberately
        different edited prompts still receive independent validation.
        """

        gallery_id = str(raw.get("gallery_id") or "site")
        work_id = int(raw["work_id"])
        page_index = int(raw.get("page_index") or 0)
        draft = raw.get("patched_comment")
        try:
            draft_key = json.dumps(
                draft,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            # An unsupported draft is not safe to coalesce.  Preserve the
            # original validation behaviour for that individual target.
            draft_key = f"unserializable:{id(draft)}"
        return gallery_id, work_id, page_index, draft_key

    keys: list[tuple[str, int, int, str]] = []
    unique_targets: list[dict[str, Any]] = []
    unique_keys: list[tuple[str, int, int, str]] = []
    known_keys: set[tuple[str, int, int, str]] = set()
    for raw in targets:
        key = _source_key(raw)
        keys.append(key)
        if key not in known_keys:
            known_keys.add(key)
            unique_keys.append(key)
            unique_targets.append(raw)

    prepared_by_key: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(unique_targets))) as pool:
        for key, result in zip(unique_keys, pool.map(_prep_one, unique_targets)):
            prepared_by_key[key] = result
    # Return one item per requested output, preserving the existing API and
    # confirmation counts even when several outputs share one preflight.
    items = [dict(prepared_by_key[key]) for key in keys]

    ok_n = sum(1 for x in items if x.get("ok"))
    return {
        "ok": True,
        "total": len(items),
        "ready": ok_n,
        "items": items,
        "message": f"可处理 {ok_n}/{len(items)}",
    }


def list_char_presets(gender: str | None = None) -> list[dict]:
    merged = _merged_char_presets()
    if gender in {"male", "female"}:
        return merged[gender]
    return merged["female"] + merged["male"]


# Compatibility Interface -------------------------------------------------
#
# ``nai_char`` predates the deeper backend modules and is imported directly by
# routes, the Butler, Generation Jobs, release probes, and third-party scripts.
# Keep those stable names while routing their implementation through the new
# modules.  Internal callers also resolve these globals at call time, so there
# is one production implementation rather than a forked legacy path.
from nai_char_modules.generation import (
    MAX_FREE_LONG_EDGE as _MODULE_MAX_FREE_LONG_EDGE,
    MAX_FREE_PIXELS as _MODULE_MAX_FREE_PIXELS,
    MAX_FREE_STEPS as _MODULE_MAX_FREE_STEPS,
    build_generate_payload as _module_build_generate_payload,
    fit_opus_free_size as _module_fit_opus_free_size,
)
from nai_char_modules.metadata import (
    GalleryMetadataAdapter as _GalleryMetadataAdapter,
    MetadataSourceRegistry as _MetadataSourceRegistry,
    SiteMetadataAdapter as _SiteMetadataAdapter,
)
from nai_char_modules.snapshots import (
    comment_from_png as _module_comment_from_png,
    effective_comment as _module_effective_comment,
    normalize_comment as _module_normalize_comment,
    parse_comment as _module_parse_comment,
    prompt_snapshot_from_comment as _module_prompt_snapshot_from_comment,
    prompt_snapshot_from_png as _module_prompt_snapshot_from_png,
)
from nai_char_modules.sanitization import sanitizer_from_path as _sanitizer_from_path
from nai_char_modules.style import (
    _style_index as _module_style_index,
    _style_kind_and_posts as _module_style_kind_and_posts,
    append_style_to_comment as _module_append_style_to_comment,
    apply_style_preset_to_comment as _module_apply_style_preset_to_comment,
    combine_style_slots as _module_combine_style_slots,
    extract_style_slots_from_comment as _module_extract_style_slots_from_comment,
    normalize_style_tag as _module_normalize_style_tag,
    normalize_style_tag_for_match as _module_normalize_style_tag_for_match,
    reload_style_index as _module_reload_style_index,
    replace_style_in_comment as _module_replace_style_in_comment,
    replace_style_in_text as _module_replace_style_in_text,
    style_index_stats as _module_style_index_stats,
)
from nai_char_modules.remix import (
    RemixPrimitives as _RemixPrimitives,
    apply_generation_settings as _module_apply_generation_settings,
    compile_remix_recipe as _module_compile_remix_recipe,
)


def _gallery_metadata_adapter(gallery_id: str) -> _GalleryMetadataAdapter:
    from gallery_catalog import get_db

    return _GalleryMetadataAdapter(gallery_id=gallery_id, database_loader=get_db)


_METADATA_SOURCES = _MetadataSourceRegistry(
    site=_SiteMetadataAdapter(load_image_json),
    gallery_factory=_gallery_metadata_adapter,
    normalize_gallery_id=normalize_gallery_id,
)


def sanitize_comment(comment: dict, **kwargs: Any) -> Any:
    return _sanitizer_from_path(DATA_DIR / "sanitize_blocklist.json").sanitize_comment(
        comment, **kwargs
    )


def _load_image_json(
    work_id: int,
    page_index: int = 0,
    gallery_id: str = "site",
) -> dict:
    return _METADATA_SOURCES.load(gallery_id, work_id, page_index)


MAX_FREE_LONG_EDGE = _MODULE_MAX_FREE_LONG_EDGE
MAX_FREE_PIXELS = _MODULE_MAX_FREE_PIXELS
MAX_FREE_STEPS = _MODULE_MAX_FREE_STEPS
fit_opus_free_size = _module_fit_opus_free_size
build_generate_payload = _module_build_generate_payload
prompt_snapshot_from_comment = _module_prompt_snapshot_from_comment
comment_from_png = _module_comment_from_png
prompt_snapshot_from_png = _module_prompt_snapshot_from_png
_parse_comment = _module_parse_comment
_normalize_nested_prompt_objects = _module_normalize_comment
_get_effective_comment = _module_effective_comment
_normalize_style_tag = _module_normalize_style_tag
_normalize_style_tag_for_match = _module_normalize_style_tag_for_match
_style_tag_index = _module_style_index
_style_kind_and_posts = _module_style_kind_and_posts
style_index_stats = _module_style_index_stats
reload_style_index = _module_reload_style_index
extract_style_slots_from_comment = _module_extract_style_slots_from_comment
combine_style_slots = _module_combine_style_slots
replace_style_in_text = _module_replace_style_in_text
replace_style_in_comment = _module_replace_style_in_comment
append_style_to_comment = _module_append_style_to_comment
def apply_style_preset_to_comment(
    comment: dict,
    style_text: str,
) -> tuple[dict, int, int, bool]:
    return _module_apply_style_preset_to_comment(
        comment,
        style_text,
        detector=extract_style_slots_from_comment,
    )
apply_generation_settings = _module_apply_generation_settings


def prepare_work_draft(
    work_id: int,
    page_index: int = 0,
    *,
    recipe: dict[str, Any],
    patched_comment: dict | None = None,
    gallery_id: str = "site",
) -> dict[str, Any]:
    """Compatibility Adapter from the facade to the Remix Recipe compiler."""

    primitives = _RemixPrimitives(
        extract_chars=extract_chars,
        merge_extract_with_draft=_merge_extract_with_draft,
        clean_plain_ark_workbench_draft=clean_plain_ark_workbench_draft,
        is_all_gender_target=_is_all_gender_target,
        pick_target_char_index=pick_target_char_index,
        infer_preset_gender=_infer_preset_gender,
        transform=transform,
        apply_style_payload=apply_style_payload,
        replace_style_in_comment=replace_style_in_comment,
        sanitize_comment=sanitize_comment,
        chars_from_comment=_chars_from_comment,
    )
    return _module_compile_remix_recipe(
        work_id,
        page_index,
        recipe=recipe,
        patched_comment=patched_comment,
        gallery_id=gallery_id,
        primitives=primitives,
    )
