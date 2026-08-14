from __future__ import annotations

import pytest

from aitag_core.external import normalize_aitag_detail, normalize_aitag_work
from aitag_core.qualification import aitag_work_is_nai
from aitag_core.recipe import (
    CharacterAsset,
    RemixRecipe,
    discover_character_candidates,
    select_character_candidate,
)
from aitag_core.studio import compile_aitag_studio_draft


def _multi_character_detail():
    return normalize_aitag_detail(
        {
            "id": "work-multi",
            "title": "Two characters",
            "images": [
                {
                    "id": "image-multi",
                    "aiJson": {
                        "Software": "NovelAI",
                        "Source": "NovelAI Diffusion V4.5",
                        "Comment": {
                            "prompt": "2girls, moonlit street, watercolor",
                            "v4_prompt": {
                                "caption": {
                                    "base_caption": "2girls, moonlit street, watercolor",
                                    "char_captions": [
                                        {
                                            "char_caption": "girl, red hair, green eyes",
                                            "centers": [{"x": 0.25, "y": 0.5}],
                                        },
                                        {
                                            "char_caption": "girl, blue hair, blue eyes",
                                            "centers": [{"x": 0.75, "y": 0.5}],
                                        },
                                    ],
                                }
                            },
                        },
                    },
                }
            ],
        }
    )


def test_recipe_swap_removes_source_identity_and_keeps_scene_style() -> None:
    source = CharacterAsset(
        asset_id="source",
        label="Source",
        identity_tags=("1girl",),
        appearance_tags=("red hair", "green eyes"),
    )
    target = CharacterAsset(
        asset_id="target",
        label="Target",
        identity_tags=("1boy",),
        appearance_tags=("black hair", "golden eyes"),
    )
    recipe = RemixRecipe(
        recipe_id="recipe",
        prompt="1girl, red hair, green eyes, moonlit street, watercolor",
        character=source,
    )

    swapped = recipe.with_character(target)

    assert swapped.prompt == "moonlit street, watercolor"
    assert "red hair" not in swapped.prompt
    assert "green eyes" not in swapped.prompt
    assert swapped.character is target


def test_cross_gender_swap_updates_subject_count_and_preserves_other_slot() -> None:
    detail = _multi_character_detail()
    original_second_slot = (
        detail.images[0].ai_json["Comment"]["v4_prompt"]["caption"][
            "char_captions"
        ][1]
    )
    target = {
        "id": "target-boy",
        "name": "Target boy",
        "source": "local",
        "core_tags": ["1boy", "black hair", "golden eyes"],
    }

    compiled = compile_aitag_studio_draft(
        detail,
        image_index=0,
        slot_index=0,
        target_record=target,
    )

    caption = compiled["draft"]["comment"]["v4_prompt"]["caption"]
    assert caption["base_caption"] == (
        "1girl, 1boy, moonlit street, watercolor"
    )
    assert "black hair" in caption["char_captions"][0]["char_caption"]
    assert "red hair" not in caption["char_captions"][0]["char_caption"]
    assert caption["char_captions"][1] == original_second_slot
    assert compiled["recipe"]["prompt"] == caption["base_caption"]
    assert "red hair" not in compiled["recipe"]["prompt"]
    assert "green eyes" not in compiled["recipe"]["prompt"]
    assert compiled["recipe"]["character"]["label"] == "Target boy"


def test_online_oc_replace_writes_caption_and_keeps_slot_action() -> None:
    detail = normalize_aitag_detail(
        {
            "id": "work-oc-swap",
            "title": "Boy and woman",
            "images": [
                {
                    "id": "image-oc",
                    "aiJson": {
                        "Software": "NovelAI",
                        "Source": "NovelAI Diffusion V4.5",
                        "Comment": {
                            "prompt": "2people, indoors",
                            "v4_prompt": {
                                "caption": {
                                    "base_caption": "2people, indoors",
                                    "char_captions": [
                                        {
                                            "char_caption": "faceless boy, standing, black randoseru",
                                            "centers": [{"x": 0.25, "y": 0.5}],
                                        },
                                        {
                                            "char_caption": "woman, tall, big breasts, plump",
                                            "centers": [{"x": 0.75, "y": 0.5}],
                                        },
                                    ],
                                }
                            },
                        },
                    },
                }
            ],
        }
    )
    oc = {
        "id": "feijibei",
        "name": "费济北",
        "label": "费济北",
        "gender": "male",
        "kind": "oc",
        "identity": ["1boy", "male_focus"],
        "char_caption": "1boy, 18 years old, slim, youthful, black hair",
    }

    compiled = compile_aitag_studio_draft(
        detail,
        image_index=0,
        slot_index=0,
        target_record=oc,
        target_reference_id="preset:male:feijibei",
    )

    slots = compiled["draft"]["comment"]["v4_prompt"]["caption"]["char_captions"]
    first = slots[0]["char_caption"]
    assert "18 years old" in first
    assert "slim" in first
    assert "standing" in first
    assert "faceless boy" not in first
    assert slots[1]["char_caption"] == "woman, tall, big breasts, plump"
    assert compiled["draft"]["reference"]["referenceId"] == "preset:male:feijibei"


def test_ai_json_software_and_source_are_novelai_qualification_evidence() -> None:
    work = normalize_aitag_work(
        {
            "id": "nai-json-only",
            "images": [
                {
                    "id": "image",
                    "promptText": "1girl, cafe",
                    "aiJson": {
                        "Software": "NovelAI",
                        "Source": "NovelAI Diffusion V4",
                    },
                }
            ],
        }
    )

    assert aitag_work_is_nai(work) is True
    assert work.qualification == "direct"


def test_candidate_selector_honors_exact_candidate_and_never_falls_back() -> None:
    candidates = discover_character_candidates(_multi_character_detail())

    selected = select_character_candidate(
        candidates,
        candidate_id=candidates[1].candidate_id,
    )

    assert selected.slot_index == 1
    assert "blue hair" in selected.character.appearance_tags
    with pytest.raises(ValueError, match="not found"):
        select_character_candidate(
            candidates,
            candidate_id=candidates[1].candidate_id,
            slot_index=0,
        )
