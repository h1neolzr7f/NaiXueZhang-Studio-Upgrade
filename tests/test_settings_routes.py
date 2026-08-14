from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests.asgi_client import TestClient

import server


ROOT = Path(__file__).resolve().parents[1]


class SettingsRouteTests(unittest.TestCase):
    def test_invalid_numeric_config_is_rejected_before_any_file_is_changed(self) -> None:
        with patch("routes.settings.save_prefs") as prefs, patch(
            "routes.settings.save_pixiv_config"
        ) as config, patch("routes.settings.save_ai_key") as key:
            response = self.client.post(
                "/api/settings/config",
                json={"prefs": {"assistant_name": "小镜"}, "ai": {"timeout": {"bad": 1}}},
            )

        self.assertEqual(response.status_code, 400)
        prefs.assert_not_called()
        config.assert_not_called()
        key.assert_not_called()

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(server.app)

    def test_global_config_saves_assistant_and_complete_ai_settings_without_echoing_key(self) -> None:
        saved_prefs = {
            "assistant_name": "小镜",
            "assistant_live2d_enabled": True,
            "assistant_live2d_model": "/assets/vendor/live2d-models/hiyori/Hiyori.model3.json",
            "assistant_poll_mode": "eco",
        }
        saved_config = {
            "ai": {
                "provider": "DeepSeek",
                "api_base": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-flash",
            }
        }
        with patch("routes.settings.save_prefs", return_value={"ok": True, "prefs": saved_prefs}) as prefs, patch(
            "routes.settings.save_pixiv_config", return_value=saved_config
        ) as config, patch(
            "routes.settings.save_ai_key", return_value={"ok": True, "has_key": True}
        ) as key, patch(
            "routes.settings.api_settings_config", return_value={
                "ok": True,
                "prefs": saved_prefs,
                "config": saved_config,
                "ai": {"has_api_key": True, "model": "deepseek-v4-flash"},
            },
        ):
            response = self.client.post(
                "/api/settings/config",
                json={
                    "prefs": saved_prefs,
                    "ai": {**saved_config["ai"], "api_key": "sk-secret-value"},
                },
            )

        self.assertEqual(response.status_code, 200)
        prefs.assert_called_once_with(saved_prefs)
        config.assert_called_once_with({"ai": saved_config["ai"]})
        key.assert_called_once_with("sk-secret-value")
        self.assertNotIn("sk-secret-value", json.dumps(response.json()))

    def test_config_center_exposes_beginner_friendly_global_fields(self) -> None:
        html = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "settings.js").read_text(encoding="utf-8")

        for marker in (
            "配置中心（只需设置一次）",
            "可以聊天",
            "可以生图",
            "可以发布",
            'id="assistantName"',
            'id="assistantLive2d"',
            'id="aiProvider"',
            'id="aiBase"',
            'id="aiModel"',
            'id="settingsAiKey"',
            'id="saveAllBtn"',
            'id="usageTotalTokens"',
            'id="usageAnlas"',
            'id="knowledgeCatalog"',
            'id="knowledgeRebuildBtn"',
            'id="knowledgeDocuments"',
            'id="knowledgeChunks"',
        ):
            self.assertIn(marker, html)
        self.assertIn('"/api/settings/config"', script)
        self.assertIn('"/api/settings/ai-test"', script)
        self.assertIn('id="testVisionBtn"', html)
        self.assertIn('"/api/settings/ai-vision-test"', script)
        self.assertIn('id="loadAiModelsBtn"', html)
        self.assertIn('id="aiModelOptions"', html)
        self.assertIn('"/api/settings/ai-models"', script)
        self.assertIn('"/api/settings/knowledge"', script)
        self.assertIn('"/api/settings/knowledge/rebuild"', script)

    def test_generation_pool_lists_masked_slots_with_check_and_delete(self) -> None:
        html = (ROOT / "web" / "settings.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "settings.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "settings.css").read_text(encoding="utf-8")
        self.assertIn('id="tokenSlotList"', html)
        self.assertIn("全部检测是否可用", html)
        self.assertIn("token.token_count", script)
        self.assertIn('"/api/nai/token/add"', script)
        self.assertIn('"/api/nai/token/check"', script)
        self.assertIn("token_id: slot.id", script)
        self.assertIn("remove_bad: false", script)
        self.assertIn('method: "DELETE"', script)
        self.assertIn(".token-slot-actions", css)
        self.assertNotIn("token.count || 0", script)

    def test_settings_status_exposes_masked_token_slots_without_plaintext(self) -> None:
        tok = {
            "has_token": True,
            "token_count": 1,
            "enabled_count": 1,
            "tokens": [
                {
                    "id": "nai_abc123",
                    "label": "NAI #1",
                    "provider": "novelai",
                    "masked": "pst-********",
                    "enabled": True,
                }
            ],
        }
        with patch("routes.settings.token_status", return_value=tok), patch(
            "routes.settings.ai_status", return_value={"has_api_key": False}
        ), patch("routes.settings.load_prefs", return_value={}):
            response = self.client.get("/api/settings/status")
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["token"]["token_count"], 1)
        self.assertEqual(payload["token"]["tokens"][0]["masked"], "pst-********")
        self.assertNotIn("pst-real-secret", json.dumps(payload))

    def test_model_list_is_proxied_without_exposing_the_saved_key(self) -> None:
        with patch(
            "routes.settings.list_ai_models",
            return_value={"ok": True, "models": ["grok-vision-test"], "count": 1},
        ):
            response = self.client.get("/api/settings/ai-models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"], ["grok-vision-test"])

    def test_vision_test_route_uses_saved_server_side_key(self) -> None:
        with patch(
            "routes.settings.test_ai_vision_connection",
            return_value={"ok": True, "model": "grok-4.5", "vision_confirmed": True},
        ):
            response = self.client.post("/api/settings/ai-vision-test", json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["vision_confirmed"])

    def test_usage_ledger_route_reports_tokens_and_unknown_anlas_honestly(self) -> None:
        summary = {
            "calls": 4,
            "total_tokens": 1234,
            "images": 2,
            "anlas_spent": 0.0,
            "anlas_unknown_images": 2,
            "anlas_complete": False,
        }
        with patch("routes.settings.usage_summary", return_value=summary), patch(
            "routes.settings.LEDGER.recent", return_value=[]
        ):
            response = self.client.get("/api/settings/usage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_tokens"], 1234)
        self.assertFalse(response.json()["summary"]["anlas_complete"])

    def test_knowledge_status_and_rebuild_use_the_catalog_and_butler_workflow_interfaces(self) -> None:
        catalog = Mock()
        catalog.status.return_value = {
            "ok": True,
            "state": "ready",
            "usable": True,
            "documents": 13,
            "chunks": 54,
            "schema_version": 1,
            "index_version": "markdown-fts5-v1",
            "content_version": "abc123",
            "last_success_at": "2026-07-20T16:10:00+00:00",
            "last_error": "",
            "sources": [{"source": "README.md", "title": "Gallery", "chunk_count": 4}],
            "model_calls": 0,
        }
        with patch("routes.settings.get_knowledge_catalog", return_value=catalog), patch(
            "routes.settings.submit_knowledge_rebuild",
            new=AsyncMock(return_value={"ok": True, "workflow_id": "wf-knowledge"}),
        ) as submit:
            status = self.client.get("/api/settings/knowledge")
            rebuild = self.client.post("/api/settings/knowledge/rebuild", json={"path": "ignored"})

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["documents"], 13)
        self.assertNotIn(str(ROOT), json.dumps(status.json()))
        self.assertEqual(rebuild.status_code, 202)
        self.assertEqual(rebuild.json()["workflow_id"], "wf-knowledge")
        self.assertEqual(
            rebuild.json()["task_url"], "/butler?task=wf-knowledge#taskCenter"
        )
        submit.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
