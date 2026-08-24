"""Regression tests for 2026-08-12 vulnerability fixes."""

from __future__ import annotations

import pytest

from generated_gallery import _group_key, _matches_group
from network_safety import (
    validate_ai_api_base,
    validate_image_download_url,
    validate_provider_api_base,
)


def test_ai_api_base_rejects_private_and_unknown() -> None:
    with pytest.raises(ValueError):
        validate_ai_api_base("http://evil.example/v1")
    with pytest.raises(ValueError):
        validate_ai_api_base("https://127.0.0.1/v1")
    with pytest.raises(ValueError):
        validate_ai_api_base("https://attacker.example/v1")
    assert validate_ai_api_base("https://api.openai.com/v1").startswith("https://")
    assert validate_ai_api_base("https://api.deepseek.com") 


def test_image_url_rejects_metadata_and_http() -> None:
    with pytest.raises(ValueError):
        validate_image_download_url("http://i.pximg.net/x.png")
    with pytest.raises(ValueError):
        validate_image_download_url("https://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        validate_image_download_url("https://evil.example/a.png")
    ok = validate_image_download_url("https://api.idlecloud.cc/files/a.png")
    assert ok.startswith("https://")


def test_provider_api_base_empty_ok() -> None:
    assert validate_provider_api_base("") == ""


def test_matches_group_includes_run_series_under_bare_work_id() -> None:
    item = {
        "work_id": 42,
        "source_gallery_id": "site",
        "generation_series_id": "task-abc",
    }
    assert _matches_group(item, "42") is True
    assert _matches_group(item, "run:task-abc:42") is True
    assert _matches_group(item, "run:other:42") is False
    # Cross-gallery isolation
    assert _matches_group(item, "gallery:codex:42") is False
    codex = {**item, "source_gallery_id": "codex"}
    assert _matches_group(codex, "gallery:codex:42") is True
    assert _matches_group(codex, "42") is False


def test_matches_group_coerces_string_work_id() -> None:
    item = {
        "work_id": "99",
        "source_gallery_id": "site",
        "generation_series_id": "",
    }
    assert _matches_group(item, "99") is True


def test_group_key_site_and_gallery() -> None:
    assert _group_key(1, source_gallery_id="site") == "1"
    assert _group_key(1, source_gallery_id="codex") == "gallery:codex:1"
    assert _group_key(1, source_gallery_id="site", generation_series_id="task-a") == "1"
    assert _group_key(1, source_gallery_id="codex", generation_series_id="task-a") == "gallery:codex:1"
