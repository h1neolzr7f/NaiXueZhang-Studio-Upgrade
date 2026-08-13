from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import butler_service
import nai_api
from local_secrets import SecretProtectionUnavailable, protect_secret


ROOT = Path(__file__).resolve().parents[1]


class PaidJobAndButlerSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        butler_service._PENDING.clear()

    def test_auto_mode_cannot_skip_production_ticket_or_change_api_base(self) -> None:
        plan = {
            "reply": "好的，我来全自动改接口再出图。",
            "actions": [
                {"tool": "set_auto_mode", "arguments": {"auto_mode": True, "auto_repair": True}},
                {"tool": "modify_setting", "arguments": {"ai_api_base": "https://evil.example/v1"}},
                {
                    "tool": "generate_image",
                    "arguments": {"work_id": 7, "prompt": "1girl", "batch_count": 10},
                },
            ],
        }
        with patch.object(
            butler_service, "ai_status", return_value={"has_api_key": True, "model": "m"}
        ), patch.object(butler_service, "request_plan", return_value=plan), patch.object(
            butler_service, "_auto_mode_enabled", return_value=True
        ), patch.object(
            butler_service, "_auto_repair_enabled", return_value=True
        ), patch.object(
            butler_service, "_write_audit"
        ), patch.object(
            butler_service, "_require_work", return_value={}
        ):
            result = butler_service.run_chat("开启全自动然后改接口再出 10 张")

        tools = [item["tool"] for item in result["pending_actions"]]
        self.assertIn("set_auto_mode", tools)
        self.assertIn("generate_image", tools)
        self.assertTrue(any("ai_api_base" in item.get("reason", "") or "接口" in item.get("reason", "")
                            or "settings" in item.get("reason", "")
                            for item in result["rejected_actions"]))
        generate = next(item for item in result["pending_actions"] if item["tool"] == "generate_image")
        self.assertEqual(generate["work_order"]["retry_policy"], "no-5xx-retry")
        self.assertEqual(generate["work_order"]["cost"]["anlas_estimate"], "unknown")
        self.assertEqual(generate["lane"], "production")

    def test_empty_gallery_rejects_crawler_plan(self) -> None:
        with patch.object(butler_service, "_main_gallery_empty", return_value=True):
            with self.assertRaises(ValueError) as exc:
                butler_service.normalize_action({"tool": "start_crawler", "arguments": {}})
        self.assertIn("AITag", str(exc.exception))

    def test_question_does_not_plan_write_tools_when_preplanned_empty(self) -> None:
        plan = {"reply": "主图库为空时请先用 AITag 发现。", "actions": []}
        with patch.object(
            butler_service, "ai_status", return_value={"has_api_key": True, "model": "m"}
        ), patch.object(butler_service, "request_plan", return_value=plan):
            result = butler_service.run_chat("现在该怎么开始？")
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(result["tool_results"], [])

    def test_modify_setting_refuses_port_and_proxy(self) -> None:
        with self.assertRaises(ValueError) as exc:
            butler_service.normalize_action(
                {"tool": "modify_setting", "arguments": {"port": 9000, "proxy_url": "http://127.0.0.1:7890"}}
            )
        self.assertIn("/settings#ai-service", str(exc.exception))

    def test_modify_setting_cannot_enable_crawler_on_empty_gallery(self) -> None:
        with patch.object(butler_service, "_main_gallery_empty", return_value=True):
            with self.assertRaises(ValueError) as exc:
                butler_service.normalize_action(
                    {"tool": "modify_setting", "arguments": {"enabled": True}}
                )
        self.assertIn("AITag", str(exc.exception))

    def test_modify_setting_can_change_model_when_gallery_empty(self) -> None:
        with patch.object(butler_service, "_main_gallery_empty", return_value=True):
            action = butler_service.normalize_action(
                {"tool": "modify_setting", "arguments": {"ai_model": "gpt-4o-mini"}}
            )
        self.assertEqual(action["arguments"]["ai_model"], "gpt-4o-mini")

    def test_auto_repair_source_cannot_start_crawler_or_clear_user_env(self) -> None:
        source = (ROOT / "butler" / "execute.py").read_text(encoding="utf-8")
        repair = source.split('if tool == "auto_repair":', 1)[1].split(
            'if tool == "add_to_queue":', 1
        )[0]
        self.assertNotIn("SetEnvironmentVariable", repair)
        self.assertNotIn("start_pixiv_crawler", repair)
        self.assertIn("检修不会自动拉起爬虫", repair)

    def test_auto_repair_does_not_start_crawler_or_mutate_env(self) -> None:
        action = {"tool": "auto_repair", "arguments": {}}
        with patch.object(butler_service, "_main_gallery_empty", return_value=True), patch(
            "crawler_control.list_pixiv_crawler_pids", return_value=[]
        ), patch(
            "crawler_control.start_pixiv_crawler"
        ) as start, patch(
            "pixiv_nai_crawler.load_task",
            return_value={"enabled": True, "request_delay_sec": 2},
        ), patch(
            "pixiv_nai_crawler.retry_quarantined", return_value={"retried": 0}
        ), patch(
            "pixiv_nai_crawler.save_task"
        ) as save, patch(
            "subprocess.run"
        ) as run:
            run.return_value = type("Proc", (), {"stdout": "http://127.0.0.1:7890\n", "stderr": ""})()
            result = asyncio.run(butler_service._execute_confirmed(action))
        start.assert_not_called()
        save.assert_not_called()
        for call in run.call_args_list:
            blob = " ".join(str(part) for part in (call.args[0] if call.args else []))
            self.assertNotIn("SetEnvironmentVariable", blob)
        self.assertIn("AITag", result["message"])

    def test_auto_config_writes_under_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            data = root / "userdata"
            project.mkdir()
            data.mkdir()
            with patch.object(butler_service, "DATA_DIR", data), patch.object(
                butler_service, "ROOT", project
            ):
                butler_service._save_auto_config(auto_mode=True, auto_repair=False)
            self.assertTrue((data / "butler_auto.json").is_file())
            self.assertFalse((project / "data" / "butler_auto.json").exists())

    def test_butler_catalog_falls_back_to_package_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            empty = Path(temp) / "empty-data"
            empty.mkdir()
            with patch.object(butler_service, "DATA_DIR", empty):
                catalog = butler_service._load_butler_catalog()
        self.assertIn("tools", catalog)
        self.assertTrue(any(item.get("name") == "auto_repair" for item in catalog["tools"]))

    def test_director_catalog_falls_back_to_package_seed(self) -> None:
        from paths import seed_data_file

        with tempfile.TemporaryDirectory() as temp:
            empty = Path(temp) / "empty-data"
            empty.mkdir()
            import paths as paths_mod

            with patch.object(paths_mod, "_DATA_DIR_CACHE", empty):
                path = seed_data_file("director_catalog.json")
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "director_catalog.json")

    def test_posix_save_token_does_not_write_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            token_path = Path(temp) / "nai_token.local.json"
            with patch.object(nai_api, "TOKEN_PATH", token_path), patch(
                "local_secrets.os.name", "posix"
            ):
                with self.assertRaises(SecretProtectionUnavailable):
                    nai_api.save_token("pst-linux-must-not-persist")
            self.assertFalse(token_path.exists())
            with patch("local_secrets.os.name", "posix"):
                with self.assertRaises(SecretProtectionUnavailable):
                    protect_secret("pst-linux-must-not-persist")


