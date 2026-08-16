"""Thin Library write boundary. Providers must not INSERT into works/work_images."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from db_compression import compress_text
from gallery_catalog import ensure_gallery_dirs, get_db
from remote_asset import RemoteAssetRef
from work_refs import WorkRef


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _account_user_id(account_key: str) -> int:
    import hashlib

    raw = "||".join(("account", str(account_key)))
    digest = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    return (int(digest[:13], 16) or 1) % 2_000_000_000 or 1


@dataclass
class MaterializePage:
    relative_path: str
    page_index: int = 0
    source_page_index: int | None = None
    source_url: str = ""
    source_sha256: str = ""
    file_name: str = ""
    prompt_text: str = ""
    model: str = ""
    ai_json: str = ""


@dataclass
class MaterializeResult:
    ok: bool
    gallery_id: str
    work_id: int
    work_ref: WorkRef
    remote_ref: RemoteAssetRef | None = None
    pages: list[int] = field(default_factory=list)


def materialize_asset(
    gallery_id: str,
    *,
    work_id: int,
    title: str,
    remote_ref: RemoteAssetRef | None = None,
    pages: list[MaterializePage] | None = None,
    caption: str = "",
    tags: str = "",
    account_key: str = "",
    account_label: str = "",
    category: str = "",
    rating: str = "",
    source: str = "",
    extra: dict[str, Any] | None = None,
    commit: bool = True,
    db: Any = None,
    acquired_at: str = "",
) -> MaterializeResult:
    """Persist a user-selected asset into the local library.

    This is the only additive import path for QQ / drop / Codex / synthetic.
    Pixiv intake still uses its receipt-aware writer until that adapter is moved.
    """

    ensure_gallery_dirs(gallery_id)
    db = db or get_db(gallery_id)
    crawled_at = str(acquired_at or "") or _now_iso()
    user_id = _account_user_id(account_key) if account_key else 0
    page_rows = list(pages or [])
    if not page_rows:
        raise ValueError("materialize_asset requires at least one page")
    preview_rel = page_rows[0].relative_path.replace("\\", "/")
    item: dict[str, Any] = {
        "id": work_id,
        "userId": user_id or None,
        "title": title,
        "caption": caption,
        "tags": tags,
        "AI_type": "NAI",
        "ai_type": "NAI",
        "create_date": crawled_at,
        "image_count": len(page_rows),
        "total_view": 0,
        "total_bookmarks": 0,
        "account_key": account_key,
        "account_label": account_label or account_key,
        "category": category,
        "rating": rating,
        "source": source,
        "gallery": gallery_id,
    }
    if remote_ref is not None:
        item["remote_ref"] = remote_ref.to_dict()
    if extra:
        item.update(extra)

    detail = {
        "work": item,
        "images": [
            {
                "page_index": page.page_index,
                "source_page_index": page.source_page_index,
                "source_url": page.source_url,
                "source_sha256": page.source_sha256,
                "image_type": "NAI",
                "author_id": user_id or None,
                "file_name": page.file_name or Path(page.relative_path).name,
                "image_path": page.relative_path.replace("\\", "/"),
                "local_path": page.relative_path.replace("\\", "/"),
                "model": page.model,
                "ai_json": page.ai_json,
                "prompt_text": page.prompt_text,
            }
            for page in page_rows
        ],
        "lineage": {
            "provider": remote_ref.provider_id if remote_ref else "",
            "remote_id": remote_ref.remote_id if remote_ref else "",
            "source_url": remote_ref.source_url if remote_ref else "",
            "acquired_at": crawled_at,
        },
    }

    def action() -> None:
        _write_library_rows(
            db,
            work_id=work_id,
            item=item,
            detail=detail,
            pages=page_rows,
            preview_rel=preview_rel,
            crawled_at=crawled_at,
            commit=commit,
        )

    db._run(action)
    return MaterializeResult(
        ok=True,
        gallery_id=gallery_id,
        work_id=int(work_id),
        work_ref=WorkRef(gallery_id=str(gallery_id), work_id=str(work_id)),
        remote_ref=remote_ref,
        pages=[int(page.page_index) for page in page_rows],
    )


def _write_library_rows(
    db: Any,
    *,
    work_id: int,
    item: dict[str, Any],
    detail: dict[str, Any],
    pages: list[MaterializePage],
    preview_rel: str,
    crawled_at: str,
    commit: bool,
) -> None:
    existing = db.conn.execute(
        "SELECT create_date FROM works WHERE id = ?",
        (work_id,),
    ).fetchone()
    if existing and existing["create_date"]:
        item["create_date"] = existing["create_date"]
        work = detail.get("work")
        if isinstance(work, dict):
            work["create_date"] = existing["create_date"]
    list_json = json.dumps(item, ensure_ascii=False)
    detail_json = compress_text(json.dumps(detail, ensure_ascii=False))
    rel = preview_rel.replace("\\", "/")
    db.conn.execute(
        """
        INSERT INTO works(
            id, user_id, title, caption, tags, ai_type, create_date,
            image_count, total_view, total_bookmarks, list_json, detail_json,
            preview_path, preview_downloaded, crawled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(id) DO UPDATE SET
            user_id = excluded.user_id,
            title = excluded.title,
            caption = excluded.caption,
            tags = excluded.tags,
            ai_type = excluded.ai_type,
            create_date = excluded.create_date,
            image_count = MAX(works.image_count, excluded.image_count),
            total_view = MAX(works.total_view, excluded.total_view),
            total_bookmarks = MAX(works.total_bookmarks, excluded.total_bookmarks),
            list_json = excluded.list_json,
            detail_json = excluded.detail_json,
            preview_path = excluded.preview_path,
            preview_downloaded = 1,
            crawled_at = excluded.crawled_at
        """,
        (
            work_id,
            item.get("userId"),
            item.get("title"),
            item.get("caption"),
            item.get("tags"),
            "NAI",
            item.get("create_date"),
            max(1, len(pages)),
            0,
            0,
            list_json,
            detail_json,
            rel,
            crawled_at,
        ),
    )
    for page in pages:
        page_rel = page.relative_path.replace("\\", "/")
        db.conn.execute(
            """
            INSERT INTO work_images(
                id, work_id, author_id, image_type, file_name, image_path,
                model, ai_json, prompt_text, page_index, source_page_index,
                source_url, source_sha256, local_path, downloaded
            ) VALUES (?, ?, ?, 'NAI', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(work_id, page_index) DO UPDATE SET
                file_name = excluded.file_name,
                image_path = excluded.image_path,
                model = excluded.model,
                ai_json = excluded.ai_json,
                prompt_text = excluded.prompt_text,
                source_page_index = excluded.source_page_index,
                source_url = excluded.source_url,
                source_sha256 = excluded.source_sha256,
                local_path = excluded.local_path,
                downloaded = 1
            """,
            (
                work_id if page.page_index == 0 else None,
                work_id,
                item.get("userId"),
                page.file_name or Path(page_rel).name,
                page_rel,
                page.model or None,
                compress_text(page.ai_json) if page.ai_json else None,
                page.prompt_text,
                int(page.page_index),
                page.source_page_index,
                page.source_url or None,
                page.source_sha256 or None,
                page_rel,
            ),
        )
    db._sync_work_fts(work_id)
    db._sync_prompt_fts(work_id)
    if commit:
        db.conn.commit()


def discard_unreferenced_file(
    gallery_id: str,
    relative_path: str,
    dest: Path,
    *,
    db: Any = None,
) -> bool:
    """Delete a newly written file only when no library row references it."""

    rel = relative_path.replace("\\", "/")
    try:
        database = db or get_db(gallery_id)
        row = database.conn.execute(
            "SELECT 1 FROM work_images WHERE local_path = ? LIMIT 1",
            (rel,),
        ).fetchone()
        if row:
            return False
    except Exception:
        pass
    dest.unlink(missing_ok=True)
    return True
