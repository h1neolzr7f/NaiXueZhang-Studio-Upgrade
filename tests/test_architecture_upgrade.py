from __future__ import annotations

import os
import tempfile
import sys
import unittest
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from aitag_core.prompt import tokenize_prompt
from aitag_core.recognition import analyze_slot_caption, classify_token, match_oc_preset
from aitag_core.transform import apply_replacement_plan, plan_replacement
from char_tag_db import classify_caption_buckets, pick_character_summary
from db import Database
from nai_char import (
    clean_plain_ark_workbench_draft,
    _chars_from_plain_character_prompt,
    _plain_ark_base_after_replacement,
    _preserve_action_tags,
    build_generate_payload,
    extract_chars,
    prepare_work_draft,
    transform,
)
from pixiv_launch import (
    _clean_stale_ai_warning,
    _job_progress,
    launch_status,
    _resolve_selection_batches,
    _upload_require_processed,
    _upload_pipeline_overrides,
    normalize_ai_config,
)
from post_pipeline import DEFAULTS as PIPELINE_DEFAULTS
from post_pipeline import (
    GENERATED_DIR,
    _write_meta,
    _strip_metadata,
    merge_pipeline_config,
    mosaic_runtime_status,
    pipeline_item_state,
)
from nai_api import (
    PROVIDER_NOVELAI,
    PROVIDER_XIANYUN,
    _TOKEN_FAILURES,
    _candidate_token_entries,
    _enabled_token_entries,
    _record_token_failure,
    _xianyun_body_from_payload,
)


LEGACY_GALLERY_FIXTURE_TESTS = {
    "test_144899810_all_pages_have_stable_slot_roles",
    "test_all_page_all_gender_guard_without_identity_is_skipped",
    "test_all_page_generic_gender_identity_is_not_a_match",
    "test_all_page_identity_guard_replaces_matching_female_character",
    "test_all_page_identity_guard_skips_different_female_character",
    "test_batch_prepare_all_page_generic_identity_is_skipped",
    "test_char_marker_replacement_has_no_stale_negative_slots",
    "test_current_page_all_female_slots_replaces_without_identity_guard",
    "test_multi_replacement_identity_guard_skips_different_character",
    "test_oc_replacement_keeps_identity_and_cleans_v4_base",
    "test_plain_ark_prompt_recognizes_spaced_character_tag",
    "test_plain_ark_workbench_draft_is_cleaned_before_generation",
    "test_replace_creature_flag_does_not_override_all_slot_mode",
    "test_stringified_v4_prompt_metadata_does_not_crash_extraction",
}


