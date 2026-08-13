# -*- coding: utf-8 -*-
"""Compliance and provenance endpoints for Pixiv NAI Gallery.

The module keeps responsibility notices, source provenance, author/work
blocklists and rightsholder cleanup local to the desktop application. It does
not add telemetry or remove any crawler, generation or publishing capability.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from db import _invalidate_scope_total_cache
from paths import canonical_path, path_is_within, relative_to_canonical
from server_shared import DATA_DIR, DB, ROOT

router = APIRouter(prefix="/api/compliance", tags=["compliance"])
page_router = APIRouter()


@page_router.get("/compliance")
def compliance_page() -> FileResponse:
    return FileResponse(
        ROOT / "web" / "compliance.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


NOTICE_VERSION = "1.1"
_ALLOWED_REMOVED_STATUSES = {"removed", "source_gone"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _db():
    return DB


def _run(fn):
    return _db()._run(fn)


def _asset_roots() -> tuple[Path, ...]:
    """Directories from which compliance cleanup is allowed to move files."""
    return tuple(
        canonical_path(path)
        for path in (
            DATA_DIR / "images",
            DATA_DIR / "galleries",
            DATA_DIR / "cache",
            DATA_DIR / ".cache",
        )
    )


def _is_under(path: Path, root: Path) -> bool:
    return path_is_within(path, root)


def _resolve_local_asset(raw_path: object) -> Path | None:
    """Resolve a stored asset path without permitting traversal outside data roots."""
    text = str(raw_path or "").strip()
    if not text:
        return None
    source = Path(text)
    roots = _asset_roots()
    candidates: list[Path]
    if source.is_absolute():
        candidates = [canonical_path(source)]
    else:
        candidates = [canonical_path(DATA_DIR / source)]
        candidates.extend(canonical_path(root / source) for root in roots)

    safe = [
        candidate
        for candidate in candidates
        if any(_is_under(candidate, root) for root in roots)
    ]
    if not safe:
        return None
    return next((candidate for candidate in safe if candidate.exists()), safe[0])


def _move_to_author_trash(path: Path, author_id: int) -> Path:
    """Move an asset to a recoverable local trash area."""
    data_root = canonical_path(DATA_DIR)
    try:
        relative = Path(relative_to_canonical(path, data_root))
    except ValueError:
        relative = Path(path.name)
    destination = DATA_DIR / "_trash" / f"author_{author_id}" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination = destination.with_name(
            f"{destination.stem}-{uuid.uuid4().hex[:8]}{destination.suffix}"
        )
    shutil.move(str(path), str(destination))
    return destination


def _table_exists(db, table_name: str) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (table_name,),
    ).fetchone()
    return row is not None


def _delete_work_rows(db, table_name: str, work_ids: list[int]) -> None:
    """Delete optional index rows without breaking a fresh/legacy database."""
    if not work_ids or not _table_exists(db, table_name):
        return
    placeholders = ",".join("?" * len(work_ids))
    db.conn.execute(
        f"DELETE FROM {table_name} WHERE work_id IN ({placeholders})",
        work_ids,
    )


# ---------------------------------------------------------------------------
# Author blacklist
# ---------------------------------------------------------------------------
@router.get("/blacklist")
def list_blacklist() -> dict:
    rows = _db().conn.execute(
        "SELECT author_id, author_name, reason, scope, created_at "
        "FROM author_blacklist ORDER BY created_at DESC"
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        local_works = _db().conn.execute(
            "SELECT COUNT(*) AS total FROM works WHERE user_id = ?",
            (item["author_id"],),
        ).fetchone()
        item["local_works"] = int(local_works["total"] if local_works else 0)
        item["cleanup_required"] = (
            item["scope"] in ("delete", "both") and item["local_works"] > 0
        )
        items.append(item)
    return {"ok": True, "items": items}


@router.post("/blacklist")
def add_blacklist(payload: dict = Body(default_factory=dict)) -> dict:
    author_id = int(payload.get("author_id") or 0)
    author_name = str(payload.get("author_name") or "").strip()
    if author_id <= 0 or not author_name:
        raise HTTPException(status_code=400, detail="author_id 与 author_name 必填")
    scope = str(payload.get("scope") or "both")
    if scope not in ("crawl", "delete", "both"):
        raise HTTPException(status_code=400, detail="scope 必须为 crawl/delete/both")

    def action():
        db = _db()
        db.conn.execute(
            "INSERT INTO author_blacklist(author_id, author_name, reason, scope, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(author_id) DO UPDATE SET "
            "author_name=excluded.author_name, reason=excluded.reason, scope=excluded.scope",
            (author_id, author_name, str(payload.get("reason") or ""), scope, _now()),
        )
        db.conn.commit()
        return db.conn.execute(
            "SELECT COUNT(*) AS total FROM works WHERE user_id = ?", (author_id,)
        ).fetchone()

    local_works = _run(action)
    return {
        "ok": True,
        "cleanup_required": scope in ("delete", "both")
        and bool(local_works and local_works["total"]),
    }


@router.delete("/blacklist/{author_id}")
def remove_blacklist(author_id: int) -> dict:
    _run(lambda: (
        _db().conn.execute("DELETE FROM author_blacklist WHERE author_id = ?", (author_id,)),
        _db().conn.commit(),
    ))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Manual blocked-collection list (per-work)
# ---------------------------------------------------------------------------
@router.get("/blocked")
def list_blocked() -> dict:
    rows = _db().conn.execute(
        "SELECT work_id, source_url, reason, created_at "
        "FROM blocked_collection ORDER BY created_at DESC"
    ).fetchall()
    return {"ok": True, "items": [dict(row) for row in rows]}


@router.post("/blocked")
def add_blocked(payload: dict = Body(default_factory=dict)) -> dict:
    work_id = int(payload.get("work_id") or 0)
    if work_id <= 0:
        raise HTTPException(status_code=400, detail="work_id 必填")
    source_url = str(
        payload.get("source_url") or f"https://www.pixiv.net/artworks/{work_id}"
    )
    _run(lambda: (
        _db().conn.execute(
            "INSERT INTO blocked_collection(work_id, source_url, reason, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(work_id) DO UPDATE SET "
            "source_url=excluded.source_url, reason=excluded.reason",
            (work_id, source_url, str(payload.get("reason") or ""), _now()),
        ),
        _db().conn.commit(),
    ))
    return {"ok": True}


@router.delete("/blocked/{work_id}")
def remove_blocked(work_id: int) -> dict:
    _run(lambda: (
        _db().conn.execute("DELETE FROM blocked_collection WHERE work_id = ?", (work_id,)),
        _db().conn.commit(),
    ))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Source-work deletion sync
# ---------------------------------------------------------------------------
@router.post("/sync/removed")
def sync_removed_works(payload: dict = Body(default_factory=dict)) -> dict:
    """Mark local copies whose source work was deleted on the origin platform."""
    default_status = str(payload.get("status") or "removed")
    if default_status not in _ALLOWED_REMOVED_STATUSES:
        raise HTTPException(status_code=400, detail="status 必须为 removed/source_gone")
    raw_items = payload.get("items") or [
        {"work_id": work_id, "status": default_status}
        for work_id in (payload.get("work_ids") or [])
    ]
    if not raw_items:
        raise HTTPException(status_code=400, detail="work_ids/items 必填")

    def action():
        db = _db()
        updated = 0
        skipped = 0
        for item in raw_items:
            work_id = int(item.get("work_id") or 0)
            status = str(item.get("status") or default_status)
            if work_id <= 0 or status not in _ALLOWED_REMOVED_STATUSES:
                skipped += 1
                continue
            db.conn.execute(
                "INSERT INTO removed_works(work_id, source_url, removed_at, status) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(work_id) DO UPDATE SET "
                "status=excluded.status, removed_at=excluded.removed_at",
                (work_id, f"https://www.pixiv.net/artworks/{work_id}", _now(), status),
            )
            db.conn.execute(
                "UPDATE works SET removed_status = ? WHERE id = ?", (status, work_id)
            )
            updated += 1
        db.conn.commit()
        return updated, skipped

    updated, skipped = _run(action)
    return {"ok": True, "updated": updated, "skipped": skipped}


@router.post("/sync/check")
def check_source_status(payload: dict = Body(default_factory=dict)) -> dict:
    work_ids = [
        int(value)
        for value in (payload.get("work_ids") or [])
        if int(value or 0) > 0
    ]
    if not work_ids:
        return {"ok": True, "removed": []}
    placeholders = ",".join("?" * len(work_ids))
    rows = _db().conn.execute(
        f"SELECT id, removed_status, user_name, source_url FROM works "
        f"WHERE id IN ({placeholders})",
        work_ids,
    ).fetchall()
    return {
        "ok": True,
        "removed": [
            {
                "work_id": row["id"],
                "removed_status": row["removed_status"],
                "author": row["user_name"],
                "source_url": row["source_url"],
            }
            for row in rows
            if row["removed_status"]
        ],
    }


# ---------------------------------------------------------------------------
# Batch cleanup by author + attribution guard
# ---------------------------------------------------------------------------
@router.delete("/authors/{author_id}")
def delete_author_material(author_id: int) -> dict:
    """Move one author's local assets to trash and remove index records."""
    if author_id <= 0:
        raise HTTPException(status_code=400, detail="author_id 必须为正整数")
    db = _db()
    rows = _run(
        lambda: db.conn.execute(
            "SELECT w.id, w.preview_path, wi.local_path, wi.image_path "
            "FROM works AS w LEFT JOIN work_images AS wi ON wi.work_id = w.id "
            "WHERE w.user_id = ?",
            (author_id,),
        ).fetchall()
    )
    work_ids = sorted({int(row["id"]) for row in rows})

    moved: list[str] = []
    missing: list[str] = []
    failures: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        for field in ("preview_path", "local_path", "image_path"):
            raw = str(row[field] or "").strip()
            if not raw:
                continue
            resolved = _resolve_local_asset(raw)
            if resolved is None:
                failures.append({"path": raw, "error": "path_outside_allowed_roots"})
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            if not resolved.exists():
                missing.append(raw)
                continue
            try:
                destination = _move_to_author_trash(resolved, author_id)
                moved.append(str(destination))
            except OSError as exc:
                failures.append({"path": raw, "error": str(exc)})

    if work_ids:
        def action():
            for table_name in (
                "work_images",
                "works_fts",
                "prompt_fts",
                "prompt_work_fts",
                "pixiv_nai_receipts",
                "removed_works",
            ):
                _delete_work_rows(db, table_name, work_ids)
            placeholders = ",".join("?" * len(work_ids))
            db.conn.execute(f"DELETE FROM works WHERE id IN ({placeholders})", work_ids)
            db.conn.commit()

        _run(action)
    else:
        _run(lambda: db.conn.commit())
    _invalidate_scope_total_cache()
    return {
        "ok": not failures,
        "deleted_works": len(work_ids),
        "author_id": author_id,
        "files_moved": len(moved),
        "files_missing": len(missing),
        "file_failures": failures,
        "trash_paths": moved,
    }


