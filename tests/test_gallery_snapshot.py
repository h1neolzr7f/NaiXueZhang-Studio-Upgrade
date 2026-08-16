from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from gallery_snapshot import (
    BACKUP_NAME_RE,
    BACKUP_RETENTION,
    GallerySnapshotManager,
    prune_backups,
)


def test_gallery_snapshot_is_consistent_verifiable_and_excludes_credentials(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    images = data / "images"
    images.mkdir(parents=True)
    (images / "asset.bin").write_bytes(b"verified-asset")
    database = data / "aitag.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE works(id INTEGER PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO works(id, title) VALUES (1, 'work')")
        connection.commit()
    (data / "pixiv_accounts.local.json").write_text(
        json.dumps({"refresh_token": "must-not-leak"}), encoding="utf-8"
    )
    destination = tmp_path / "backups" / "gallery.zip"

    manager = GallerySnapshotManager(
        database, images, crawler_stopper=lambda: {"crawler_pixiv": []}
    )
    created = manager.create(destination)
    verified = manager.verify(destination)

    assert created["asset_files"] == 1
    assert verified["ok"] is True
    assert verified["database_integrity"] == "ok"
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert "gallery.db" in names
        assert "images/asset.bin" in names
        assert all("account" not in name.lower() for name in names)
        assert b"must-not-leak" not in destination.read_bytes()


def test_gallery_snapshot_restore_requires_confirmation_and_restores_exact_state(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    images = data / "images"
    images.mkdir(parents=True)
    asset = images / "asset.bin"
    asset.write_bytes(b"before")
    database = data / "aitag.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE works(id INTEGER PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO works VALUES (1, 'before')")
        connection.commit()
    snapshot = tmp_path / "gallery.zip"
    manager = GallerySnapshotManager(
        database, images, crawler_stopper=lambda: {"crawler_pixiv": []}
    )
    manager.create(snapshot)

    asset.write_bytes(b"after")
    (images / "orphan.bin").write_bytes(b"orphan")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE works SET title='after' WHERE id=1")
        connection.commit()

    with pytest.raises(PermissionError):
        manager.restore(snapshot, confirm=False)
    restored = manager.restore(snapshot, confirm=True)

    assert restored["ok"] is True
    assert asset.read_bytes() == b"before"
    assert not (images / "orphan.bin").exists()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT title FROM works WHERE id=1").fetchone()[0] == "before"


def _fake_backup(backups: Path, timestamp: str, mtime: float) -> Path:
    path = backups / f"pixiv-nai-gallery-{timestamp}.zip"
    path.write_bytes(b"fake-zip")
    os.utime(path, (mtime, mtime))
    return path


def test_prune_backups_keeps_newest_and_only_tool_owned_names(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    total = BACKUP_RETENTION + 4
    created = []
    for index in range(total):
        # 合法时间戳命名，mtime 递增（越新越大）
        timestamp = f"202608{10 + index:02d}T120000Z"
        created.append(_fake_backup(backups, timestamp, mtime=1_000_000 + index))
    # 不符合命名 scheme 的文件必须原样保留
    foreign = backups / "pixiv-nai-gallery-notes.zip"
    foreign.write_bytes(b"user file")
    other = backups / "manual-backup.zip"
    other.write_bytes(b"user file")

    removed = prune_backups(backups)

    assert len(removed) == total - BACKUP_RETENTION
    remaining = sorted(path.name for path in backups.iterdir())
    assert len(remaining) == BACKUP_RETENTION + 2
    kept = [path for path in created if path.name in remaining]
    assert kept == created[-BACKUP_RETENTION:], "must keep the newest backups by mtime"
    assert foreign.name in remaining and other.name in remaining
    assert all(BACKUP_NAME_RE.match(path.name) for path in removed)


def test_current_schema_v2_snapshot_rollback_rehearsal(tmp_path: Path) -> None:
    from db import SCHEMA_VERSION, Database

    data = tmp_path / "data"
    images = data / "images"
    images.mkdir(parents=True)
    (images / "keep.bin").write_bytes(b"keep")
    db_path = data / "gallery.db"
    db = Database(db_path)
    try:
        version = int(db.conn.execute("PRAGMA user_version").fetchone()[0])
        assert version == SCHEMA_VERSION == 2
        db.conn.execute(
            "INSERT INTO works(id, title, caption, tags, ai_type) VALUES (1, 'before', '', 't', 'nai')"
        )
        db.conn.commit()
    finally:
        db.close()
    snapshot = tmp_path / "current-schema.zip"
    manager = GallerySnapshotManager(
        db_path, images, crawler_stopper=lambda: {"crawler_pixiv": []}
    )
    manager.create(snapshot)
    db = Database(db_path)
    try:
        db.conn.execute("UPDATE works SET title='after' WHERE id=1")
        db.conn.commit()
    finally:
        db.close()
    (images / "orphan.bin").write_bytes(b"orphan")
    restored = manager.restore(snapshot, confirm=True)
    assert restored["ok"] is True
    db = Database(db_path)
    try:
        assert int(db.conn.execute("PRAGMA user_version").fetchone()[0]) == 2
        assert db.conn.execute("SELECT title FROM works WHERE id=1").fetchone()[0] == "before"
    finally:
        db.close()
    assert (images / "keep.bin").read_bytes() == b"keep"
    assert not (images / "orphan.bin").exists()


def test_prune_backups_noop_when_within_retention(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    for index in range(3):
        _fake_backup(backups, f"2026081{index}T000000Z", mtime=1_000_000 + index)

    assert prune_backups(backups) == []
    assert len(list(backups.iterdir())) == 3
    assert prune_backups(tmp_path / "missing-dir") == []
