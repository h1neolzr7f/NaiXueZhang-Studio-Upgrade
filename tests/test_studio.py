from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nai_prompt_optimizer import (
    _apply_texts_to_comment,
    _prompt_snapshot,
    optimize_nai_prompt,
)
from studio_service import import_from_work, preview_work_prompt, sanitize_comment, studio_config


class StudioServiceTests(unittest.TestCase):
    def test_prompt_snapshot_reads_v4_slots(self) -> None:
        comment = {
            "prompt": "scene",
            "uc": "bad",
            "v4_prompt": {
                "caption": {
                    "base_caption": "outdoors",
                    "char_captions": [{"char_caption": "1girl, surtr"}],
                }
            },
        }
        snap = _prompt_snapshot(comment)
        self.assertEqual(snap["base_caption"], "outdoors")
        self.assertEqual(snap["char_captions"], ["1girl, surtr"])
        self.assertEqual(snap["uc"], "bad")

    def test_apply_texts_to_comment_roundtrip(self) -> None:
        comment = {
            "prompt": "old",
            "uc": "old_uc",
            "v4_prompt": {"caption": {"base_caption": "old", "char_captions": [{"char_caption": "a"}]}},
        }
        patched = _apply_texts_to_comment(
            comment,
            {
                "prompt": "new prompt",
                "base_caption": "new base",
                "uc": "new uc",
                "char_captions": ["char one", "char two"],
            },
        )
        snap = _prompt_snapshot(patched)
        self.assertEqual(snap["prompt"], "new base")
        self.assertEqual(snap["char_captions"], ["char one", "char two"])
        self.assertEqual(snap["uc"], "new uc")

    def test_local_anima_optimize(self) -> None:
        comment = {
            "prompt": "artist:test, 1girl, surtr (arknights), standing",
            "uc": "lowres",
        }
        result = optimize_nai_prompt(comment, mode="anima_epic")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("provider"), "local")
        self.assertIn("masterpiece", result["texts"]["prompt"].lower())

    def test_smart_optimize_requires_api_key(self) -> None:
        comment = {"prompt": "1girl", "uc": "bad"}
        with patch("nai_prompt_optimizer._ai_env", return_value={"api_key": ""}):
            with self.assertRaises(ValueError):
                optimize_nai_prompt(comment, mode="smart")

    def test_smart_optimize_with_mock_llm(self) -> None:
        comment = {
            "prompt": "1girl, surtr",
            "uc": "lowres",
            "v4_prompt": {
                "caption": {
                    "base_caption": "outdoors",
                    "char_captions": [{"char_caption": "1girl, surtr (arknights)"}],
                }
            },
        }
        llm_json = json.dumps(
            {
                "prompt": "masterpiece, best quality, 1girl, surtr (arknights), volcano background",
                "uc": "lowres, bad anatomy",
                "base_caption": "volcano background",
                "char_captions": ["1girl, surtr (arknights), red hair"],
                "notes": "强化质量与背景",
            },
            ensure_ascii=False,
        )
        with patch("nai_prompt_optimizer._ai_env", return_value={"api_key": "k", "model": "deepseek-v4-flash", "api_base": "https://api.deepseek.com/v1", "timeout": 30, "max_tokens": 1024}):
            with patch("nai_prompt_optimizer._chat_completion", return_value=llm_json):
                result = optimize_nai_prompt(comment, mode="smart")
        self.assertEqual(result.get("provider"), "llm")
        self.assertIn("surtr", result["texts"]["char_captions"][0].lower())
        self.assertNotIn("red hair", result["texts"]["char_captions"][0].lower())
        self.assertEqual(result.get("notes"), "强化质量与背景")
        self.assertIn("playbook", result)

    def test_studio_config_lists_modes(self) -> None:
        cfg = studio_config()
        ids = [m["id"] for m in cfg.get("optimize_modes") or []]
        self.assertIn("smart", ids)
        self.assertIn("playbook", ids)
        self.assertIn("sanitize", ids)

    def test_sanitize_comment(self) -> None:
        comment = {"prompt": "1girl, gore, standing", "uc": ""}
        result = sanitize_comment(comment)
        self.assertTrue(result.get("ok"))
        self.assertNotIn("gore", result["texts"]["prompt"].lower())

    def test_attach_image_reference_from_work_id(self) -> None:
        from studio_service import attach_image_reference

        with patch("studio_service.import_from_work", return_value={"thumb": "/data/images/sample.webp"}):
            result = attach_image_reference({"prompt": "1girl"}, work_id=12345, kind="vibe", strength=0.5)
        self.assertTrue(result.get("ok"))
        self.assertIn("xianyun_vibe", result["comment"])
        self.assertEqual(result["image_url"], "/data/images/sample.webp")

    def test_preview_work_prompt_lightweight(self) -> None:
        with patch("studio_service.DB.get_work_prompt_snippet", return_value={"snippet": "1girl, surtr", "page_index": 0, "source": "work_images"}):
            result = preview_work_prompt(12345, 0)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("has_prompt"))
        self.assertIn("surtr", result.get("snippet", ""))
        self.assertEqual(result.get("gallery_id"), "site")

    def test_preview_work_prompt_uses_requested_gallery(self) -> None:
        other = type("DB", (), {
            "get_work_prompt_snippet": staticmethod(
                lambda work_id, page: {"snippet": "codex prompt", "page_index": page, "source": "codex"}
            )
        })()
        with patch("studio_service._gallery_db", return_value=other):
            result = preview_work_prompt(99, 1, "codex")
        self.assertEqual(result.get("gallery_id"), "codex")
        self.assertEqual(result.get("snippet"), "codex prompt")

    def test_import_from_work_returns_all_local_pages(self) -> None:
        from gallery_cache import clear_all
        from studio_service import import_from_work

        clear_all()
        details = {
            "work": {"title": "series"},
            "images": [
                {"page_index": 0, "local_path": "NAI/1/a_p0.webp"},
                {"page_index": 1, "local_path": "NAI/1/a_p1.webp"},
                {"page_index": 2, "local_path": "NAI/1/a_p2.webp"},
            ],
        }

        def extract(work_id, page_index, gallery_id="site"):
            return {
                "comment": {"prompt": f"page {page_index}"},
                "params": {"width": 832},
                "chars": [],
                "base_caption": f"base {page_index}",
            }

        db = type("DB", (), {"get_work_detail": staticmethod(lambda _id: details)})()
        with patch("studio_service.extract_chars", side_effect=extract), patch(
            "studio_service._gallery_db", return_value=db
        ):
            result = import_from_work(99, 1, "site")

        self.assertEqual(result["page_index"], 1)
        self.assertEqual(result["page_count"], 3)
        self.assertEqual([page["image_index"] for page in result["pages"]], [0, 1, 2])
        self.assertEqual(result["texts"]["prompt"], "page 1")
        self.assertEqual(result["pages"][2]["draft"]["texts"]["prompt"], "page 2")
        self.assertEqual(result["gallery_id"], "site")

    def test_vibe_image_path_must_stay_inside_data_dir(self) -> None:
        from studio_service import apply_vibe_to_comment

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            (data / "images").mkdir(parents=True)
            inside = data / "images" / "ref.png"
            inside.write_bytes(b"\x89PNG\r\n\x1a\n")
            outside = root / "secret.png"
            outside.write_bytes(b"secret")
            with patch("studio_service.DATA_DIR", data):
                ok = apply_vibe_to_comment({"prompt": "1girl"}, image_path=str(inside))
                self.assertTrue(ok.get("ok"))
                self.assertTrue(ok["comment"]["xianyun_vibe"]["reference_images"][0].startswith("data:image/"))
                with self.assertRaises(ValueError):
                    apply_vibe_to_comment({"prompt": "1girl"}, image_path=str(outside))

    def test_attach_char_reference(self) -> None:
        from studio_service import attach_image_reference

        result = attach_image_reference(
            {"prompt": "1girl"},
            image_url="https://example.test/ref.png",
            kind="char",
            strength=0.7,
        )
        self.assertEqual(result.get("kind"), "char")
        self.assertEqual(result["comment"]["reference_image_multiple"], ["https://example.test/ref.png"])


if __name__ == "__main__":
    unittest.main()