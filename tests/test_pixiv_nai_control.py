from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import pixiv_intake
from pixiv_nai_source import PixivSourcePage


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pixiv_intake.router)
    return TestClient(app)


def test_pixiv_task_api_round_trip_and_validation(tmp_path: Path) -> None:
    with patch.object(pixiv_intake, "ROOT", tmp_path):
        with _client() as client:
            initial = client.get("/api/crawler/pixiv/task")
            saved = client.post(
                "/api/crawler/pixiv/task",
                json={
                    "enabled": True,
                    "account_id": "acc-1",
                    "scopes": [
                        {
                            "id": "ranking",
                            "type": "ranking",
                            "mode": "day",
                            "enabled": True,
                        }
                    ],
                    "max_pages_per_run": 4,
                    "max_works_per_run": 20,
                },
            )
            invalid = client.post(
                "/api/crawler/pixiv/task",
                json={"enabled": True, "scopes": []},
            )

    assert initial.status_code == 200
    assert initial.json()["task"]["enabled"] is False
    assert initial.json()["presets"]
    assert any(item["id"] == "arknights" for item in initial.json()["presets"])
    assert saved.status_code == 200
    assert saved.json()["task"]["scopes"][0]["type"] == "ranking"
    assert invalid.status_code == 400


def test_pixiv_task_reset_search_clears_scope_cursors(tmp_path: Path) -> None:
    from pixiv_nai_crawler import _save_state, load_state

    with patch.object(pixiv_intake, "ROOT", tmp_path):
        (tmp_path / "data").mkdir()
        _save_state(
            tmp_path,
            {
                "version": 1,
                "scopes": {"novelai": {"cursor": "abc", "offset": 9}},
                "failures": {},
                "quarantine": {},
            },
        )
        with _client() as client:
            saved = client.post(
                "/api/crawler/pixiv/task",
                json={
                    "enabled": True,
                    "scopes": [
                        {
                            "id": "novelai",
                            "type": "search",
                            "query": "NovelAI",
                            "sort": "date_desc",
                            "search_target": "partial_match_for_tags",
                            "enabled": True,
                        }
                    ],
                    "reset_search": True,
                },
            )

    assert saved.status_code == 200
    assert saved.json()["reset_search"] is True
    state = load_state(root=tmp_path)
    assert state["scopes"]["novelai"]["cursor"] == ""
    assert state["scopes"]["novelai"]["offset"] == 0


def test_pixiv_report_api_contains_only_aggregate_receipts(tmp_path: Path) -> None:
    with patch.object(pixiv_intake, "ROOT", tmp_path):
        with _client() as client:
            response = client.get("/api/crawler/pixiv/report")

    payload = response.json()
    assert response.status_code == 200
    assert payload["report"]["status"] == "never_run"
    assert "source_url" not in str(payload)


def test_pixiv_preflight_uses_unsaved_form_and_never_persists(tmp_path: Path) -> None:
    class EmptySource:
        def __init__(self) -> None:
            self.closed = 0

        def fetch_page(self, scope: dict, cursor: str = "") -> PixivSourcePage:
            return PixivSourcePage(works=(), next_cursor="")

        def download_original(self, url: str, destination: Path) -> None:
            raise AssertionError("empty page has no downloads")

        def close(self) -> None:
            self.closed += 1

    source = EmptySource()
    payload = {
        "enabled": False,
        "account_id": "local-account-slot",
        "scopes": [
            {"id": "search-1", "type": "search", "query": "NovelAI", "enabled": True}
        ],
        "retry_max": 1,
        "request_delay_sec": 0,
    }

    with (
        patch.object(pixiv_intake, "ROOT", tmp_path),
        patch("pixiv_nai_preflight.PixivNAISource", return_value=source),
        _client() as client,
    ):
        response = client.post(
            "/api/crawler/pixiv/preflight?max_pages=1&max_works=5",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["report"]["status"] == "completed"
    assert response.json()["report"]["works_found"] == 0
    assert source.closed == 1
    assert list(tmp_path.iterdir()) == []
