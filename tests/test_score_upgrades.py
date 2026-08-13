"""Regression coverage for the post-v1.4.0 score upgrades.

Paid retry, empty-gallery crawler gate, frozen comments, required persist,
legacy secret deletion, data_dir routing, schema v2, and UI contracts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import char_swap_config
import crawler_control
import favorites
import gallery_guard
import nai_batch
import pixiv_accounts
from db import SCHEMA_VERSION, Database
from generation_jobs import GenerationJobManager, JobPersistenceError, partition_retry_targets
from paths import data_dir


ROOT = Path(__file__).resolve().parents[1]


def test_partition_blocks_unknown_and_missing_in_flight_indexes() -> None:
    retryable, blocked = partition_retry_targets(
        [{"work_id": 1}, {"work_id": 2}],
        [],
        status="unknown",
    )
    assert retryable == []
    assert blocked == [0, 1]


def test_partition_allows_never_run_indexes_on_completed_batch() -> None:
    retryable, blocked = partition_retry_targets(
        [{"work_id": 1}, {"work_id": 2}],
        [{"target_index": 0, "ok": False}],
        status="done",
    )
    assert retryable == [0, 1]
    assert blocked == []


def test_empty_gallery_blocks_new_crawler_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crawler_control, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        crawler_control,
        "pixiv_crawler_lock_path",
        lambda root=None: tmp_path / "pixiv_nai_crawler.lock",
    )
    monkeypatch.setattr(crawler_control, "_list_pixiv_crawler_pids_uncached", lambda: [])
    monkeypatch.setattr(
        crawler_control,
        "_spawn_detached_ps",
        lambda **kwargs: pytest.fail("must not spawn"),
    )
    monkeypatch.setattr(
        "gallery_snapshot.maintenance_mode_active", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(gallery_guard, "main_gallery_empty", lambda db=None: True)
    with pytest.raises(ValueError, match="主图库为空"):
        crawler_control.start_pixiv_crawler(watch=False)


def test_main_gallery_empty_is_fail_closed() -> None:
    class Boom:
        def count_works(self) -> int:
            raise RuntimeError("locked")

    assert gallery_guard.main_gallery_empty(Boom()) is True


def test_paid_start_batch_freezes_patched_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = GenerationJobManager(state_path=tmp_path / "generation_jobs.json")
    monkeypatch.setattr(nai_batch, "_JOB_MANAGER", manager)
    monkeypatch.setattr(nai_batch, "generation_concurrency_for_batch", lambda *a, **k: 1)
    monkeypatch.setattr(nai_batch, "_launch_job", lambda job: None)
    comment = {"v4_prompt": {"caption": {"base_caption": "1girl"}}}
    result = nai_batch.start_batch(
        [{"work_id": 11, "page_index": 0, "patched_comment": comment}],
        {},
        force_free=True,
        generate=True,
        preview_only=False,
    )
    assert result["ok"]
    target = manager.get_job(result["task_id"]).state["_request"]["targets"][0]
    assert target["frozen_comment"] is True
    comment["v4_prompt"]["caption"]["base_caption"] = "mutated"
    assert target["patched_comment"]["v4_prompt"]["caption"]["base_caption"] == "1girl"


def test_paid_append_item_requires_persistence(tmp_path: Path) -> None:
    manager = GenerationJobManager(state_path=tmp_path / "generation_jobs.json")
    job = manager.start_job(total=1, generate=True, preview_only=False)

    def boom(*, required: bool = False) -> bool:
        if required:
            raise JobPersistenceError("disk full")
        return True

    manager._persist_locked = boom  # type: ignore[method-assign]
    with pytest.raises(JobPersistenceError):
        manager.append_item(job, {"target_index": 0, "ok": True}, count_done=True)


def test_legacy_pixiv_secret_is_deleted_after_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pixiv_accounts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        pixiv_accounts, "ACCOUNTS_PATH", tmp_path / "pixiv_accounts.local.json"
    )
    monkeypatch.setattr(
        pixiv_accounts,
        "ACCOUNTS_BACKUP_PATH",
        tmp_path / "pixiv_accounts.local.backup.json",
    )
    legacy = tmp_path / "pixiv.local.json"
    monkeypatch.setattr(pixiv_accounts, "LEGACY_SECRET_PATH", legacy)
    legacy.write_text(
        json.dumps({"refresh_token": "tok-legacy"}),
        encoding="utf-8",
    )
    pixiv_accounts._migrate_legacy_secret()
    assert not legacy.exists()
    assert pixiv_accounts.ACCOUNTS_PATH.exists()


def test_favorites_and_char_swap_honor_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("paths._DATA_DIR_CACHE", tmp_path)
    monkeypatch.setattr(favorites, "FAV_PATH", None)
    monkeypatch.setattr(char_swap_config, "CONFIG_PATH", None)
    assert favorites.favorite_path() == tmp_path / "favorites.json"
    assert char_swap_config._config_path() == tmp_path / "char_swap_config.json"


def test_schema_v2_records_migrations(tmp_path: Path) -> None:
    db = Database(tmp_path / "gallery.db")
    try:
        version = int(db.conn.execute("PRAGMA user_version").fetchone()[0])
        assert version == SCHEMA_VERSION == 2
        rows = list(
            db.conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        )
        assert [int(row[0]) for row in rows] == [1, 2]
    finally:
        db.close()


def test_progress_page_escapes_api_text() -> None:
    html = (ROOT / "web" / "progress.html").read_text(encoding="utf-8")
    assert "/assets/shared/escape.js" in html
    assert "esc(data.search_query" in html
    assert "esc(preset.label)" in html


def test_atlas_pages_include_site_nav_css() -> None:
    for name in ("nai-tags.html", "maintenance.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "/assets/shared/site-nav.css" in html


def test_char_swap_batch_sends_frozen_comment() -> None:
    source = (ROOT / "web" / "plugins" / "char-swap" / "batch.js").read_text(
        encoding="utf-8"
    )
    assert "t.frozen_comment = true" in source


def test_github_actions_workflow_runs_pytest() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "scan_sensitive.py" in workflow


def test_data_dir_helper_is_live() -> None:
    assert data_dir().name
