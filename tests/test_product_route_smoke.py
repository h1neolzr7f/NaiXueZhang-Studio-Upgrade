from __future__ import annotations

import time
import unittest

from tests.asgi_client import TestClient

import server


class ProductRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(server.app)

    def test_product_pages_and_api_are_reachable(self) -> None:
        cases = [
            ("/ops", "text/html"),
            ("/tag-assets", "text/html"),
            ("/aitag-library", "text/html"),
            ("/pipeline", "text/html"),
            ("/api/product/strategy", "application/json"),
            ("/api/product/verification", "application/json"),
        ]
        for path, content_type in cases:
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200)
                self.assertIn(content_type, res.headers.get("content-type", ""))

    def test_health_endpoint_is_fast_enough_for_dashboard(self) -> None:
        start = time.perf_counter()
        res = self.client.get("/api/product/health")
        elapsed = time.perf_counter() - start
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["health"]["checks"]["database"])
        self.assertNotIn("paths", payload["health"])
        self.assertLess(elapsed, 5.0)

    def test_existing_core_pages_remain_reachable(self) -> None:
        for path in ["/", "/studio", "/generated", "/settings", "/pixiv"]:
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200)
                self.assertIn("text/html", res.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
