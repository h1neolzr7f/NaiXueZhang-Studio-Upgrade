from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_atlas.external import normalize_atlas_book, normalize_atlas_entry
from codex_atlas.online import (
    ATLAS_POINTER_URL,
    CodexAtlasClient,
    CodexAtlasClientError,
    parse_atlas_work_id,
)
from routes import codex_atlas as atlas_routes


class _Response:
    def __init__(self, payload, status_code: int = 200, url: str = ""):
        if isinstance(payload, (bytes, bytearray)):
            self.content = bytes(payload)
            self._payload = None
        else:
            self.content = json.dumps(payload).encode("utf-8")
            self._payload = payload
        self.status_code = status_code
        self.text = self.content.decode("utf-8", errors="replace")
        self.url = url
        self.history = []

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _HTTP:
    def __init__(self):
        self.calls: list[str] = []
        self.pointer = {"release": "r-327b1017c3b03674f9d6", "schemaVersion": 1}
        self.books = [
            {
                "id": "suozhang",
                "title": "所长常规NovelAI个人法典",
                "author": "戒红所",
                "type": "codex",
                "entryCount": 2,
                "nsfw": False,
            },
            {
                "id": "suozhang_r18",
                "title": "所长色色",
                "author": "戒红所",
                "type": "codex",
                "entryCount": 1,
                "nsfw": True,
            },
            {
                "id": "mengshen_r18",
                "title": "外部源",
                "nsfw": True,
                "dataUrl": "https://prompt-vault-gallery.pages.dev/data/prompt-vault.json",
            },
        ]
        self.suozhang = {
            "id": "suozhang",
            "title": "所长常规NovelAI个人法典",
            "author": "戒红所",
            "entries": [
                {
                    "id": "sz-0001",
                    "title": "蓝发少女",
                    "tags": "1girl, blue hair, masterpiece",
                    "negative": "lowres",
                    "path": ["角色", "发型"],
                    "image": "sz-0001.jpg",
                },
                {
                    "id": "sz-0002",
                    "title": "红发少女",
                    "tags": "1girl, red hair",
                    "path": ["角色"],
                    "image": "sz-0002.jpg",
                },
            ],
        }

    def get(self, url: str, params=None):
        self.calls.append(url)
        if url == ATLAS_POINTER_URL:
            return _Response(self.pointer, url=url)
        if url.endswith("/codexes.json"):
            return _Response(self.books, url=url)
        if url.endswith("/suozhang.json"):
            return _Response(self.suozhang, url=url)
        if url.endswith("/sz-0001.jpg"):
            return _Response(b"\xff\xd8fakejpeg", url=url)
        if "evil.example" in url or "pages.dev" in url:
            raise AssertionError(f"external host must not be fetched: {url}")
        return _Response({}, status_code=404, url=url)


class CodexAtlasNormalizerTests(unittest.TestCase):
    def test_external_book_is_marked_and_work_id_is_compound(self) -> None:
        book = normalize_atlas_book(
            {
                "id": "mengshen_r18",
                "title": "外部",
                "nsfw": True,
                "dataUrl": "https://prompt-vault-gallery.pages.dev/data/x.json",
            }
        )
        self.assertIsNotNone(book)
        self.assertTrue(book.external)
        self.assertTrue(book.nsfw)
        local = normalize_atlas_book({"id": "suozhang", "title": "所长", "author": "戒红所"})
        entry = normalize_atlas_entry(
            {"id": "sz-0001", "title": "蓝发", "tags": "1girl, blue hair", "image": "sz-0001.jpg"},
            book=local,
            source_url="https://novelai.quicktagcloud.com/?codex=suozhang",
        )
        self.assertEqual(entry.work_id, "suozhang:sz-0001")
        self.assertEqual(entry.image, "sz-0001.jpg")
        self.assertEqual(parse_atlas_work_id(entry.work_id), ("suozhang", "sz-0001"))


class CodexAtlasClientTests(unittest.TestCase):
    def test_search_uses_official_release_and_skips_external_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            http = _HTTP()
            client = CodexAtlasClient(http_client=http, cache_root=Path(tmp))
            books = client.list_books(safe_only=True)
            self.assertEqual([book.book_id for book in books], ["suozhang"])
            page = client.search(query="blue hair", book_id="suozhang")
            self.assertEqual(page.total, 1)
            self.assertEqual(page.entries[0].work_id, "suozhang:sz-0001")
            self.assertEqual(page.entries[0].tags, "1girl, blue hair, masterpiece")
            client.search(query="blue hair", book_id="suozhang")
            self.assertEqual(http.calls.count(ATLAS_POINTER_URL), 1)
            self.assertTrue(all("pages.dev" not in url for url in http.calls))

    def test_nsfw_and_path_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            http = _HTTP()
            client = CodexAtlasClient(http_client=http, cache_root=Path(tmp))
            with self.assertRaises(CodexAtlasClientError):
                client.load_entries("suozhang_r18", safe_only=True)
            with self.assertRaises(ValueError):
                client.get_image("suozhang", "../secret.jpg")
            with self.assertRaises(ValueError):
                parse_atlas_work_id("https://evil.example/x")


class CodexAtlasRouteTests(unittest.TestCase):
    def test_search_and_draft_stay_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            http = _HTTP()
            client = CodexAtlasClient(http_client=http, cache_root=Path(tmp) / "cache")
            with patch.object(atlas_routes, "get_atlas_client", return_value=client), patch.object(
                atlas_routes, "DATA_DIR", Path(tmp)
            ), patch.object(atlas_routes, "_online_enabled", return_value=True):
                books = atlas_routes.api_atlas_books(safe_only=True)
                self.assertEqual(books["items"][0]["id"], "suozhang")
                self.assertEqual(books["items"][0]["kind"], "book")
                result = atlas_routes.api_atlas_search(
                    q="blue",
                    prompt="",
                    book_id="suozhang",
                    group="",
                    page=1,
                    page_size=60,
                    sort="relevance",
                    safe_only=True,
                )
                self.assertEqual(result["source"], "codex-atlas")
                self.assertEqual(result["generation_calls"], 0)
                self.assertEqual(result["items"][0]["id"], "suozhang:sz-0001")
                self.assertTrue(str(result["items"][0]["cover_url"]).startswith("/api/nai/codex-atlas/cover/"))
                detail = atlas_routes.api_atlas_entry("suozhang:sz-0001", safe_only=True)
                self.assertEqual(detail["work"]["prompt"], "1girl, blue hair, masterpiece")
                draft = atlas_routes.api_atlas_draft("suozhang:sz-0001", safe_only=True)
                self.assertEqual(draft["generation_calls"], 0)
                self.assertEqual(draft["source"], "codex-atlas")
                self.assertIn("draft=", draft["studio_url"])
                self.assertEqual(draft["draft"]["comment"]["prompt"], "1girl, blue hair, masterpiece")
                self.assertEqual(draft["draft"]["source"]["provider"], "codex-atlas")


if __name__ == "__main__":
    unittest.main()
