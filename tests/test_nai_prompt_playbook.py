from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from butler.cards import _prepare_studio
from nai_prompt_optimizer import optimize_nai_prompt
from nai_prompt_playbook import (
    DEMAND_FORMED,
    DEMAND_SUBJECT,
    apply_v5_playbook,
    classify_demand,
    playbook_optimizer_rules,
)
from studio_service import studio_config


class PromptPlaybookTests(unittest.TestCase):
    def test_copyright_character_is_identity_minimal(self) -> None:
        report = apply_v5_playbook(
            {
                "prompt": (
                    "1girl, stelle (honkai: star rail), grey hair, long hair, "
                    "yellow eyes, medium breasts, black jacket, white shirt, standing, rooftop, rain"
                ),
                "uc": "lowres",
                "char_captions": [],
            }
        )
        texts = report["texts"]
        self.assertTrue(report["copyright_minimal"])
        self.assertIn("1girl", texts["base_caption"])
        self.assertIn("standing", texts["base_caption"])
        self.assertIn("rooftop", texts["base_caption"])
        self.assertNotIn("grey hair", texts["base_caption"])
        slot = texts["char_captions"][0].lower()
        self.assertIn("stelle (honkai: star rail)", slot)
        self.assertIn("girl", slot)
        self.assertNotIn("grey hair", slot)
        self.assertNotIn("yellow eyes", slot)
        self.assertNotIn("black jacket", slot)
        self.assertNotIn("medium breasts", slot)

    def test_outfit_override_keeps_requested_clothes(self) -> None:
        report = apply_v5_playbook(
            {
                "prompt": "1girl, stelle (honkai: star rail), grey hair, pajamas, sitting",
                "char_captions": [],
            },
            intent="把她换装成睡衣",
        )
        slot = report["texts"]["char_captions"][0].lower()
        self.assertTrue(report["outfit_override"])
        self.assertIn("pajamas", slot)
        self.assertNotIn("grey hair", slot)

    def test_prompt_text_can_request_outfit_without_separate_intent(self) -> None:
        report = apply_v5_playbook(
            {
                "prompt": "1girl, stelle (honkai: star rail), grey hair, pajamas, sitting",
                "char_captions": [],
            }
        )
        slot = report["texts"]["char_captions"][0].lower()
        self.assertTrue(report["outfit_override"])
        self.assertIn("pajamas", slot)
        self.assertNotIn("grey hair", slot)

    def test_slot_isolation_moves_action_and_appearance(self) -> None:
        report = apply_v5_playbook(
            {
                "prompt": "2girls, rooftop, grey hair",
                "char_captions": [
                    "lumine (genshin impact), girl, from side, standing",
                    "hu tao (genshin impact), girl, red eyes",
                ],
            }
        )
        base = report["texts"]["base_caption"].lower()
        self.assertIn("2girls", base)
        self.assertIn("from side", base)
        self.assertIn("standing", base)
        self.assertNotIn("grey hair", base)
        first = report["texts"]["char_captions"][0].lower()
        second = report["texts"]["char_captions"][1].lower()
        self.assertNotIn("from side", first)
        self.assertNotIn("red eyes", second)
        self.assertEqual(base.count("2girls"), 1)
        self.assertNotIn("2girls", first)

    def test_demand_tiers(self) -> None:
        self.assertEqual(classify_demand(""), "D")
        self.assertEqual(
            classify_demand("夏天"),
            "C",
        )
        self.assertEqual(
            classify_demand(
                "",
                {"prompt": "stelle (honkai: star rail)"},
            ),
            DEMAND_SUBJECT,
        )
        self.assertEqual(
            classify_demand(
                "芙宁娜在雨夜屋顶站着看远处",
                {"prompt": "furina (genshin impact), standing, rooftop, rain"},
            ),
            DEMAND_FORMED,
        )

    def test_playbook_rules_are_first_party(self) -> None:
        rules = playbook_optimizer_rules()
        self.assertIn("版权角色", rules)
        self.assertNotIn("某单机游戏爱好者", rules)
        self.assertNotIn("1067312194", rules)
        self.assertIn("不要输出漫画分镜", rules)

    def test_optimize_playbook_mode_is_local(self) -> None:
        comment = {
            "prompt": "1girl, surtr (arknights), red hair, standing, volcano",
        }
        result = optimize_nai_prompt(comment, mode="playbook")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["profile"], "v5_playbook")
        slot = result["texts"]["char_captions"][0].lower()
        self.assertIn("surtr (arknights)", slot)
        self.assertNotIn("red hair", slot)
        self.assertIn("volcano", result["texts"]["base_caption"].lower())

    def test_smart_optimize_applies_playbook_after_llm(self) -> None:
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
                "prompt": "masterpiece, best quality, 1girl, outdoors",
                "uc": "lowres, bad anatomy",
                "base_caption": "1girl, outdoors, masterpiece, best quality",
                "char_captions": ["1girl, surtr (arknights), red hair"],
                "notes": "强化质量与背景",
            },
            ensure_ascii=False,
        )
        with patch(
            "nai_prompt_optimizer._ai_env",
            return_value={
                "api_key": "k",
                "model": "deepseek-v4-flash",
                "api_base": "https://api.deepseek.com/v1",
                "timeout": 30,
                "max_tokens": 1024,
            },
        ), patch("nai_prompt_optimizer._chat_completion", return_value=llm_json):
            result = optimize_nai_prompt(comment, mode="smart")
        self.assertEqual(result.get("provider"), "llm")
        self.assertIn("surtr", result["texts"]["char_captions"][0].lower())
        self.assertNotIn("red hair", result["texts"]["char_captions"][0].lower())
        self.assertEqual(result.get("notes"), "强化质量与背景")
        self.assertTrue(result["playbook"]["copyright_minimal"])

    def test_prepare_studio_prompt_runs_playbook(self) -> None:
        result = _prepare_studio(
            {
                "prompt": (
                    "1girl, stelle (honkai: star rail), grey hair, yellow eyes, "
                    "black jacket, standing, rooftop"
                )
            }
        )
        texts = result["draft"]["texts"]
        self.assertIn("playbook", result)
        self.assertTrue(result["playbook"]["copyright_minimal"])
        self.assertIn("standing", texts["base_caption"])
        self.assertNotIn("grey hair", texts["base_caption"])
        self.assertIn("stelle (honkai: star rail)", texts["char_captions"][0])

    def test_studio_config_lists_playbook_mode(self) -> None:
        ids = [item["id"] for item in studio_config().get("optimize_modes") or []]
        self.assertIn("playbook", ids)
        self.assertIn("smart", ids)


if __name__ == "__main__":
    unittest.main()