@router.get("/authors/{author_id}")
def author_info(author_id: int) -> dict:
    row = _db().conn.execute(
        "SELECT user_id, user_name, source_url, COUNT(*) AS works FROM works "
        "WHERE user_id = ? GROUP BY user_id",
        (author_id,),
    ).fetchone()
    if not row:
        return {"ok": True, "author": None}
    return {
        "ok": True,
        "author": {
            "author_id": row["user_id"],
            "author_name": row["user_name"],
            "profile_url": f"https://www.pixiv.net/users/{row['user_id']}",
            "works": row["works"],
        },
    }


# ---------------------------------------------------------------------------
# No-AI / no-repost notices
# ---------------------------------------------------------------------------
@router.post("/notices")
def set_work_notice(payload: dict = Body(default_factory=dict)) -> dict:
    work_id = int(payload.get("work_id") or 0)
    notice = str(payload.get("notice") or "").strip()
    if work_id <= 0:
        raise HTTPException(status_code=400, detail="work_id 必填")
    _run(lambda: (
        _db().conn.execute(
            "UPDATE works SET no_ai_notice = ? WHERE id = ?", (notice or None, work_id)
        ),
        _db().conn.commit(),
    ))
    return {"ok": True}


@router.get("/notices/{work_id}")
def work_notice(work_id: int) -> dict:
    row = _db().conn.execute(
        "SELECT no_ai_notice FROM works WHERE id = ?", (work_id,)
    ).fetchone()
    return {
        "ok": True,
        "work_id": work_id,
        "notice": row["no_ai_notice"] if row else None,
    }