def _legacy_gallery_fixtures_available() -> bool:
    database = Path(__file__).resolve().parents[1] / "data" / "aitag.db"
    if not database.is_file():
        return False
    try:
        with closing(sqlite3.connect(database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM work_images WHERE work_id IN (144899810, 127760436, 127751944)"
            ).fetchone()[0]
        return int(count) >= 16
    except sqlite3.Error:
        return False


class ArchitectureUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        if (
            self._testMethodName in LEGACY_GALLERY_FIXTURE_TESTS
            and not _legacy_gallery_fixtures_available()
        ):
            self.skipTest("optional legacy gallery fixture database is not installed")

    def test_schema_initializes_on_empty_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with Database(Path(tmp) / "empty.sqlite") as db:
                work_cols = {
                    row["name"]
                    for row in db.conn.execute("PRAGMA table_info(works)").fetchall()
                }
                index_names = {
                    row["name"]
                    for row in db.conn.execute("PRAGMA index_list(works)").fetchall()
                }
                self.assertIn("preview_attempts", work_cols)
                self.assertIn("idx_works_preview_pending", index_names)

    def test_token_classification_keeps_noise_out_of_identity(self) -> None:
        cases = {
            "standing": "action",
            "open mouth": "action",
            "from side": "action",
            "disembodied hand": "action",
            "grabbing another's ass": "action",
            "spreading another's anus": "action",
            "breast sucking": "action",
            "grabbing another's hair": "action",
            "sex": "action",
            "small breasts": "body",
            "large penis": "body",
            "no panties": "appearance",
            "silverash_(arknights)": "identity",
            "sussurro_(summer_flower)_(arknights)": "identity",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                token = tokenize_prompt(raw)[0]
                self.assertEqual(classify_token(token).category, expected)

    def test_character_summary_prefers_weighted_character_over_solo_noise(self) -> None:
        cap = (
            "girl, solo, 1.5:: shining (arknights), brown eyes, white hair, "
            "large breasts::"
        )
        buckets = classify_caption_buckets(cap)
        self.assertNotIn("solo", buckets.get("identity") or [])
        self.assertIn("1.5::shining (arknights)::", buckets.get("identity") or [])
        self.assertEqual(
            pick_character_summary(cap, buckets.get("identity") or []),
            "shining",
        )

    def test_character_summary_extracts_wrapped_character_tag(self) -> None:
        cap = (
            "girl, {{st. louis (luxurious wheels) (azur lane)}}, "
            "{{{{{feater (arknights)_(cosplay),Silver hair}}}}}"
        )
        buckets = classify_caption_buckets(cap)
        self.assertEqual(
            pick_character_summary(cap, buckets.get("identity") or []),
            "feater (arknights)",
        )

    def test_weighted_character_not_misclassified_as_appearance_by_substring(self) -> None:
        cap = "girl, solo, 1.5:: nearl (arknights), "
        buckets = classify_caption_buckets(cap)
        self.assertIn("1.5::nearl (arknights)::", buckets.get("identity") or [])
        self.assertNotIn("1.5::nearl (arknights)::", buckets.get("appearance") or [])

    def test_oc_matcher_does_not_match_substrings(self) -> None:
        preset = {
            "kind": "oc",
            "label": "ding（群友OC）",
            "identity": ["ding_(oc)"],
            "char_caption": "1boy, ding_(oc), black hair",
        }
        self.assertFalse(match_oc_preset("1boy, standing, bent over", preset).matched)
        self.assertTrue(match_oc_preset("1boy, ding_(oc), black hair", preset).matched)

    def test_144899810_all_pages_have_stable_slot_roles(self) -> None:
        for page_index in range(14):
            with self.subTest(page_index=page_index):
                data = extract_chars(144899810, page_index)
                chars = data.get("chars") or []
                self.assertEqual(len(chars), 2)
                female = chars[0]
                male = chars[1]
                self.assertEqual(female.get("identity_name"), "sussurro (summer flower)")
                self.assertEqual(female.get("role"), "female")
                self.assertTrue(female.get("replaceable"))
                self.assertEqual(male.get("identity_name"), None)
                self.assertEqual(male.get("role"), "male")
                self.assertTrue(male.get("replaceable"))
                self.assertFalse(male.get("oc_matched"))

    def test_replacement_plan_preserves_action_and_injects_source(self) -> None:
        target = analyze_slot_caption(
            "boy, disembodied hand, grabbing another's ass, spreading another's anus"
        )
        plan = plan_replacement(
            target,
            {
                "gender": "male",
                "identity": ["silverash_(arknights)"],
                "appearance": ["white hair"],
            },
            preserve_action=True,
            force_gender="male",
        )
        self.assertIn("silverash_(arknights)", plan.output_caption)
        self.assertIn("disembodied hand", plan.output_caption)
        self.assertIn("1boy", plan.output_caption)
        self.assertNotIn("large penis", plan.output_caption)

        patched = apply_replacement_plan(
            {"v4_prompt": {"caption": {"char_captions": [{"char_caption": "boy"}]}}},
            plan,
        )
        self.assertEqual(
            patched["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            plan.output_caption,
        )

    def test_replacement_plan_does_not_preserve_body_tokens(self) -> None:
        target = analyze_slot_caption("1boy, male_focus, standing, black hair, large penis")
        plan = plan_replacement(
            target,
            {"gender": "male", "identity": ["thorn_(arknights)"]},
            preserve_action=True,
            force_gender="male",
        )
        self.assertIn("standing", plan.output_caption)
        self.assertNotIn("large penis", plan.output_caption)
        self.assertNotIn("black hair", plan.output_caption)

    def test_replacement_plan_keeps_oc_identity_with_direct_caption(self) -> None:
        target = analyze_slot_caption("1girl, amiya_(arknights), blue eyes")
        plan = plan_replacement(
            target,
            {
                "gender": "female",
                "kind": "oc",
                "identity": ["12gg_(oc)", "original_character", "1girl", "female_focus"],
                "char_caption": "cat girl, cat ears, long black hair",
            },
            preserve_action=False,
            force_gender="female",
        )
        self.assertIn("12gg_(oc)", plan.output_caption)
        self.assertIn("original_character", plan.output_caption)
        self.assertIn("cat girl", plan.output_caption)
        self.assertNotIn("amiya_(arknights)", plan.output_caption)

    def test_replaced_arknights_character_remains_identity(self) -> None:
        slot = analyze_slot_caption(
            "silverash_(arknights), 1boy, male_focus, white hair, black coat"
        )
        self.assertEqual(slot.identity_name, "silverash")
        self.assertEqual(slot.display_name, "silverash")
        self.assertEqual(slot.role, "male")
        self.assertIn("silverash_(arknights)", slot.token_groups.get("identity") or [])

    def test_plain_ark_base_cleanup_removes_old_character_only(self) -> None:
        base = (
            "artist:redshark_(t373412), priestess_(arknights), arknights, "
            "1girl, dark_grey_hair, lab_coat, standing, looking_at_viewer"
        )
        cleaned = _plain_ark_base_after_replacement(
            base,
            [
                {
                    "ark_library_tag": "priestess_(arknights)",
                    "identity_tags": ["priestess_(arknights)"],
                    "summary": "Priestess",
                }
            ],
        )
        self.assertNotIn("priestess_(arknights)", cleaned)
        self.assertNotIn("arknights", cleaned)
        self.assertNotIn("1girl", cleaned)
        self.assertNotIn("dark_grey_hair", cleaned)
        self.assertIn("artist:redshark_(t373412)", cleaned)
        self.assertIn("standing", cleaned)
        self.assertIn("looking_at_viewer", cleaned)

    def test_plain_ark_prompt_recognizes_spaced_character_tag(self) -> None:
        data = extract_chars(127760436, 0)
        chars = data.get("chars") or []
        self.assertEqual(data.get("prompt_layout"), "plain_ark_library")
        self.assertGreaterEqual(len(chars), 1)
        self.assertEqual(chars[0].get("ark_library_tag"), "amiya_(arknights)")
        self.assertTrue(chars[0].get("replaceable"))
        self.assertIn("amiya_(arknights)", chars[0].get("char_caption") or "")
        self.assertNotIn("artist:", chars[0].get("char_caption") or "")
        self.assertNotIn("standing", chars[0].get("char_caption") or "")

    def test_plain_prompt_uses_danbooru_character_tags_for_slots(self) -> None:
        result = _chars_from_plain_character_prompt(
            "artist:sample, hatsune_miku, rem_(re:zero), 2girls, standing, blue hair"
        )
        self.assertIsNotNone(result)
        chars, base, layout = result or ([], "", "")
        self.assertEqual(layout, "plain_character_tags")
        self.assertEqual(base, "artist:sample, hatsune_miku, rem_(re:zero), 2girls, standing, blue hair")
        self.assertEqual([ch.get("identity_tags") for ch in chars], [["hatsune_miku"], ["rem_(re:zero)"]])
        self.assertEqual([ch.get("summary") for ch in chars], ["hatsune_miku", "rem"])
        self.assertTrue(all(ch.get("replaceable") for ch in chars))

    def test_plain_prompt_does_not_promote_generic_gender_to_character_tag(self) -> None:
        result = _chars_from_plain_character_prompt("1girl, female_focus, standing, blue hair")
        self.assertIsNone(result)

    def test_plain_character_base_cleanup_removes_only_replaced_identity(self) -> None:
        base = "artist:sample, hatsune_miku, rem_(re:zero), 2girls, standing, blue hair"
        cleaned = _plain_ark_base_after_replacement(
            base,
            [
                {
                    "plain_character_tag": "hatsune_miku",
                    "identity_tags": ["hatsune_miku"],
                    "summary": "hatsune_miku",
                    "char_caption": "hatsune_miku",
                }
            ],
        )
        self.assertNotIn("hatsune_miku", cleaned)
        self.assertNotIn("2girls", cleaned)
        self.assertNotIn("blue hair", cleaned)
        self.assertIn("artist:sample", cleaned)
        self.assertIn("standing", cleaned)

    def test_preserve_action_tags_handles_artist_tags(self) -> None:
        actions = _preserve_action_tags(
            "artist:redshark_(t373412), priestess_(arknights), 1girl, standing",
            hooded=False,
        )
        self.assertIn("standing", actions)
        self.assertNotIn("priestess_(arknights)", actions)

    def test_plain_ark_workbench_draft_is_cleaned_before_generation(self) -> None:
        comment = {
            "prompt": "priestess_(arknights), 1girl, dark_grey_hair, lab_coat, standing",
            "v4_prompt": {
                "caption": {
                    "base_caption": (
                        "artist:redshark_(t373412), priestess_(arknights), 1girl, "
                        "dark_grey_hair, lab_coat, standing"
                    ),
                    "char_captions": [
                        {
                            "char_caption": "1girl, female_focus, cat girl, cat ears",
                            "centers": [{"x": 0.5, "y": 0.5}],
                        }
                    ],
                }
            },
        }
        cleaned = clean_plain_ark_workbench_draft(comment, 140404580, 0)
        base = cleaned["v4_prompt"]["caption"]["base_caption"]
        self.assertNotIn("priestess_(arknights)", base)
        self.assertNotIn("dark_grey_hair", base)
        self.assertNotIn("lab_coat", base)
        self.assertIn("artist:redshark_(t373412)", base)
        self.assertIn("standing", base)
        self.assertEqual(
            cleaned["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            "1girl, female_focus, cat girl, cat ears",
        )

    def test_oc_replacement_keeps_identity_and_cleans_v4_base(self) -> None:
        result = transform(
            {
                "target_work_id": 131008442,
                "target_page_index": 8,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "gender_slot_index": 0,
                "replace_creature": False,
            }
        )
        first = result["chars"][0]
        base = result["patched_comment"]["v4_prompt"]["caption"]["base_caption"]
        self.assertIn("12gg_(oc)", first["char_caption"])
        self.assertIn("original_character", first["char_caption"])
        self.assertEqual(first["summary"], "12gg")
        self.assertNotIn("vendela", base.lower())

    def test_char_marker_replacement_has_no_stale_negative_slots(self) -> None:
        result = transform(
            {
                "target_work_id": 145473354,
                "target_page_index": 5,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "gender_slot_index": 0,
                "replace_creature": False,
            }
        )
        comment = result["patched_comment"]
        self.assertIn("char1", str(comment.get("prompt") or "").lower())
        cap = comment["v4_prompt"]["caption"]
        capn = comment["v4_negative_prompt"]["caption"]
        self.assertEqual(cap["char_captions"], [])
        self.assertEqual(capn["char_captions"], [])
        self.assertIn("12gg_(oc)", cap["base_caption"])

    def test_all_page_identity_guard_skips_different_female_character(self) -> None:
        kaltsit_page = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "target_char_index": "all_female",
                "match_identity_keys": ["amiya_(arknights)"],
                "replace_creature": False,
            }
        )
        self.assertTrue(kaltsit_page.get("skipped"))
        self.assertEqual(kaltsit_page["chars"][0].get("ark_library_tag"), "kal'tsit_(arknights)")
        self.assertNotIn("12gg_(oc)", kaltsit_page["chars"][0].get("char_caption") or "")

    def test_all_page_all_gender_guard_without_identity_is_skipped(self) -> None:
        result = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "target_char_index": "all_female",
                "require_match_identity": True,
                "skip_missing_slots": True,
                "replace_creature": False,
            }
        )
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["chars"][0].get("ark_library_tag"), "kal'tsit_(arknights)")
        self.assertNotIn("12gg_(oc)", result["chars"][0].get("char_caption") or "")

    def test_all_page_generic_gender_identity_is_not_a_match(self) -> None:
        result = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "mode": "replace_female",
                "preset_id": "custom_female_1781597897",
                "gender": "female",
                "target_char_index": "all_female",
                "match_identity_keys": ["1girl", "female_focus"],
                "replace_creature": False,
            }
        )
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["chars"][0].get("ark_library_tag"), "kal'tsit_(arknights)")
        self.assertNotIn("astgenne_(arknights)", result["chars"][0].get("char_caption") or "")

    def test_all_page_identity_guard_replaces_matching_female_character(self) -> None:
        amiya_page = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 95,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "target_char_index": "all_female",
                "match_identity_keys": ["amiya_(arknights)"],
                "replace_creature": False,
            }
        )
        self.assertFalse(amiya_page.get("skipped"))
        self.assertIn("12gg_(oc)", amiya_page["chars"][0].get("char_caption") or "")

    def test_current_page_all_female_slots_replaces_without_identity_guard(self) -> None:
        draft = {
            "prompt": "stage, two girls",
            "v4_prompt": {
                "caption": {
                    "base_caption": "stage, two girls",
                    "char_captions": [
                        {
                            "char_caption": "amiya_(arknights), 1girl, female_focus, standing",
                            "centers": [{"x": 0.35, "y": 0.5}],
                        },
                        {
                            "char_caption": "kal'tsit_(arknights), 1girl, female_focus, sitting",
                            "centers": [{"x": 0.65, "y": 0.5}],
                        },
                    ],
                }
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": "",
                    "char_captions": [{"char_caption": ""}, {"char_caption": ""}],
                }
            },
        }
        result = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "patched_comment": draft,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "target_char_index": "all_female",
                "replace_creature": False,
            }
        )
        self.assertFalse(result.get("skipped"))
        caps = [
            ch.get("char_caption") or ""
            for ch in result["patched_comment"]["v4_prompt"]["caption"]["char_captions"]
        ]
        self.assertEqual(len(caps), 2)
        self.assertTrue(all("12gg_(oc)" in cap for cap in caps))

    def test_batch_prepare_all_page_generic_identity_is_skipped(self) -> None:
        prep = prepare_work_draft(
            127760436,
            49,
            recipe={
                "transform": {
                    "mode": "replace_female",
                    "preset_id": "custom_female_1781597897",
                    "gender": "female",
                    "target_char_index": "all_female",
                    "match_identity_keys": ["1girl", "female_focus"],
                    "require_match_identity": True,
                    "replace_creature": False,
                },
                "auto_sanitize": False,
            },
        )
        self.assertTrue(prep.get("skipped"))
        self.assertNotIn("astgenne_(arknights)", str(prep.get("patched_comment") or ""))

    def test_replace_creature_flag_does_not_override_all_slot_mode(self) -> None:
        draft = {
            "prompt": "stage, two girls",
            "v4_prompt": {
                "caption": {
                    "base_caption": "stage, two girls",
                    "char_captions": [
                        {"char_caption": "amiya_(arknights), 1girl, female_focus"},
                        {"char_caption": "kal'tsit_(arknights), 1girl, female_focus"},
                    ],
                }
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": "",
                    "char_captions": [{"char_caption": ""}, {"char_caption": ""}],
                }
            },
        }
        result = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "patched_comment": draft,
                "mode": "replace_female",
                "preset_id": "oc_12gg_f",
                "gender": "female",
                "target_char_index": "all_female",
                "replace_creature": True,
            },
        )
        self.assertFalse(result.get("skipped"))
        caps = [
            ch.get("char_caption") or ""
            for ch in result["patched_comment"]["v4_prompt"]["caption"]["char_captions"]
        ]
        self.assertEqual(len(caps), 2)
        self.assertTrue(all("12gg_(oc)" in cap for cap in caps))

    def test_multi_replacement_identity_guard_skips_different_character(self) -> None:
        result = transform(
            {
                "target_work_id": 127760436,
                "target_page_index": 49,
                "mode": "replace_multi",
                "gender": "female",
                "skip_missing_slots": True,
                "replacements": [
                    {
                        "target_char_index": 0,
                        "preset_id": "oc_12gg_f",
                        "gender": "female",
                        "mode": "replace_female",
                        "match_identity_keys": ["amiya_(arknights)"],
                    }
                ],
                "replace_creature": False,
            }
        )
        self.assertEqual(result["chars"][0].get("ark_library_tag"), "kal'tsit_(arknights)")
        self.assertNotIn("12gg_(oc)", result["chars"][0].get("char_caption") or "")

    def test_stringified_v4_prompt_metadata_does_not_crash_extraction(self) -> None:
        data = extract_chars(127751944, 7)
        self.assertEqual(data.get("prompt_layout"), "v4_slots")
        self.assertGreaterEqual(len(data.get("chars") or []), 2)

    def test_deepseek_config_repairs_bad_business_model_name(self) -> None:
        cfg = normalize_ai_config(
            {
                "provider": "自定义 OpenAI-compatible",
                "api_base": "https://api.deepseek.com/v1",
                "model": "明日方舟",
            }
        )
        self.assertEqual(cfg["model"], "deepseek-v4-flash")
        self.assertEqual(cfg["api_base"], "https://api.deepseek.com/v1")

    def test_stale_deepseek_warning_is_not_kept_in_persona(self) -> None:
        persona = {
            "source": "local_fallback",
            "warning": (
                "AI 人设生成失败，已用本地模板：AI 接口 400: "
                "The supported API model names are deepseek-v4-pro or "
                "deepseek-v4-flash, but you passed 明日方舟."
            ),
        }
        cleaned = _clean_stale_ai_warning(persona)
        self.assertNotIn("warning", cleaned)
        self.assertEqual(persona["warning"], persona["warning"])

    def test_upload_pipeline_forces_mosaic_and_clean_metadata(self) -> None:
        overrides = _upload_pipeline_overrides(
            {
                "pipeline": {
                    "mosaic": {"enabled": False, "method": "pixel"},
                    "metadata": {
                        "enabled": True,
                        "custom_note": "should not upload",
                        "png_text": {"Comment": "secret"},
                    },
                }
            }
        )
        self.assertTrue(overrides["mosaic"]["enabled"])
        self.assertEqual(overrides["metadata"]["png_text"], {})
        self.assertEqual(overrides["metadata"]["custom_note"], "")
        self.assertFalse(overrides["metadata"]["pipeline_marker"])

    def test_upload_never_allows_raw_image_fallback(self) -> None:
        self.assertTrue(_upload_require_processed({"upload": {"use_processed": False}}))
        self.assertTrue(_upload_require_processed({}))

    def test_job_progress_reports_percent(self) -> None:
        _job_progress(current=2, total=4, label="上传前处理", step="pipeline", message="第 2/4 张")
        job = launch_status()
        self.assertEqual(job["step"], "pipeline")
        self.assertEqual(job["message"], "第 2/4 张")
        self.assertEqual(job["progress"]["percent"], 50)
        self.assertEqual(job["progress"]["label"], "上传前处理")

    def test_upload_metadata_cleaner_writes_no_png_text_chunks(self) -> None:
        from PIL import Image, PngImagePlugin

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.png"
            meta = PngImagePlugin.PngInfo()
            meta.add_text("Comment", "NovelAI prompt secret")
            meta.add_text("Software", "NovelAI")
            Image.new("RGB", (2, 2), (255, 0, 0)).save(source, pnginfo=meta)

            clean = _strip_metadata(
                source,
                {
                    "enabled": True,
                    "custom_note": "",
                    "png_text": {},
                    "pipeline_marker": False,
                },
            )
            with Image.open(clean) as img:
                self.assertEqual(dict(img.text), {})

    def test_metadata_cleaner_accepts_unicode_note(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.png"
            Image.new("RGB", (2, 2), (255, 255, 255)).save(source)

            clean = _strip_metadata(
                source,
                {
                    "enabled": True,
                    "custom_note_key": "处理说明",
                    "custom_note": "已人工通过，清除原始元数据",
                    "png_text": {"中文键": "中文值"},
                    "pipeline_marker": True,
                },
            )
            with Image.open(clean) as img:
                text = dict(img.text)
            self.assertIn("aitag-pipeline", text)
            self.assertIn("已人工通过", "".join(text.values()))
            self.assertIn("中文值", "".join(text.values()))

    def test_pixiv_selection_accepts_plus_joined_group_id(self) -> None:
        def fake_group(gid: str) -> list[str]:
            return {
                "145754820": ["a1", "a2"],
                "140404580": ["b1"],
            }[gid]

        with patch("pixiv_launch._image_ids_for_group", side_effect=fake_group):
            batches = _resolve_selection_batches(
                {
                    "group_id": "145754820+140404580",
                    "merge_groups": True,
                }
            )
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["group_ids"], ["145754820", "140404580"])
        self.assertEqual(batches[0]["image_ids"], ["a1", "a2", "b1"])
        self.assertTrue(batches[0]["merged"])

    def test_mosaic_none_counts_as_checked_for_normal_images(self) -> None:
        from PIL import Image

        stem = "unit_normal_no_mosaic_target"
        source = GENERATED_DIR / f"{stem}.png"
        final = GENERATED_DIR / f"{stem}_final.png"
        clean = GENERATED_DIR / f"{stem}_clean.png"
        try:
            Image.new("RGB", (2, 2), (255, 255, 255)).save(source)
            clean.write_bytes(source.read_bytes())
            final.write_bytes(source.read_bytes())
            _write_meta(
                source,
                {
                    "pipeline_steps": ["mosaic:none", "metadata:clean"],
                    "mosaic_no_target": "ANR 未检测到可打码目标",
                    "processed_filename": final.name,
                },
            )
            state = pipeline_item_state(
                stem,
                overrides={
                    "upscale": {"enabled": False},
                    "mosaic": {"enabled": True},
                    "metadata": {"enabled": True},
                },
            )
            self.assertTrue(state["mosaic"])
            self.assertEqual(state["mosaic_no_target"], "ANR 未检测到可打码目标")
            self.assertNotIn("mosaic", state["missing"])
        finally:
            for path in (source, final, clean, source.with_suffix(".json"), final.with_suffix(".json"), clean.with_suffix(".json")):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def test_pipeline_overrides_keep_anr_root(self) -> None:
        cfg = merge_pipeline_config(
            {
                "anr_root": "E:/ai批量生图/Auto-NovelAI-Refactor",
                "mosaic": {"enabled": True, "method": "像素"},
            }
        )
        self.assertEqual(cfg["anr_root"], "E:/ai批量生图/Auto-NovelAI-Refactor")
        self.assertTrue((cfg.get("mosaic") or {}).get("enabled"))

    def test_pipeline_default_does_not_embed_local_anr_path(self) -> None:
        self.assertEqual(PIPELINE_DEFAULTS["anr_root"], "")

    def test_mosaic_runtime_status_does_not_import_detector(self) -> None:
        detector_mod = "plugins.anr_plugin_auto_mosaics.detector"
        sys.modules.pop(detector_mod, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugins" / "anr_plugin_auto_mosaics"
            plugin.mkdir(parents=True)
            (plugin / "__init__.py").write_text("", encoding="utf-8")
            (plugin / "mosaics.py").write_text("", encoding="utf-8")
            (plugin / "detector.py").write_text(
                "raise RuntimeError('detector should not be imported by status')\n",
                encoding="utf-8",
            )
            status = mosaic_runtime_status({"anr_root": str(root)})
        self.assertTrue(status["ok"])
        self.assertNotIn(detector_mod, sys.modules)

    @unittest.skipUnless(os.name == "nt", "token file writes require Windows DPAPI")
    def test_nai_recaptcha_failure_removes_bad_token_and_falls_back(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                nai = {
                    "id": "nai_test_recaptcha",
                    "label": "NAI test",
                    "provider": PROVIDER_NOVELAI,
                    "token": "pst-test",
                    "enabled": True,
                }
                xy = {
                    "id": "xy_test_fallback",
                    "label": "Xianyun test",
                    "provider": PROVIDER_XIANYUN,
                    "token": "xy-test",
                    "enabled": True,
                }
                nai_api.TOKEN_PATH.write_text(
                    json.dumps({"tokens": [nai, xy], "updated_at": "2026-06-16T00:00:00"}),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                _TOKEN_FAILURES.clear()
                self.assertTrue(
                    _record_token_failure(
                        nai,
                        'NAI API error 400: {"message":"Recaptcha token is required for trial generation"}',
                    )
                )
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                self.assertEqual([t["id"] for t in saved["tokens"]], ["xy_test_fallback"])
                candidates = _candidate_token_entries(nai)
                self.assertEqual(candidates[0]["id"], "xy_test_fallback")
            finally:
                _TOKEN_FAILURES.clear()
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_xianyun_banned_token_is_removed_from_pool(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                token_entry = {
                    "id": "xy_disabled_test",
                    "label": "Xianyun bad",
                    "provider": PROVIDER_XIANYUN,
                    "token": "xy-bad-token",
                    "enabled": True,
                }
                nai_api.TOKEN_PATH.write_text(
                    json.dumps(
                        {
                            "token": "xy-bad-token",
                            "tokens": [token_entry],
                            "updated_at": "2026-06-16T00:00:00",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                self.assertTrue(
                    _record_token_failure(
                        token_entry,
                        "Xianyun account forbidden or banned: 403 account banned",
                    )
                )
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["tokens"], [])
                self.assertIn("banned", saved["last_removed_token"]["reason"])
                self.assertEqual(_enabled_token_entries(), [])
            finally:
                _TOKEN_FAILURES.clear()
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_token_provider_autodetects_nai_and_bare_xianyun_keys(self) -> None:
        import nai_api

        nai = nai_api._parse_token_line("pst-good-token", 0)
        xy = nai_api._parse_token_line("jDurqKZQ3j_DGo_zvdNb5iL-QlUW2tdi6iawZ4-PkrI", 1)

        self.assertEqual(nai["provider"], PROVIDER_NOVELAI)
        self.assertEqual(xy["provider"], PROVIDER_XIANYUN)
        self.assertTrue(nai["id"].startswith("nai_"))
        self.assertTrue(xy["id"].startswith("xianyun_"))

    @unittest.skipUnless(os.name == "nt", "token file writes require Windows DPAPI")
    def test_save_token_keeps_mixed_nai_and_xianyun_slots(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                result = nai_api.save_token(
                    "\n".join(
                        [
                            "pst-good-token",
                            "jDurqKZQ3j_DGo_zvdNb5iL-QlUW2tdi6iawZ4-PkrI",
                        ]
                    )
                )
                self.assertEqual(result["token_count"], 2)
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                providers = [entry["provider"] for entry in saved["tokens"]]
                self.assertEqual(providers, [PROVIDER_NOVELAI, PROVIDER_XIANYUN])
                self.assertEqual(nai_api.token_status()["providers"], {PROVIDER_NOVELAI: 1, PROVIDER_XIANYUN: 1})
            finally:
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    @unittest.skipUnless(os.name == "nt", "token file writes require Windows DPAPI")
    def test_add_token_entry_probes_unknown_provider_before_rejecting(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                nai_api.TOKEN_PATH.write_text(
                    json.dumps({"token": "", "tokens": [], "updated_at": "2026-06-16T00:00:00"}),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                with patch("nai_api._probe_provider", return_value=PROVIDER_NOVELAI) as probe:
                    result = nai_api.add_token_entry({"token": "opaque-provider-token"})

                self.assertTrue(result["ok"])
                probe.assert_called_once()
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["tokens"][0]["provider"], PROVIDER_NOVELAI)
                self.assertTrue(saved["tokens"][0]["id"].startswith("nai_"))
            finally:
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_generated_group_includes_source_prompt_by_default(self) -> None:
        import routes.nai as nai_routes

        fake_prompt = {
            "base_caption": "artist:sample, cinematic lighting",
            "chars": [{"index": 0, "caption": "amiya_(arknights), 1girl"}],
            "uc": "bad anatomy",
        }
        with patch("routes.nai.migrate_legacy_meta"), patch(
            "routes.nai.batch_status", return_value={"status": "idle", "items": []}
        ), patch("routes.nai.queue_status", return_value={"status": "idle"}), patch(
            "routes.nai.get_group",
            return_value={
                "id": "140404580",
                "work_id": 140404580,
                "items": [{"id": "generated-1", "prompt_snapshot": None}],
                "count": 1,
            },
        ), patch(
            "routes.nai.DB.get_work_detail",
            return_value={"work": {"title": "sample title"}, "images": []},
        ), patch("routes.nai._generated_source_prompt", return_value=fake_prompt) as source_prompt:
            result = nai_routes.api_generated_group("140404580", include_source_prompt=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source_prompt"], fake_prompt)
        self.assertEqual(result["group"]["items"][0]["id"], "generated-1")
        source_prompt.assert_called_once_with(140404580, gallery_id="site")

    def test_xianyun_check_accepts_parameter_validation_response(self) -> None:
        import nai_api

        entry = {
            "id": "xy_check_ok",
            "label": "Xianyun check",
            "provider": PROVIDER_XIANYUN,
            "token": "xy-good-token",
            "enabled": True,
        }
        with patch(
            "nai_api._token_check_request",
            return_value=(400, '{"error":"API请求数据不能为空"}'),
        ) as request, patch("nai_api._remove_token_entry") as remove_token:
            result = nai_api._check_one_token_entry(entry, remove_bad=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["removed"])
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertEqual(request.call_args.args[1], f"{nai_api.XIANYUN_API_BASE}/generate_image")
        self.assertEqual(request.call_args.kwargs["json_body"], {})
        remove_token.assert_not_called()

    def test_xianyun_check_removes_forbidden_token(self) -> None:
        import nai_api

        entry = {
            "id": "xy_check_forbidden",
            "label": "Xianyun forbidden",
            "provider": PROVIDER_XIANYUN,
            "token": "xy-bad-token",
            "enabled": True,
        }
        with patch("nai_api._token_check_request", return_value=(403, "account forbidden")), patch(
            "nai_api._remove_token_entry", return_value=True
        ) as remove_token:
            result = nai_api._check_one_token_entry(entry, remove_bad=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["removed"])
        self.assertIn("403", result["message"])
        remove_token.assert_called_once()

    def test_curl_token_check_keeps_secret_out_of_command_args(self) -> None:
        import nai_api

        calls: list[dict[str, object]] = []

        class FakeCompleted:
            returncode = 0
            stdout = '{"ok":true}\n__AITAG_HTTP_STATUS__:200'
            stderr = ""

        def fake_run(cmd, **kwargs):
            calls.append({"cmd": cmd, **kwargs})
            return FakeCompleted()

        with patch("nai_api.shutil.which", return_value="curl.exe"), patch(
            "nai_api.subprocess.run", side_effect=fake_run
        ):
            status, body = nai_api._curl_request_for_token_check(
                "GET",
                "https://example.test/check",
                {"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, '{"ok":true}')
        cmd_text = " ".join(str(part) for part in calls[0]["cmd"])
        self.assertNotIn("secret-token", cmd_text)
        self.assertIn("secret-token", str(calls[0]["input"]))

    def test_nai_400_token_is_removed_from_pool(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                token_entry = {
                    "id": "nai_bad_400",
                    "label": "NAI bad",
                    "provider": PROVIDER_NOVELAI,
                    "token": "pst-bad-token",
                    "enabled": True,
                }
                nai_api.TOKEN_PATH.write_text(
                    json.dumps(
                        {
                            "token": "pst-bad-token",
                            "tokens": [token_entry],
                            "updated_at": "2026-06-16T00:00:00",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                self.assertTrue(
                    _record_token_failure(
                        token_entry,
                        'NAI API error 400: {"message":"Recaptcha token is required for trial generation"}',
                    )
                )
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                self.assertEqual(saved["tokens"], [])
                self.assertEqual(_enabled_token_entries(), [])
                self.assertEqual(saved["last_removed_token"]["id"], "nai_bad_400")
            finally:
                _TOKEN_FAILURES.clear()
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_nai_500_temporarily_disables_token_without_removing_it(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                nai = {
                    "id": "nai_temp_500",
                    "label": "NAI temp",
                    "provider": PROVIDER_NOVELAI,
                    "token": "pst-good-token",
                    "enabled": True,
                }
                xy = {
                    "id": "xy_after_500",
                    "label": "Xianyun fallback",
                    "provider": PROVIDER_XIANYUN,
                    "token": "xy-good-token",
                    "enabled": True,
                }
                nai_api.TOKEN_PATH.write_text(
                    json.dumps({"tokens": [nai, xy], "updated_at": "2026-06-16T00:00:00"}),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                _TOKEN_FAILURES.clear()
                self.assertTrue(
                    _record_token_failure(
                        nai,
                        'NAI API error 500: {"statusCode":500,"message":"Internal Server Error"}',
                    )
                )
                saved = json.loads(nai_api.TOKEN_PATH.read_text(encoding="utf-8"))
                self.assertEqual([t["id"] for t in saved["tokens"]], ["nai_temp_500", "xy_after_500"])
                candidates = _candidate_token_entries(nai)
                self.assertEqual(candidates[0]["id"], "xy_after_500")
                self.assertNotIn("nai_temp_500", [entry["id"] for entry in candidates])
            finally:
                _TOKEN_FAILURES.clear()
                nai_api._LAST_GEN_AT_BY_TOKEN.clear()
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_all_temporarily_disabled_tokens_report_cooldown_not_busy(self) -> None:
        import nai_api

        with tempfile.TemporaryDirectory() as tmp:
            old_path = nai_api.TOKEN_PATH
            old_data_dir = nai_api.DATA_DIR
            old_cache = nai_api._TOKEN_ENTRIES_CACHE
            old_cache_at = nai_api._TOKEN_ENTRIES_CACHE_AT
            try:
                nai_api.DATA_DIR = Path(tmp)
                nai_api.TOKEN_PATH = Path(tmp) / "nai_token.local.json"
                token_entry = {
                    "id": "nai_temp_disabled",
                    "label": "NAI temp disabled",
                    "provider": PROVIDER_NOVELAI,
                    "token": "pst-good-token",
                    "enabled": True,
                }
                nai_api.TOKEN_PATH.write_text(
                    json.dumps({"tokens": [token_entry], "updated_at": "2026-06-16T00:00:00"}),
                    encoding="utf-8",
                )
                nai_api._invalidate_token_cache()
                _TOKEN_FAILURES.clear()
                _record_token_failure(
                    token_entry,
                    "Request too frequent; please retry later",
                )
                entry, reason, wait, _provider = nai_api._pick_available_token()
                self.assertIsNone(entry)
                self.assertEqual(reason, "cooldown")
                self.assertGreater(wait, 0)
            finally:
                _TOKEN_FAILURES.clear()
                nai_api._LAST_GEN_AT_BY_TOKEN.clear()
                nai_api.TOKEN_PATH = old_path
                nai_api.DATA_DIR = old_data_dir
                nai_api._TOKEN_ENTRIES_CACHE = old_cache
                nai_api._TOKEN_ENTRIES_CACHE_AT = old_cache_at

    def test_xianyun_payload_includes_vibe_transfer(self) -> None:
        payload = {
            "model": "nai-diffusion-4-full",
            "parameters": {"width": 832, "height": 1216, "steps": 28},
        }
        body = {
            "input": "1girl",
            "model": "nai-diffusion-4-full",
            "parameters": {"scale": 5, "uc": "bad"},
        }
        req = _xianyun_body_from_payload(
            payload,
            body,
            {
                "xianyun_vibe": {
                    "enabled": True,
                    "image_url": "https://example.test/ref.png",
                    "strength": 0.72,
                }
            },
        )
        self.assertEqual(req["reference_images"], ["https://example.test/ref.png"])
        self.assertEqual(req["reference_strength_multiple"], [0.72])
        self.assertTrue(req["characterTransfer"]["enabled"])

    def test_novelai_payload_uses_current_generate_shape(self) -> None:
        payload = build_generate_payload(
            {
                "Source": "NovelAI Diffusion V4.5",
                "prompt": "1girl",
                "uc": "bad anatomy",
                "width": 832,
                "height": 1216,
                "steps": 28,
            },
            force_free=True,
        )
        params = payload["parameters"]
        self.assertEqual(payload["request_type"], "PromptGenerateRequest")
        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        self.assertEqual(params["params_version"], 3)
        self.assertEqual(params["v4_prompt"]["caption"]["base_caption"], "1girl")
        self.assertEqual(params["v4_prompt"]["caption"]["char_captions"], [])
        self.assertEqual(params["v4_negative_prompt"]["caption"]["base_caption"], "bad anatomy")
        self.assertEqual(params["negative_prompt"], "bad anatomy")
        self.assertEqual(params["uc"], "bad anatomy")
        self.assertFalse(params["legacy"])
        self.assertFalse(params["legacy_uc"])
        self.assertFalse(params["legacy_v3_extend"])
        self.assertTrue(params["qualityToggle"])
        self.assertTrue(params["prefer_brownian"])
        self.assertFalse(params["deliberate_euler_ancestral_bug"])
        self.assertEqual(params["reference_image_multiple"], [])

    def test_char_swap_large_modules_no_longer_import_panel_module(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("batch.js", "presets.js"):
            with self.subTest(name=name):
                text = (root / "web" / "plugins" / "char-swap" / name).read_text(encoding="utf-8")
                self.assertNotIn('from "./panel.js"', text)

    def test_batch_recipe_is_single_build_recipe_owner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files = list((root / "web" / "plugins" / "char-swap").glob("*.js"))
        owners = [
            path.name
            for path in files
            if "function buildRecipeFromForm" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(owners, ["batch_recipe.js"])


if __name__ == "__main__":
    unittest.main()
