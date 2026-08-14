"""Compile remote AITag metadata into a zero-generation Studio Draft."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping

from nai_anima_adapter import apply_anima_character_to_comment
from nai_char_modules.metadata import ImageMetadataSource
from nai_char_modules.remix import apply_generation_settings
from nai_char_modules.snapshots import effective_comment, prompt_snapshot_from_comment

from .external import AitagWorkDetail, parse_aitag_json
from .recipe import (
    CharacterAsset,
    CharacterCandidate,
    RemixRecipe,
    discover_character_candidates,
    select_character_candidate,
)


@dataclass(frozen=True)
class AitagMetadataAdapter(ImageMetadataSource):
    """Expose one normalized remote detail through the metadata-source Seam."""

    detail: AitagWorkDetail

    def load(self, work_id: int | str, page_index: int = 0) -> dict:
        if str(work_id) != self.detail.work.work_id:
            raise ValueError("AITag metadata source does not contain that work")
        if page_index < 0 or page_index >= len(self.detail.images):
            raise ValueError("AITag image index is out of range")
        image = self.detail.images[page_index]
        parsed = parse_aitag_json(image.ai_json)
        if isinstance(parsed, Mapping):
            metadata = copy.deepcopy(dict(parsed))
        else:
            metadata = {}
        if image.prompt_text and not any(
            metadata.get(key) for key in ("Description", "prompt", "Comment")
        ):
            metadata["Description"] = image.prompt_text
        if image.model:
            metadata.setdefault("Source", image.model)
        return metadata


_CHARACTER_CATEGORIES = frozenset(
    {"identity", "gender", "body", "appearance", "creature"}
)


def _tag_key(value: str) -> str:
    from char_tag_db import weighted_tag_inner

    inner = weighted_tag_inner(value)
    return str(inner or value or "").strip().casefold().replace("_", " ")


def _scene_prompt(prompt: str, source_record: Mapping[str, Any] | None) -> str:
    """Remove source character facts while preserving scene/style token spelling."""

    from char_tag_db import split_prompt_tags

    if source_record is not None:
        from nai_anima_adapter import adapt_anima_character

        card = adapt_anima_character(dict(source_record))
        character_keys = {
            _tag_key(value)
            for value in [
                *(card.get("character_tags") or []),
                card.get("base_subject_tag") or "",
            ]
            if _tag_key(value)
        }
        kept = [
            token
            for token in split_prompt_tags(prompt)
            if _tag_key(token) not in character_keys
        ]
        if kept:
            return ", ".join(kept).strip(" ,")

    from aitag_core.recognition import analyze_slot_caption

    analysis = analyze_slot_caption(prompt)
    kept = [
        item.token.raw
        for item in analysis.tokens
        if item.category not in _CHARACTER_CATEGORIES
    ]
    return ", ".join(value for value in kept if value).strip(" ,")


def _base_comment(
    detail: AitagWorkDetail,
    image_index: int,
    recipe: RemixRecipe,
    source_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata = AitagMetadataAdapter(detail).load(detail.work.work_id, image_index)
    comment = effective_comment(metadata)
    v4 = comment.get("v4_prompt") or {}
    caption = (v4.get("caption") or {}) if isinstance(v4, Mapping) else {}
    existing_slots = caption.get("char_captions") or []
    source_prompt = str(
        caption.get("base_caption") or recipe.prompt or metadata.get("Description") or ""
    ).strip()
    base_prompt = source_prompt if existing_slots else (
        _scene_prompt(source_prompt, source_record) or source_prompt
    )
    comment = apply_generation_settings(
        comment,
        {
            "prompt": base_prompt,
            "negative_prompt": recipe.negative_prompt,
        },
    )
    if recipe.model:
        comment["model"] = recipe.model
    return comment


def _candidate_for_image(
    candidates: tuple[CharacterCandidate, ...],
    image_index: int,
    slot_index: int,
) -> CharacterCandidate | None:
    try:
        return select_character_candidate(
            candidates,
            image_index=image_index,
            slot_index=slot_index,
        )
    except ValueError:
        return None


_SUBJECT_COUNT_RE = re.compile(r"^(\d+)(girl|girls|boy|boys|other|others)$")
_SUBJECT_KIND = {
    "girl": "girl",
    "girls": "girl",
    "boy": "boy",
    "boys": "boy",
    "other": "other",
    "others": "other",
}


def _subject_count(value: str) -> tuple[str, int] | None:
    normalized = _tag_key(value).replace(" ", "")
    match = _SUBJECT_COUNT_RE.fullmatch(normalized)
    if not match:
        return None
    return _SUBJECT_KIND[match.group(2)], int(match.group(1))


def _subject_tag(kind: str, count: int) -> str:
    if kind == "girl":
        return f"{count}{'girl' if count == 1 else 'girls'}"
    if kind == "boy":
        return f"{count}{'boy' if count == 1 else 'boys'}"
    return f"{count}{'other' if count == 1 else 'others'}"


def _replace_base_subject(
    base_prompt: str,
    source_subject: str,
    target_subject: str,
) -> str:
    """Replace one slot's subject contribution without changing scene/style."""

    source = _subject_count(source_subject)
    target = _subject_count(target_subject)
    if target is None or (source is not None and source[0] == target[0]):
        return base_prompt

    from char_tag_db import split_prompt_tags

    counts = {"girl": 0, "boy": 0, "other": 0}
    kept: list[str] = []
    for token in split_prompt_tags(base_prompt):
        parsed = _subject_count(token)
        if parsed is None:
            kept.append(token)
            continue
        counts[parsed[0]] += parsed[1]

    if source is not None and counts[source[0]]:
        counts[source[0]] = max(0, counts[source[0]] - 1)
    counts[target[0]] += 1
    subject_tags = [
        _subject_tag(kind, counts[kind])
        for kind in ("girl", "boy", "other")
        if counts[kind] > 0
    ]
    return ", ".join([*subject_tags, *kept]).strip(" ,")