class FrontendSecurityContractTests(unittest.TestCase):
    def test_progress_page_has_real_site_nav(self) -> None:
        html = (ROOT / "web" / "progress.html").read_text(encoding="utf-8")
        self.assertIn('id="siteNav"', html)
        self.assertNotIn('id=\\"siteNav\\"', html)
        self.assertIn("/assets/shared/site-nav.js", html)
        self.assertNotIn("http://127.0.0.1:8797/progress", html)

    def test_gallery_loads_toast_and_escapes_untrusted_strings(self) -> None:
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/assets/shared/ui-toast.js", index)
        panel = (ROOT / "web" / "plugins" / "char-swap" / "panel.js").read_text(encoding="utf-8")
        self.assertIn("esc(idTags)", panel)
        self.assertIn('src.summary || "角色"', panel)
        pixiv_html = (ROOT / "web" / "pixiv.html").read_text(encoding="utf-8")
        self.assertIn('type="password"', pixiv_html)
        self.assertIn('id="pxRefresh"', pixiv_html)

    def test_generated_queue_and_ops_escape_untrusted_strings(self) -> None:
        html = (ROOT / "web" / "generated.html").read_text(encoding="utf-8")
        self.assertIn("function escText(", html)
        self.assertIn("escText(item.message", html)
        self.assertIn("escText(batch.message", html)
        self.assertIn("escText(queue.message", html)
        self.assertIn("escText(msg", html)
        self.assertIn("escText(e && e.message", html)
        batch = (ROOT / "web" / "plugins" / "char-swap" / "batch.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('innerHTML = `<img src="${url}"', batch)
        ops = (ROOT / "web" / "ops.html").read_text(encoding="utf-8")
        self.assertIn("/assets/shared/escape.js", ops)
        self.assertIn("escapeHtml(x)", ops)

    def test_startup_maintenance_failures_are_logged(self) -> None:
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("WARNING: 生成库元数据迁移失败", server)
        self.assertIn("WARNING: 生成库缩略图维护失败", server)

    def test_studio_generate_no_longer_loops_in_the_browser(self) -> None:
        studio = (ROOT / "web" / "studio.js").read_text(encoding="utf-8")
        self.assertNotIn("for (let i = 0; i < copies", studio)
        self.assertIn("pollJob", studio)
        self.assertIn("copies", studio)


if __name__ == "__main__":
    unittest.main()
