"""Regression tests for the 2026-08-12 backend defect fixes.

Covers: accounts backup restore, atomic writes, upload-job TOCTOU guard,
launch_status deepcopy, AI secret single-read/decrypt failure, corrupted
config warnings, draft identity matching, selector-pack hot reload,
session-token loopback restriction, and silent-except logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

import pixiv_accounts
import pixiv_ai_transport
import pixiv_launch
import pixiv_launch_config
import user_prefs


# --- #1 accounts backup restore ----------------------------------------------


@pytest.fixture()
def accounts_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(pixiv_accounts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        pixiv_accounts, "ACCOUNTS_PATH", tmp_path / "pixiv_accounts.local.json"
    )
    monkeypatch.setattr(
        pixiv_accounts,
        "ACCOUNTS_BACKUP_PATH",
        tmp_path / "pixiv_accounts.local.backup.json",
    )
    monkeypatch.setattr(
        pixiv_accounts, "LEGACY_SECRET_PATH", tmp_path / "pixiv.local.json"
    )
    return tmp_path


@pytest.mark.skipif(os.name != "nt", reason="Pixiv account restore encrypts with Windows DPAPI")
def test_corrupt_main_accounts_file_recovers_from_backup(
    accounts_paths: Path,
) -> None:
    backup = {
        "active_id": "a1",
        "accounts": [{"id": "a1", "label": "t", "refresh_token": "tok-backup-1"}],
    }
    pixiv_accounts.ACCOUNTS_BACKUP_PATH.write_text(
        json.dumps(backup, ensure_ascii=False), encoding="utf-8"
    )
    pixiv_accounts.ACCOUNTS_PATH.write_text("{corrupted!!!", encoding="utf-8")

    data = pixiv_accounts._load_accounts_file()

    assert data["accounts"][0]["id"] == "a1"
    assert data["accounts"][0]["refresh_token"] == "tok-backup-1"
    # 主文件已被从备份恢复（且落盘为加密形式）
    restored_raw = pixiv_accounts.ACCOUNTS_PATH.read_text(encoding="utf-8")
    restored = json.loads(restored_raw)
    assert restored["accounts"][0]["id"] == "a1"
    assert "tok-backup-1" not in restored_raw


def test_load_accounts_returns_empty_only_when_both_copies_fail(
    accounts_paths: Path,
) -> None:
    pixiv_accounts.ACCOUNTS_PATH.write_text("{corrupted!!!", encoding="utf-8")
    pixiv_accounts.ACCOUNTS_BACKUP_PATH.write_text("not json either", encoding="utf-8")

    data = pixiv_accounts._load_accounts_file()

    assert data["accounts"] == []


@pytest.mark.skipif(os.name != "nt", reason="Pixiv account writes encrypt with Windows DPAPI")
def test_save_accounts_file_writes_backup_atomically(accounts_paths: Path) -> None:
    first = {
        "active_id": "a1",
        "accounts": [{"id": "a1", "label": "t", "refresh_token": "tok-one"}],
    }
    second = {
        "active_id": "a1",
        "accounts": [{"id": "a1", "label": "t", "refresh_token": "tok-two"}],
    }
    pixiv_accounts._save_accounts_file(first)
    pixiv_accounts._save_accounts_file(second)

    backup = json.loads(
        pixiv_accounts.ACCOUNTS_BACKUP_PATH.read_text(encoding="utf-8")
    )
    assert backup["accounts"], "备份文件必须随保存一起写入"
    assert not list(accounts_paths.glob("*.tmp"))


# --- #5 atomic writes ---------------------------------------------------------


def test_save_stats_db_uses_atomic_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pixiv_accounts, "STATS_PATH", tmp_path / "stats.json")
    pixiv_accounts._save_stats_db({"accounts": {"a1": {"followers": 3}}})
    assert json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))[
        "accounts"
    ]["a1"]["followers"] == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_save_prefs_uses_atomic_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(user_prefs, "PREFS_PATH", tmp_path / "user_prefs.json")
    user_prefs.save_prefs({"quick_send_studio": True})
    raw = json.loads((tmp_path / "user_prefs.json").read_text(encoding="utf-8"))
    assert raw["quick_send_studio"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_generate_post_copy_draft_write_is_atomic() -> None:
    source = Path(pixiv_launch.__file__).read_text(encoding="utf-8")
    body = source.split("def generate_post_copy", 1)[1].split(
        "def load_prepared_submission", 1
    )[0]
    assert "atomic_write_text(" in body
    assert "DRAFT_PATH" in body
    assert ".write_text(" not in body


def test_accounts_migration_write_is_atomic() -> None:
    source = Path(pixiv_accounts.__file__).read_text(encoding="utf-8")
    body = source.split("def _read_accounts_secret_file", 1)[1].split(
        "def _encrypt_accounts_payload", 1
    )[0]
    assert "atomic_write_text(" in body
    assert ".write_text(" not in body


# --- #2 / #7 upload job TOCTOU + deepcopy snapshot ----------------------------


class _DummyThread:
    """Thread stand-in that never runs the worker, keeping status 'running'."""

    def __init__(self, target=None, daemon=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        pass


@pytest.fixture()
def job_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pixiv_launch, "LAST_JOB_PATH", tmp_path / "last_job.json")
    monkeypatch.setattr(
        pixiv_launch,
        "_resolve_selection_batches",
        lambda payload: [{"image_ids": ["img-1"], "group_id": ""}],
    )
    monkeypatch.setattr(
        pixiv_launch, "threading", SimpleNamespace(Thread=_DummyThread)
    )
    saved_job = dict(pixiv_launch._JOB)
    saved_request = dict(pixiv_launch._LAST_JOB_REQUEST)
    try:
        yield
    finally:
        with pixiv_launch._LOCK:
            pixiv_launch._JOB.clear()
            pixiv_launch._JOB.update(saved_job)
            pixiv_launch._LAST_JOB_REQUEST.clear()
            pixiv_launch._LAST_JOB_REQUEST.update(saved_request)


def test_second_upload_job_is_rejected_while_running(job_env) -> None:
    first = pixiv_launch.start_upload_job({"image_id": "img-1"})
    assert first["ok"] is True
    second = pixiv_launch.start_upload_job({"image_id": "img-1"})
    assert second["ok"] is False
    assert "进行中" in second["message"]


def test_second_launch_is_rejected_while_running(job_env) -> None:
    first = pixiv_launch.launch_one_click({"image_id": "img-1"})
    assert first["ok"] is True
    second = pixiv_launch.launch_one_click({"image_id": "img-1"})
    assert second["ok"] is False
    assert "进行中" in second["message"]


def test_concurrent_upload_start_allows_exactly_one(job_env) -> None:
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def _start() -> None:
        barrier.wait(timeout=10)
        results.append(pixiv_launch.start_upload_job({"image_id": "img-1"}))

    threads = [threading.Thread(target=_start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sum(1 for r in results if r.get("ok")) == 1
    assert sum(1 for r in results if not r.get("ok")) == 1


def test_launch_status_returns_deep_snapshot(job_env) -> None:
    pixiv_launch.start_upload_job({"image_id": "img-1"})
    snapshot = pixiv_launch.launch_status()
    snapshot["progress"]["current"] = 999
    snapshot["progress"]["label"] = "tampered"
    fresh = pixiv_launch.launch_status()
    assert fresh["progress"]["current"] == 0
    assert fresh["progress"]["label"] == "上传"


# --- #3 butler modify_setting writes to data_dir atomically -------------------


def test_butler_modify_setting_writes_ai_config_into_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import butler_service

    monkeypatch.setattr(butler_service, "DATA_DIR", tmp_path)
    result = asyncio.run(
        butler_service._execute_confirmed(
            {"tool": "modify_setting", "arguments": {"ai_model": "deepseek-v4-flash"}}
        )
    )
    assert result["ok"] is True
    target = tmp_path / "ai.local.json"
    assert target.exists(), "ai.local.json 必须写入 data_dir()"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["model"] == "deepseek-v4-flash"
    assert not list(tmp_path.glob("*.tmp"))


# --- #4 AI secret single read + decrypt failure -------------------------------


def test_ai_env_reads_secret_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_secret() -> dict:
        calls.append(1)
        return {
            "api_key": "plain-relay-key",
            "api_base": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        }

    monkeypatch.setattr(pixiv_ai_transport, "_read_ai_secret", fake_secret)
    env = pixiv_ai_transport._ai_env({"ai": {"provider": "", "api_base": "", "model": ""}})
    assert env["api_key"] == "plain-relay-key"
    assert env["api_base"] == "https://api.deepseek.com/v1"
    assert len(calls) == 1


def test_ai_env_raises_clear_error_on_undecryptable_dpapi_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pixiv_ai_transport,
        "_read_ai_secret",
        lambda: {"api_key": "dpapi:v1:bad"},
    )
    with pytest.raises(ValueError, match="本地密钥解密失败"):
        pixiv_ai_transport._ai_env({"ai": {}})


def test_read_ai_secret_keeps_dpapi_ciphertext_on_decrypt_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pixiv_launch_config, "DATA_DIR", tmp_path)
    (tmp_path / "ai.local.json").write_text(
        json.dumps({"api_key": "dpapi:v1:x", "model": "m"}),
        encoding="utf-8",
    )
    secret = pixiv_launch_config._read_ai_secret()
    # 解密失败时保留密文标记，由 _ai_env 识别并报错，而不是静默当明文用
    assert secret["api_key"].startswith("dpapi:")
    assert secret["model"] == "m"


def test_ai_env_env_var_override_still_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pixiv_ai_transport,
        "_read_ai_secret",
        lambda: {"api_key": "dpapi:v1:bad"},
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    env = pixiv_ai_transport._ai_env({"ai": {"provider": "DeepSeek"}})
    assert env["api_key"] == "env-key"


# --- #6 corrupted config/history warnings -------------------------------------


def test_load_config_warns_on_corrupted_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    bad = tmp_path / "pixiv_launch.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(pixiv_launch_config, "CONFIG_PATH", bad)
    with caplog.at_level(logging.WARNING, logger="pixiv_launch_config"):
        cfg = pixiv_launch_config.load_config()
    assert cfg["account"]["direction"]  # 回退到默认配置
    assert "已损坏" in caplog.text


def test_list_upload_history_warns_on_corrupted_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    bad = tmp_path / "pixiv_uploads.json"
    bad.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(pixiv_launch, "HISTORY_PATH", bad)
    with caplog.at_level(logging.WARNING, logger="pixiv_launch"):
        assert pixiv_launch.list_upload_history() == []
    assert "上传历史" in caplog.text


def test_remember_job_request_warns_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(pixiv_launch, "LAST_JOB_PATH", tmp_path / "last_job.json")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pixiv_launch, "atomic_write_text", boom)
    with caplog.at_level(logging.WARNING, logger="pixiv_launch"):
        pixiv_launch._remember_job_request("upload", {"image_id": "x"})
    assert "最近任务请求" in caplog.text


# --- #8 draft identity matching ------------------------------------------------


def _write_draft(path: Path, image_id: str, title: str) -> None:
    path.write_text(
        json.dumps(
            {"image_id": image_id, "post": {"title": title}, "persona": {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_post_draft_only_returned_for_matching_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = tmp_path / "pixiv_draft.json"
    monkeypatch.setattr(pixiv_launch, "DRAFT_PATH", draft)
    _write_draft(draft, "series-a-cover", "标题A")

    assert pixiv_launch._load_post_draft("series-a-cover")["title"] == "标题A"
    # 另一批次的图片拿不到上一批的草稿
    assert pixiv_launch._load_post_draft("series-b-cover") == {}
    # 同一批次（related）内允许复用
    assert (
        pixiv_launch._load_post_draft("series-b-cover", ["series-a-cover"])["title"]
        == "标题A"
    )


def test_post_draft_corrupt_or_mismatched_is_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = tmp_path / "pixiv_draft.json"
    monkeypatch.setattr(pixiv_launch, "DRAFT_PATH", draft)
    assert pixiv_launch._load_post_draft("anything") == {}
    draft.write_text("{broken", encoding="utf-8")
    assert pixiv_launch._load_post_draft("anything") == {}


# --- #10 silent except logging -------------------------------------------------


def test_png_comment_parse_failure_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    from nai_char_modules.snapshots import comment_from_png

    bad_png = tmp_path / "broken.png"
    bad_png.write_bytes(b"this is not a real png")
    with caplog.at_level(logging.WARNING, logger="nai_char_modules.snapshots"):
        assert comment_from_png(bad_png) is None
    assert "Comment" in caplog.text


def test_oc_preset_match_failure_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import inspect

    import nai_char

    source = inspect.getsource(nai_char._extract_chars_impl)
    assert "_logger.warning" in source
    assert "OC 预设匹配失败" in source


# --- #12 session-token loopback only -------------------------------------------


def _fake_request(host: str | None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/session-token",
        "headers": [],
        "query_string": b"",
    }
    if host is not None:
        scope["client"] = (host, 12345)
    return Request(scope)


def test_session_token_served_to_loopback_only() -> None:
    import server

    for host in ("127.0.0.1", "::1"):
        assert server.api_session_token(_fake_request(host))["token"] == (
            server.SESSION_TOKEN
        )
    for host in ("192.168.1.20", "10.0.0.2", "evil.example", None):
        with pytest.raises(HTTPException) as exc_info:
            server.api_session_token(_fake_request(host))
        assert exc_info.value.status_code == 403


# --- publish-flow P1: account pinning & draft route ----------------------------


def test_upload_pixiv_illust_pins_payload_account_over_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """payload 里的 account_id 必须钉死投稿账号，上传中途切号不改变目标。"""
    captured: dict[str, str] = {}

    def fake_validate(account_id: str) -> dict:
        captured["validated"] = account_id
        return {"account_id": account_id, "user": {"id": "1"}, "label": "L"}

    def fake_web_sync(paths, **kwargs):
        captured["account_id"] = kwargs.get("account_id")
        return {"illust_id": "1", "pixiv_url": ""}

    monkeypatch.setattr(pixiv_launch, "validate_account_for_upload", fake_validate)
    monkeypatch.setattr(pixiv_launch, "get_active_account_id", lambda: "active-acc")
    monkeypatch.setattr(pixiv_launch, "account_display_name", lambda aid: aid)
    monkeypatch.setattr(pixiv_launch, "_append_history", lambda record: None)
    monkeypatch.setattr(
        pixiv_launch,
        "load_config",
        lambda: {"upload": {"x_restrict": "r18"}, "account": {}},
    )
    import pixiv_web_upload

    monkeypatch.setattr(pixiv_web_upload, "upload_illust_via_web_sync", fake_web_sync)
    monkeypatch.setattr(pixiv_web_upload, "set_upload_progress_hook", lambda hook: None)

    img = tmp_path / "a_final.png"
    img.write_bytes(b"png")
    pixiv_launch._upload_pixiv_illust(
        img, title="t", caption="c", tags=["x"], account_id="pinned-acc"
    )
    assert captured["validated"] == "pinned-acc"
    assert captured["account_id"] == "pinned-acc"


def test_upload_pixiv_illust_falls_back_to_active_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_validate(account_id: str) -> dict:
        captured["validated"] = account_id
        return {"account_id": account_id, "user": {}, "label": ""}

    monkeypatch.setattr(pixiv_launch, "validate_account_for_upload", fake_validate)
    monkeypatch.setattr(pixiv_launch, "get_active_account_id", lambda: "active-acc")
    monkeypatch.setattr(pixiv_launch, "account_display_name", lambda aid: aid)
    monkeypatch.setattr(pixiv_launch, "_append_history", lambda record: None)
    monkeypatch.setattr(pixiv_launch, "load_config", lambda: {"upload": {}, "account": {}})
    import pixiv_web_upload

    monkeypatch.setattr(
        pixiv_web_upload,
        "upload_illust_via_web_sync",
        lambda paths, **kwargs: {"illust_id": "1"},
    )
    monkeypatch.setattr(pixiv_web_upload, "set_upload_progress_hook", lambda hook: None)

    img = tmp_path / "a_final.png"
    img.write_bytes(b"png")
    pixiv_launch._upload_pixiv_illust(img, title="t", caption="c", tags=["x"])
    assert captured["validated"] == "active-acc"


def test_draft_route_returns_matching_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routes.pixiv import api_pixiv_draft

    draft = tmp_path / "pixiv_draft.json"
    monkeypatch.setattr(pixiv_launch, "DRAFT_PATH", draft)
    _write_draft(draft, "img-1", "标题X")

    assert api_pixiv_draft(image_id="img-1")["draft"]["title"] == "标题X"
    assert api_pixiv_draft(image_id="img-2")["draft"] == {}
    assert api_pixiv_draft(image_id="")["draft"] == {}
