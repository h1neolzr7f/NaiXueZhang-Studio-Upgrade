from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.asgi_client import TestClient

import server
from routes import mobile as mobile_routes


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class MobileShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(server.app)

    def setUp(self) -> None:
        mobile_routes.reset_mobile_pairing()

    def test_mobile_page_is_standalone_shell(self) -> None:
        html = (WEB / "m" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-mobile="1"', html)
        self.assertIn("/assets/m/m.css?v=", html)
        self.assertIn("/assets/m/m.js?v=", html)
        self.assertIn("/assets/shared/api-client.js?v=", html)
        self.assertNotIn("site-nav.js", html)
        self.assertNotIn("companion-dock", html)
        self.assertIn("发现", html)
        self.assertIn("换角", html)
        self.assertIn("批量", html)
        self.assertIn("流水线", html)
        self.assertIn("1.5.2", html)
        self.assertIn("m-sky", html)
        self.assertIn("m-tab-ico", html)
        css = (WEB / "m" / "m.css").read_text(encoding="utf-8")
        self.assertIn("--sakura", css)
        self.assertIn("#1a1230", css)

    def test_mobile_js_uses_api_client_and_keeps_paid_gates(self) -> None:
        js = (WEB / "m" / "m.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bfetch\s*\(", js))
        self.assertIn("window.ApiClient", js)
        self.assertIn("force_free: true", js)
        self.assertIn("generation_calls", js)
        self.assertIn("/api/nai/aitag/work/", js)
        self.assertIn("/api/plugin/char-swap/batch/preview", js)
        self.assertIn("/api/plugin/char-swap/batch/run", js)
        self.assertIn("/api/pipeline/run", js)
        self.assertIn("skipSessionToken", js)
        self.assertIn("这次可能已扣费", js)

    def test_mobile_routes_are_registered(self) -> None:
        page = self.client.get("/m")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Nai学长工作室 · 手机版", page.text)
        nested = self.client.get("/m/work/123")
        self.assertEqual(nested.status_code, 200)
        status = self.client.get("/api/mobile/status")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("loopback"))

    def test_pair_claim_works_without_session_token(self) -> None:
        started = self.client.post("/api/mobile/pair/start", json={})
        self.assertEqual(started.status_code, 200)
        code = started.json()["code"]
        self.assertTrue(str(code).isdigit())
        claimed = self.client.post(
            "/api/mobile/pair/claim",
            json={"code": code},
            headers={"X-Session-Token": "not-the-session-token"},
        )
        self.assertEqual(claimed.status_code, 200)
        token = claimed.json()["token"]
        self.assertTrue(token)
        self.assertTrue(mobile_routes.is_mobile_token(token))
        again = self.client.post(
            "/api/mobile/pair/claim",
            json={"code": code},
            headers={"X-Session-Token": "not-the-session-token"},
        )
        self.assertEqual(again.status_code, 403)

    def test_session_token_stays_loopback_only(self) -> None:
        from fastapi import HTTPException
        from tests.test_backend_fixes_20260812 import _fake_request

        with self.assertRaises(HTTPException) as exc_info:
            server.api_session_token(_fake_request("192.168.1.20"))
        self.assertEqual(exc_info.exception.status_code, 403)

    def test_launcher_opens_mobile_path(self) -> None:
        bat = (ROOT / "启动手机版.bat").read_text(encoding="utf-8")
        self.assertIn("GALLERY_HOST=0.0.0.0", bat)
        self.assertIn("GALLERY_ALLOW_REMOTE=1", bat)
        self.assertIn("GALLERY_OPEN_PATH=/m", bat)
        start = (ROOT / "START_GALLERY.bat").read_text(encoding="utf-8")
        self.assertIn("GALLERY_OPEN_PATH", start)

    def test_desktop_nav_count_unchanged(self) -> None:
        nav = (WEB / "shared" / "site-nav.js").read_text(encoding="utf-8")
        primary = nav.split("const NAV_SECONDARY", 1)[0]
        self.assertEqual(primary.count("{ href:"), 6)


if __name__ == "__main__":
    unittest.main()
