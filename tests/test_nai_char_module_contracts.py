from __future__ import annotations

import inspect

import nai_char


PUBLIC_CALL_SIGNATURES = {
    "apply_style_payload": "(payload: 'dict') -> 'dict[str, Any]'",
    "batch_preview": "(payload: 'dict') -> 'dict[str, Any]'",
    "build_generate_payload": "(patched_comment: 'dict', *, force_free: 'bool' = True) -> 'dict[str, Any]'",
    "clean_plain_ark_workbench_draft": "(comment: 'dict', work_id: 'int | None', page_index: 'int' = 0, gallery_id: 'str' = 'site') -> 'dict'",
    "clear_extract_chars_cache": "(work_id: 'int | None' = None) -> 'None'",
    "extract_chars": "(work_id: 'int', page_index: 'int' = 0, gallery_id: 'str' = 'site') -> 'dict[str, Any]'",
    "list_char_presets": "(gender: 'str | None' = None) -> 'list[dict]'",
    "prepare_work_draft": "(work_id: 'int', page_index: 'int' = 0, *, recipe: 'dict[str, Any]', patched_comment: 'dict | None' = None, gallery_id: 'str' = 'site') -> 'dict[str, Any]'",
    "prompt_snapshot_from_comment": "(comment: 'dict') -> 'dict[str, Any]'",
    "prompt_snapshot_from_png": "(path: 'Path | str') -> 'dict[str, Any] | None'",
    "reload_style_index": "() -> 'dict[str, Any]'",
    "sanitize_payload": "(payload: 'dict') -> 'dict[str, Any]'",
    "style_index_stats": "() -> 'dict[str, Any]'",
    "transform": "(payload: 'dict', *, source_data: 'dict[str, Any] | None' = None, include_style_slots: 'bool' = True) -> 'dict[str, Any]'",
}


def test_legacy_nai_char_interface_keeps_stable_names_and_call_shapes() -> None:
    """Routes, the Butler, Generation Jobs and scripts import this facade directly."""

    actual = {
        name: str(inspect.signature(getattr(nai_char, name)))
        for name in PUBLIC_CALL_SIGNATURES
    }
    assert actual == PUBLIC_CALL_SIGNATURES
    assert nai_char.BATCH_TARGET_MAX == 250
    assert nai_char.MAX_FREE_LONG_EDGE == 1216
    assert nai_char.MAX_FREE_PIXELS == 1024 * 1024
    assert nai_char.MAX_FREE_STEPS == 28


def test_generate_payload_characterization_preserves_cost_and_v4_contract() -> None:
    draft = {
        "Source": "NovelAI Diffusion V4.5",
        "prompt": "fallback prompt",
        "negative_prompt": "bad anatomy",
        "width": 1408,
        "height": 1408,
        "steps": 40,
        "seed": "123",
        "v4_prompt": {
            "caption": {
                "base_caption": "studio scene",
                "char_captions": [
                    {
                        "char_caption": "1girl, test_character",
                        "centers": [{"x": 0.25, "y": 0.75}],
                    }
                ],
            },
            "use_coords": True,
        },
        "v4_negative_prompt": {"caption": {"base_caption": "bad anatomy"}},
    }

    result = nai_char.build_generate_payload(draft, force_free=True)

    assert set(result) == {
        "action",
        "free_eligible",
        "height",
        "input",
        "model",
        "parameters",
        "request_type",
        "requested_action",
        "resized_for_free",
        "steps",
        "unknown_fields",
        "unsupported_fields",
        "width",
    }
    assert result["requested_action"] == "generate"
    assert result["unsupported_fields"] == []
    assert isinstance(result["unknown_fields"], list)
    assert result["action"] == "generate"
    assert result["request_type"] == "PromptGenerateRequest"
    assert result["model"] == "nai-diffusion-4-5-full"
    assert result["input"] == "studio scene"
    assert result["steps"] == 28
    assert result["resized_for_free"] is True
    assert result["free_eligible"] is True
    assert result["width"] * result["height"] <= nai_char.MAX_FREE_PIXELS

    parameters = result["parameters"]
    assert parameters["n_samples"] == 1
    assert parameters["seed"] == 123
    assert parameters["v4_prompt"]["caption"]["char_captions"] == [
        {
            "char_caption": "1girl, test_character",
            "centers": [{"x": 0.25, "y": 0.75}],
        }
    ]
    assert parameters["v4_negative_prompt"]["caption"]["char_captions"] == [
        {"char_caption": "", "centers": [{"x": 0.25, "y": 0.75}]}
    ]


def test_prompt_snapshot_characterization_is_bounded_and_stable() -> None:
    comment = {
        "prompt": "fallback",
        "uc": "x" * 900,
        "seed": 7,
        "steps": 28,
        "width": 832,
        "height": 1216,
        "v4_prompt": {
            "caption": {
                "base_caption": "b" * 2100,
                "char_captions": [{"char_caption": "1girl, card", "centers": []}],
            }
        },
    }

    snapshot = nai_char.prompt_snapshot_from_comment(comment)

    assert set(snapshot) == {
        "base_caption",
        "char_captions",
        "height",
        "seed",
        "steps",
        "uc",
        "width",
    }
    assert len(snapshot["base_caption"]) == 2000
    assert len(snapshot["uc"]) == 800
    assert snapshot["char_captions"] == [
        {"index": 0, "caption": "1girl, card", "center": {"x": 0.5, "y": 0.5}}
    ]