def _has_slot(comment: dict[str, Any], slot_index: int) -> bool:
    v4 = comment.get("v4_prompt") or {}
    caption = (v4.get("caption") or {}) if isinstance(v4, Mapping) else {}
    slots = caption.get("char_captions") or []
    return bool(
        slot_index < len(slots)
        and isinstance(slots[slot_index], Mapping)
        and str(slots[slot_index].get("char_caption") or "").strip()
    )


def _candidate_gender(candidate: CharacterCandidate) -> str:
    role = str(candidate.role or "").strip().lower()
    if role in {"male", "female"}:
        return role
    asset = getattr(candidate, "character", None) or getattr(candidate, "asset", None)
    tags = {
        str(tag or "").strip().casefold()
        for tag in (
            *(getattr(asset, "identity_tags", ()) or ()),
            *(getattr(asset, "appearance_tags", ()) or ()),
        )
    }
    if tags & {"1girl", "female_focus", "girls_only", "solo_female"}:
        return "female"
    if tags & {"1boy", "male_focus", "boys_only", "solo_male"}:
        return "male"
    return "unknown"


def _resolve_slot_indexes(
    candidates: tuple[CharacterCandidate, ...],
    *,
    image_index: int,
    slot_index: int,
    slot_indexes: list[int] | None,
    gender_scope: str,
    require_gender_match: bool = True,
) -> list[int]:
    page = [c for c in candidates if int(c.image_index) == int(image_index)]
    scope = str(gender_scope or "").strip().lower()
    if scope in {"male", "female"}:
        indexes = sorted(
            {
                int(c.slot_index)
                for c in page
                if _candidate_gender(c) == scope and 0 <= int(c.slot_index) < 6
            }
        )
        if indexes:
            return indexes
        if require_gender_match:
            raise ValueError(
                f"p{image_index} 没有可替换的{('男' if scope == 'male' else '女')}性角色槽"
            )
        return [max(0, min(5, int(slot_index)))]
    if scope in {"all", "all_slots", "*"}:
        indexes = sorted({int(c.slot_index) for c in page if 0 <= int(c.slot_index) < 6})
        if indexes:
            return indexes
        return [max(0, min(5, int(slot_index)))]
    if slot_indexes:
        cleaned = sorted(
            {max(0, min(5, int(i))) for i in slot_indexes if str(i).strip() != ""}
        )
        if cleaned:
            return cleaned
    return [max(0, min(5, int(slot_index)))]