# ---------------------------------------------------------------------------
# Export manifest (provenance list)
# ---------------------------------------------------------------------------
@router.get("/export-manifest")
def export_manifest(work_ids: str = "") -> dict:
    ids = [int(value) for value in work_ids.split(",") if value.strip().isdigit()]
    if not ids:
        return {"ok": True, "items": []}
    placeholders = ",".join("?" * len(ids))
    rows = _db().conn.execute(
        f"SELECT id, user_id, user_name, source_url, removed_status, no_ai_notice, "
        f"title, crawled_at FROM works WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    items = []
    for row in rows:
        images = _db().conn.execute(
            "SELECT local_path, file_name FROM work_images "
            "WHERE work_id = ? AND downloaded = 1",
            (row["id"],),
        ).fetchall()
        items.append(
            {
                "work_id": row["id"],
                "title": row["title"],
                "author_id": row["user_id"],
                "author_name": row["user_name"],
                "author_url": (
                    f"https://www.pixiv.net/users/{row['user_id']}"
                    if row["user_id"]
                    else None
                ),
                "work_url": row["source_url"]
                or f"https://www.pixiv.net/artworks/{row['id']}",
                "removed_status": row["removed_status"],
                "no_ai_notice": row["no_ai_notice"],
                "crawled_at": row["crawled_at"],
                "local_files": [
                    image["local_path"] for image in images if image["local_path"]
                ],
            }
        )
    return {"ok": True, "items": items}


# ---------------------------------------------------------------------------
# First-run responsibility notice (local-only acknowledgment record)
# ---------------------------------------------------------------------------
@router.get("/notice/status")
def notice_status() -> dict:
    row = _db().conn.execute(
        "SELECT value FROM crawl_state WHERE key = 'responsibility_notice'"
    ).fetchone()
    accepted = None
    if row:
        try:
            accepted = json.loads(row["value"])
        except (TypeError, ValueError):
            accepted = None
    accepted_current = bool(
        isinstance(accepted, dict)
        and accepted.get("notice_version") == NOTICE_VERSION
    )
    return {
        "ok": True,
        "notice_version": NOTICE_VERSION,
        "accepted": accepted,
        "accepted_current": accepted_current,
        "required": not accepted_current,
    }


@router.post("/notice/accept")
def notice_accept(payload: dict = Body(default_factory=dict)) -> dict:
    record = {
        "notice_version": NOTICE_VERSION,
        "accepted_at": _now(),
        "app_version": str(payload.get("app_version") or ""),
        "nonce": uuid.uuid4().hex,
    }
    _run(lambda: (
        _db().conn.execute(
            "INSERT INTO crawl_state(key, value) VALUES ('responsibility_notice', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(record, ensure_ascii=False),),
        ),
        _db().conn.commit(),
    ))
    return {"ok": True, "record": record}
