from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aitag_core.external import AitagConfig, normalize_aitag_detail
from aitag_core.online import AitagClient, AitagClientError
from routes import aitag as aitag_routes


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = __import__("json").dumps(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        if self.status_code >= 400:
            raise ValueError("no json")
        return self._payload


class _HTTP:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, params: dict[str, str]):
        self.calls.append((url, params))
        if url.endswith("/api/config"):
            return _Response({"asset_base_url": "https://cdn.example.test/", "available_years": [2024]})
        if url.endswith("/api/ai_works_search"):
            return _Response(
                {
                    "items": [
                        {
                            "id": "42",
                            "title": "Online character",
                            "userName": "artist-live",
                            "AI_type": "NovelAI",
                            "tags": "[\"1girl\", \"blue hair\"]",
                        }
                    ],
                    "total": 1,
                }
            )
        if url.endswith("/api/work/42"):
            return _Response(
                {
                    "id": "42",
                    "title": "Online character",
                    "AI_type": "NovelAI",
                    "tags": ["1girl", "blue hair", "blue eyes"],
                    "images": [
                        {
                            "id": "7",
                            "workId": "42",
                            "authorId": "9",
                            "imageType": "novelai",
                            "fileName": "image-7",
                            "model": "nai-v4",
                            "promptText": "1girl, blue hair, blue eyes",
                            "aiJson": '{"uc":"lowres"}',
                        }
                    ],
                }
            )
        return _Response({}, status_code=404)


class _FakeCatalog:
    def __init__(self):
        self.imported = None

    def import_records(self, records, **kwargs):
        self.imported = (records, kwargs)
        return {"ok": True, "inserted": 1, "updated": 0}

    def search(self, **kwargs):
        return {"items": [{"reference_id": "ref_online"}], "total": 1}


class AitagOnlineClientTests(unittest.TestCase):
    def test_search_and_detail_use_official_shapes_and_cache_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = _HTTP()
            client = AitagClient(http_client=http, cache_root=Path(tmp))
            page = client.search(query="blue hair", page=2, page_size=60)
            self.assertEqual(page.total, 1)
            self.assertEqual(page.works[0].work_id, "42")
            self.assertEqual(page.works[0].creator, "artist-live")
            self.assertEqual(page.works[0].tags, ("1girl", "blue hair"))
            detail = client.get_work("42")
            image = detail.images[0]
            self.assertEqual(image.author_id, "9")
            self.assertEqual(image.file_name, "image-7")
            self.assertEqual(len(http.calls), 2)
            client.search(query="blue hair", page=2, page_size=60)
            self.assertEqual(len(http.calls), 2)

    def test_search_404_is_an_empty_page(self):
        class Missing(_HTTP):
            def get(self, url, *, params):
                self.calls.append((url, params))
                return _Response({}, 404)

        with tempfile.TemporaryDirectory() as tmp:
            page = AitagClient(http_client=Missing(), cache_root=Path(tmp)).search(query="missing")
            self.assertEqual(page.works, ())
            self.assertFalse(page.has_more)

    def test_base_url_is_allowlisted(self):
        with self.assertRaises(ValueError):
            AitagClient(base_url="https://example.test")

    def test_popular_uses_monthly_rank_while_recent_uses_search(self):
        class SplitHTTP(_HTTP):
            def get(self, url, *, params):
                self.calls.append((url, dict(params)))
                if url.endswith("/api/rank/monthly/real"):
                    return _Response(
                        {
                            "items": [
                                {
                                    "id": "hot-1",
                                    "title": "Ranked work",
                                    "AI_type": "NAI",
                                    "total_bookmarks": 2144,
                                }
                            ],
                            "total": 1,
                        }
                    )
                if url.endswith("/api/ai_works_search"):
                    return _Response(
                        {
                            "items": [
                                {
                                    "id": "new-1",
                                    "title": "Newest work",
                                    "AI_type": "NAI",
                                }
                            ],
                            "total": 1,
                        }
                    )
                if url.endswith("/api/rank/monthly"):
                    return _Response(
                        {
                            "items": [
                                {
                                    "id": "july-1",
                                    "title": "July rank",
                                    "AI_type": "NAI",
                                }
                            ],
                            "total": 1,
                        }
                    )
                return _Response({}, status_code=404)

        with tempfile.TemporaryDirectory() as tmp:
            http = SplitHTTP()
            client = AitagClient(http_client=http, cache_root=Path(tmp))
            popular = client.search(sort="popular")
            recent = client.search(sort="recent")
            historic = client.search(sort="hot", time_range="2026-07")

        self.assertEqual([work.work_id for work in popular.works], ["hot-1"])
        self.assertEqual([work.work_id for work in recent.works], ["new-1"])
        self.assertEqual([work.work_id for work in historic.works], ["july-1"])
        self.assertTrue(http.calls[0][0].endswith("/api/rank/monthly/real"))
        self.assertNotIn("sort", http.calls[0][1])
        self.assertTrue(http.calls[1][0].endswith("/api/ai_works_search"))
        self.assertEqual(http.calls[1][1].get("sort"), "new")
        self.assertTrue(http.calls[2][0].endswith("/api/rank/monthly"))
        self.assertEqual(http.calls[2][1].get("period"), "2026-07")


class AitagOnlineRouteTests(unittest.TestCase):
    def setUp(self):
        self.http = _HTTP()
        self.tmp = tempfile.TemporaryDirectory()
        self.client = AitagClient(http_client=self.http, cache_root=Path(self.tmp.name))
        self.catalog = _FakeCatalog()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_online_apply_only_patches_nai_draft(self):
        comment = {"model": "nai-v4", "prompt": "cinematic cafe", "v4_prompt": {"caption": {}}}
        with patch.object(aitag_routes, "get_aitag_client", return_value=self.client):
            result = aitag_routes.api_aitag_apply("42", {"comment": comment, "slot_index": 0})
        self.assertEqual(result["provider"], "aitag-online")
        self.assertEqual(result["generation_calls"], 0)
        self.assertIn("char_captions", result["comment"]["v4_prompt"]["caption"])
        self.assertEqual(result["work_id"], "42")

    def test_online_import_is_explicit_and_uses_local_catalog(self):
        with patch.object(aitag_routes, "get_aitag_client", return_value=self.client), patch.object(
            aitag_routes, "get_reference_catalog", return_value=self.catalog
        ):
            result = aitag_routes.api_aitag_import({"work_id": "42", "image_index": 0})
        self.assertEqual(result["reference_id"], "ref_online")
        records, options = self.catalog.imported
        self.assertEqual(options["source"], "aitag-online")
        self.assertEqual(records[0]["source"], "aitag-online")
        self.assertEqual(result["generation_calls"], 0)


if __name__ == "__main__":
    unittest.main()
