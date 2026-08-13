from __future__ import annotations

import unittest
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


class CoreDependencyProfileTests(unittest.TestCase):
    def test_installer_banner_is_cmd_safe_and_describes_the_nai_only_path(self) -> None:
        installer = (ROOT / "INSTALL.bat").read_text(encoding="utf-8")
        self.assertNotIn("用此图生成", installer)
        for fragile in ("╔", "║", "╚", "═"):
            self.assertNotIn(fragile, installer)
        self.assertTrue(installer.isascii())
        self.assertIn("Gallery - NAI Tags - Pixiv Intake", installer)

    def test_core_dependency_files_are_pinned_and_exclude_heavy_features(self) -> None:
        requirements = (ROOT / "requirements.core.txt").read_text(encoding="utf-8")
        lock_lines = (ROOT / "requirements.core.lock.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        normalized = "\n".join(line.casefold() for line in lock_lines)

        for package in (
            "fastapi",
            "httpx",
            "numpy",
            "pillow",
            "psutil",
            "python-multipart",
            "pyyaml",
            "uvicorn",
        ):
            self.assertIn(package, requirements.casefold())
            self.assertTrue(
                any(line.casefold().startswith(f"{package}==") for line in lock_lines),
                f"{package} must be pinned in the Core lock",
            )
        self.assertTrue(
            all("==" in line for line in lock_lines if line and not line.startswith("#"))
        )
        for forbidden in (
            "playwright",
            "gradio",
            "opencv",
            "ultralytics",
            "langgraph",
            "torch",
            "nai-api",
        ):
            self.assertNotIn(forbidden, normalized)

    def test_core_intake_page_satisfies_every_dom_id_used_by_its_scripts(self) -> None:
        html = (ROOT / "scripts" / "core_web_progress.html").read_text(encoding="utf-8")
        scripts = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in ("scripts/core_web_intake.js", "web/pixiv-intake-control.js")
        )
        required = set(re.findall(r'byId\("([A-Za-z0-9_-]+)"\)', scripts))
        present = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
        self.assertEqual(set(), required - present)

    def test_core_public_schema_recursively_drops_intake_secrets(self) -> None:
        from scripts.routes_gallery_core import public_detail, public_search_result

        secret = "https://i.pximg.net/private-original.png?token=secret"
        work = {"id": 7, "title": "safe", "source_url": secret, "receipt": {"token": secret}}
        image = {"page_index": 0, "local_path": "NAI/1/7_p0.png", "original_url": secret, "source_page_index": 9}
        payload = {"work": work, "images": [image], "download_receipt": {"url": secret}}
        encoded = json.dumps(public_detail(payload), ensure_ascii=False)
        encoded_search = json.dumps(public_search_result({"page": 1, "page_size": 60, "total": 1, "items": [work]}))
        self.assertNotIn("pximg", encoded + encoded_search)
        self.assertNotIn("receipt", encoded + encoded_search)
        self.assertNotIn("source_page_index", encoded)
        self.assertIn("NAI/1/7_p0.png", encoded)

    def test_core_account_errors_never_echo_credentials_or_urls(self) -> None:
        from scripts import pixiv_accounts_core

        leaked = "https://oauth.example.invalid/?refresh_token=super-secret"
        with patch.object(pixiv_accounts_core, "_find", return_value={"id": "acc", "refresh_token": "x" * 64}), patch.object(
            pixiv_accounts_core, "ensure_access_token", side_effect=RuntimeError(leaked)
        ):
            result = pixiv_accounts_core.test_account_auth("acc")
        encoded = json.dumps(result)
        self.assertNotIn("oauth.example", encoded)
        self.assertNotIn("super-secret", encoded)
        self.assertEqual("auth_unavailable", result["error"]["code"])

    def test_core_server_honors_run_once_and_watch_requests(self) -> None:
        calls: list[bool] = []
        crawler = types.ModuleType("crawler_control")
        crawler.multi_crawler_status = lambda: {"pixiv": {"running": False}}
        crawler.start_crawler_target = lambda target, watch=True: calls.append(watch) or {"pixiv": {"started": True}}
        crawler.stop_crawler_target = lambda target: {"pixiv": {"crawler_pixiv": []}}
        accounts = types.ModuleType("pixiv_accounts")
        accounts.add_account = lambda **kwargs: {"ok": True}
        accounts.get_active_account = lambda: None
        accounts.list_accounts = lambda: []
        accounts.remove_account = lambda account_id: {"ok": True}
        accounts.switch_account = lambda account_id: {"ok": True}
        accounts.test_account_auth = lambda account_id=None: {"ok": True}
        accounts.update_account_token = lambda account_id, token: {"ok": True}
        routes = types.ModuleType("routes")
        for name in ("gallery", "maintenance", "nai_tags", "pixiv_intake"):
            module = types.SimpleNamespace(router=APIRouter(), page_router=APIRouter())
            setattr(routes, name, module)
        shared = types.ModuleType("server_shared")
        shared.WEB_DIR = ROOT / "does-not-exist"
        spec = importlib.util.spec_from_file_location("_core_server_contract", ROOT / "scripts" / "server_core.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"crawler_control": crawler, "pixiv_accounts": accounts, "routes": routes, "server_shared": shared}):
            assert spec and spec.loader
            spec.loader.exec_module(module)
        client = TestClient(module.app)
        self.assertEqual(200, client.post("/api/crawler/start", json={"watch": False}).status_code)
        self.assertEqual(200, client.post("/api/crawler/start", json={"watch": True}).status_code)
        self.assertEqual([False, True], calls)


if __name__ == "__main__":
    unittest.main()
