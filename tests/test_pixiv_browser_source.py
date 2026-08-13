from __future__ import annotations

from unittest import mock

import httpx

from pixiv_browser_source import PixivBrowserSource
from pixiv_nai_source import PixivAPIError, PixivSourceProtocolError
from pixiv_public_source import PixivPublicWebSource

DETAIL = {
    "id": "123",
    "illustId": "123",
    "title": "browser NAI work",
    "description": "caption",
    "userId": "456",
    "userName": "Alice",
    "createDate": "2026-08-03T08:13:00+00:00",
    "aiType": 2,
    "illustType": 0,
    "xRestrict": 0,
    "viewCount": 99,
    "bookmarkCount": 12,
    "tags": {"tags": [{"tag": "NovelAI"}, {"tag": "girl"}]},
    "urls": {"original": "https://i.pximg.net/img-original/a_p0.png"},
}


def _search_handler(expression: str):
    if "/ajax/search/artworks" in expression:
        return {
            "error": False,
            "body": {
                "illustManga": {
                    "data": [
                        {
                            "id": "123",
                            "title": "browser NAI work",
                            "userId": "456",
                            "userName": "Alice",
                            "aiType": 2,
                            "pageCount": 1,
                        }
                    ],
                    "lastPage": 2,
                }
            },
        }
    if "/ajax/illust/123?" in expression:
        return {"error": False, "body": {**DETAIL, "pageCount": 1}}
    raise AssertionError(f"unexpected fetch: {expression}")


def test_browser_source_hydrates_search_via_page_eval() -> None:
    source = PixivBrowserSource(
        page_eval=_search_handler, client=httpx.Client(), ai_prefilter=True
    )
    page = source.fetch_page({"type": "search", "query": "NovelAI"})

    assert len(page.works) == 1
    assert page.works[0].work_id == 123
    assert page.works[0].pixiv_ai_type == 2
    assert page.works[0].pages[0].original_url.endswith("a_p0.png")
    assert "p=2" in page.next_cursor
    source.close()


def test_browser_source_fetch_failure_is_retryable_api_error() -> None:
    def failing(_expression: str):
        raise RuntimeError("browser page navigated to challenge")

    source = PixivBrowserSource(page_eval=failing, client=httpx.Client())
    try:
        try:
            source.fetch_page({"type": "search", "query": "NovelAI"})
        except PixivAPIError as exc:
            assert exc.retryable is True
        else:
            raise AssertionError("fetch failure should surface as PixivAPIError")
    finally:
        source.close()


def test_browser_source_rejects_error_payload() -> None:
    def error_payload(_expression: str):
        return {"error": True, "message": "challenge"}

    source = PixivBrowserSource(page_eval=error_payload, client=httpx.Client())
    try:
        try:
            source.fetch_page({"type": "search", "query": "NovelAI"})
        except PixivSourceProtocolError as exc:
            assert "error payload" in str(exc)
        else:
            raise AssertionError("error payload should raise PixivSourceProtocolError")
    finally:
        source.close()


def test_browser_source_unavailable_when_playwright_missing() -> None:
    with mock.patch("pixiv_browser_source.sync_playwright", None):
        assert PixivBrowserSource.available() is False


def test_crawler_selects_browser_source_when_enabled_and_available() -> None:
    from pixiv_nai_crawler import _build_pixiv_source

    task = {
        "source_mode": "public",
        "account_id": "",
        "max_download_bytes": 134217728,
        "require_pixiv_ai_generated": True,
        "request_delay_sec": 1.0,
        "proxy_url": "",
        "browser_mode": True,
    }
    with mock.patch("pixiv_nai_crawler._active_pixiv_account_id", return_value=""), mock.patch(
        "pixiv_nai_crawler.PixivBrowserSource.available", return_value=True
    ):
        source, selected = _build_pixiv_source(task)
    assert selected == "public_browser"
    assert isinstance(source, PixivBrowserSource)
    source.close()


def test_crawler_falls_back_to_httpx_when_browser_unavailable() -> None:
    from pixiv_nai_crawler import _build_pixiv_source

    task = {
        "source_mode": "public",
        "account_id": "",
        "max_download_bytes": 134217728,
        "require_pixiv_ai_generated": True,
        "request_delay_sec": 1.0,
        "proxy_url": "",
        "browser_mode": True,
    }
    with mock.patch("pixiv_nai_crawler._active_pixiv_account_id", return_value=""), mock.patch(
        "pixiv_nai_crawler.PixivBrowserSource.available", return_value=False
    ):
        source, selected = _build_pixiv_source(task)
    assert selected == "public"
    assert isinstance(source, PixivPublicWebSource)
    source.close()