def _ensure_v4_slot(comment: dict[str, Any], slot_index: int, caption: str = "") -> dict[str, Any]:
    v4 = comment.setdefault("v4_prompt", {})
    if not isinstance(v4, dict):
        v4 = {}
        comment["v4_prompt"] = v4
    cap = v4.setdefault("caption", {})
    if not isinstance(cap, dict):
        cap = {}
        v4["caption"] = cap
    slots = list(cap.get("char_captions") or [])
    while len(slots) <= slot_index:
        slots.append({"char_caption": "", "centers": [{"x": 0.5, "y": 0.5}]})
    current = slots[slot_index] if isinstance(slots[slot_index], dict) else {"centers": [{"x": 0.5, "y": 0.5}]}
    if caption and not str(current.get("char_caption") or "").strip():
        current = {**current, "char_caption": caption}
    slots[slot_index] = current
    cap["char_captions"] = slots[:6]
    return comment


def _apply_target_character(
    comment: dict[str, Any],
    target_record: Mapping[str, Any],
    *,
    slot_index: int,
    source_caption: str = "",
    model: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write a target into one V4 slot.

    Custom OC presets keep their whole ``char_caption`` (same path as local
    char-swap). Named library records still go through the Anima adapter.
    """

    record = dict(target_record or {})
    oc_caption = str(record.get("char_caption") or "").strip()
    kind = str(record.get("kind") or "").strip().lower()
    comment = _ensure_v4_slot(comment, slot_index, source_caption)
    if oc_caption or kind == "oc":
        from aitag_core.transform.planner import apply_replacement_plan, plan_replacement

        v4 = comment.get("v4_prompt") or {}
        cap = v4.get("caption") or {} if isinstance(v4, dict) else {}
        slots = cap.get("char_captions") or [] if isinstance(cap, dict) else []
        current = ""
        if slot_index < len(slots) and isinstance(slots[slot_index], dict):
            current = str(slots[slot_index].get("char_caption") or "")
        gender = str(record.get("gender") or "").strip().lower()
        plan = plan_replacement(
            {"char_caption": current or source_caption},
            record,
            slot_index=slot_index,
            preserve_action=True,
            force_gender=gender if gender in {"male", "female"} else None,
        )
        patched = apply_replacement_plan(comment, plan)
        subject = "1boy" if gender == "male" else "1girl" if gender == "female" else ""
        return patched, {
            "character_caption": plan.output_caption,
            "base_subject_tag": subject,
            "label": str(record.get("name") or record.get("label") or record.get("character") or ""),
        }
    return apply_anima_character_to_comment(
        comment, record, slot_index=slot_index, model=model
    )


def _apply_style_to_comment(
    comment: dict[str, Any],
    *,
    style_find: str = "",
    style_replace: str = "",
    style_mode: str = "replace",
) -> tuple[dict[str, Any], int]:
    """Apply the same style rewrite path local char-swap uses."""

    find = str(style_find or "").strip()
    replace = str(style_replace or "")
    mode = str(style_mode or "replace").strip().lower()
    if not find and not str(replace).strip():
        return comment, 0
    from nai_char_modules.style import append_style_to_comment, replace_style_in_comment

    if mode == "append" or (not find and str(replace).strip()):
        return append_style_to_comment(comment, replace)
    return replace_style_in_comment(comment, find, replace)


def compile_aitag_studio_draft(
    detail: AitagWorkDetail,
    *,
    image_index: int = 0,
    slot_index: int = 0,
    slot_indexes: list[int] | None = None,
    gender_scope: str = "",
    target_record: Mapping[str, Any] | None = None,
    target_reference_id: str = "",
    style_find: str = "",
    style_replace: str = "",
    style_mode: str = "replace",
    base_comment: Mapping[str, Any] | None = None,
    model: str = "",
    batch_count: int = 1,
) -> dict[str, Any]:
    """Build a complete Studio Draft without invoking any generation provider.

    Supports multi-slot gender scope (local「全部换角」) and style find/replace
    (local「画风替换」) on the same zero-generation path.

    When ``base_comment`` is provided, character/style edits stack on that
    draft instead of recompiling from the original image metadata.
    """

    if image_index < 0 or image_index >= len(detail.images):
        raise ValueError("AITag image index is out of range")
    if slot_index < 0 or slot_index >= 6:
        raise ValueError("NovelAI character slot index must be between 0 and 5")
    image = detail.images[image_index]
    candidates = discover_character_candidates(detail)
    resolved_slots = _resolve_slot_indexes(
        candidates,
        image_index=image_index,
        slot_index=slot_index,
        slot_indexes=slot_indexes,
        gender_scope=gender_scope,
        require_gender_match=True,
    )
    primary_slot = resolved_slots[0] if resolved_slots else slot_index
    source_candidate = _candidate_for_image(candidates, image_index, primary_slot)
    recipe = RemixRecipe.from_aitag(detail.work, image)
    source_record = source_candidate.to_reference_record() if source_candidate else None
    if isinstance(base_comment, Mapping) and base_comment:
        comment = copy.deepcopy(dict(base_comment))
    else:
        comment = _base_comment(detail, image_index, recipe, source_record)

    selected_record: dict[str, Any] | None = None
    selected_asset: CharacterAsset | None = None
    if target_record is not None:
        selected_record = dict(target_record)
        selected_asset = CharacterAsset.from_reference_record(selected_record)
    elif (
        target_record is None
        and not str(style_find or "").strip()
        and not str(style_replace or "").strip()
        and source_record is not None
        and not _has_slot(comment, primary_slot)
    ):
        # Only auto-fill empty slots when building a plain original draft.
        selected_record = dict(source_record)

    card: dict[str, Any] | None = None
    applied_slots: list[int] = []
    if selected_record is not None:
        v4 = comment.get("v4_prompt") or {}
        caption = (v4.get("caption") or {}) if isinstance(v4, Mapping) else {}
        preserved_base = str(caption.get("base_caption") or comment.get("prompt") or "")
        model_name = str(model or recipe.model or image.model or "")
        # Apply every slot first, then rewrite base subject once per source slot.
        # Avoids compounding base-tag drift when multi-slot gender replace runs.
        source_subjects: list[str] = []
        for si in resolved_slots:
            source_for_slot = _candidate_for_image(candidates, image_index, si)
            if target_record is not None and source_for_slot is not None:
                from nai_anima_adapter import adapt_anima_character

                source_subjects.append(
                    str(
                        adapt_anima_character(
                            dict(source_for_slot.to_reference_record())
                        ).get("base_subject_tag")
                        or ""
                    )
                )
            else:
                source_subjects.append("")
            comment, card = _apply_target_character(
                comment,
                selected_record,
                slot_index=si,
                source_caption=str(source_for_slot.caption if source_for_slot is not None else ""),
                model=model_name,
            )
            applied_slots.append(si)

        if target_record is not None:
            target_subject = str((card or {}).get("base_subject_tag") or "")
            final_base = preserved_base
            for source_subject in source_subjects:
                final_base = _replace_base_subject(
                    final_base,
                    source_subject,
                    target_subject,
                )
            comment["prompt"] = final_base
            if isinstance(comment.get("v4_prompt"), dict):
                cap = comment["v4_prompt"].setdefault("caption", {})
                if isinstance(cap, dict):
                    cap["base_caption"] = final_base
            if selected_asset is not None:
                recipe = recipe.with_character(selected_asset, prompt=final_base)

    style_replacements = 0
    comment, style_replacements = _apply_style_to_comment(
        comment,
        style_find=style_find,
        style_replace=style_replace,
        style_mode=style_mode,
    )

    params = {
        key: comment.get(key)
        for key in ("width", "height", "steps", "scale", "sampler", "seed")
    }
    params["batch"] = max(1, min(int(batch_count or 1), 64))
    remote_work_id = str(detail.work.work_id or "")
    # Prefer numeric workId when it fits JS-safe range; always keep string in source.
    work_id_num = 0
    if remote_work_id.isdigit():
        try:
            parsed = int(remote_work_id)
            if 0 < parsed <= 9_007_199_254_740_991:  # Number.MAX_SAFE_INTEGER
                work_id_num = parsed
        except ValueError:
            work_id_num = 0
    draft = {
        "galleryId": "aitag-online",
        "workId": work_id_num,
        "pageIndex": image_index,
        "title": detail.work.title or f"AITag {detail.work.work_id}",
        "thumb": image.thumbnail_url or image.url,
        "comment": comment,
        "texts": prompt_snapshot_from_comment(comment),
        "params": params,
        "refs": {"vibe": "", "char": "", "strength": "0.6"},
        "source": {
            "provider": "aitag-online",
            "workId": remote_work_id,
            "workIdStr": remote_work_id,
            "imageId": image.image_id,
            "imageIndex": image_index,
            "title": detail.work.title or f"AITag {detail.work.work_id}",
            "thumb": image.thumbnail_url or image.url or "",
        },
    }
    if target_reference_id:
        draft["reference"] = {
            "referenceId": target_reference_id,
            "slotIndex": primary_slot,
        }
        selected_slots = list(applied_slots or resolved_slots)
        if len(selected_slots) > 1:
            draft["reference"]["slotIndexes"] = selected_slots
    return {
        "draft": draft,
        "recipe": recipe.to_dict(),
        "card": card,
        "candidates": [candidate.to_dict() for candidate in candidates],
        "work_id": detail.work.work_id,
        "image_id": image.image_id,
        "image_index": image_index,
        "slot_index": primary_slot,
        "slot_indexes": list(applied_slots or resolved_slots),
        "style_replacements": int(style_replacements or 0),
    }


def compile_aitag_studio_drafts(
    detail: AitagWorkDetail,
    *,
    image_indexes: list[int] | None = None,
    slot_index: int = 0,
    gender_scope: str = "",
    target_record: Mapping[str, Any] | None = None,
    target_reference_id: str = "",
    style_find: str = "",
    style_replace: str = "",
    style_mode: str = "replace",
    base_comments: Mapping[int, Mapping[str, Any]] | None = None,
    model: str = "",
    batch_count: int = 1,
) -> dict[str, Any]:
    """Compile one draft per image (local「全部图片」).

    ``base_comments`` maps image_index -> previous NAI comment so multi-step
    edits (char then style, or slot A then slot B) stack correctly.
    """

    if image_indexes is None:
        indexes = list(range(len(detail.images)))
    else:
        indexes = [int(i) for i in image_indexes]
    pages: list[dict[str, Any]] = []
    errors: list[str] = []
    base_map = {
        int(k): v
        for k, v in (base_comments or {}).items()
        if isinstance(v, Mapping)
    }
    for image_index in indexes:
        try:
            pages.append(
                compile_aitag_studio_draft(
                    detail,
                    image_index=image_index,
                    slot_index=slot_index,
                    gender_scope=gender_scope,
                    target_record=target_record,
                    target_reference_id=target_reference_id,
                    style_find=style_find,
                    style_replace=style_replace,
                    style_mode=style_mode,
                    base_comment=base_map.get(image_index),
                    model=model,
                    batch_count=batch_count,
                )
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"p{image_index}: {exc}")
    if not pages:
        raise ValueError("; ".join(errors) if errors else "no pages compiled")
    # 顶层身份优先取封面页（image_index=0）：封面编译失败时才回退到第一个
    # 成功页，避免多页作品的草稿标题/缩略图/身份静默变成中间页。
    first = next(
        (page for page in pages if int(page.get("image_index") or 0) == 0),
        pages[0],
    )
    requested = len(indexes)
    ok_pages = len(pages)
    return {
        **first,
        "pages": pages,
        "page_count": ok_pages,
        "requested_pages": requested,
        "errors": errors,
        "ok_pages": ok_pages,
        "partial": bool(errors) and ok_pages > 0,
        "failed_pages": list(errors),
    }


__all__ = [
    "AitagMetadataAdapter",
    "compile_aitag_studio_draft",
    "compile_aitag_studio_drafts",
]
