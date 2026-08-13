from __future__ import annotations

import logging
from typing import Any
import time

from db_compression import decompress_if_needed

_logger = logging.getLogger(__name__)


def check_schema_version(self) -> None:
    """Record the schema version and warn when the DB is newer than the code."""

    from datetime import datetime, timezone

    from db import SCHEMA_VERSION

    self.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = self.conn.execute("PRAGMA user_version").fetchone()
    existing = int(row[0]) if row else 0
    if existing > SCHEMA_VERSION:
        _logger.warning(
            "Database %s has schema user_version=%d, newer than this code "
            "supports (%d); downgrading the app against this database is "
            "not supported.",
            self.db_path,
            existing,
            SCHEMA_VERSION,
        )
        return
    if existing < SCHEMA_VERSION:
        applied_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for version in range(max(existing, 0) + 1, SCHEMA_VERSION + 1):
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, ?)",
                (version, applied_at),
            )
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _list_text_changed(existing: Any, item: dict[str, Any]) -> bool:
    """True when a list upsert changed searchable text on a detail-complete row."""

    if not existing:
        return False
    return (
        str(existing["title"] or "") != str(item.get("title") or "")
        or str(existing["caption"] or "") != str(item.get("caption") or "")
        or str(existing["tags"] or "") != str(item.get("tags") or "")
    )


def _unique_ids(work_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(int(work_id) for work_id in work_ids))


def _id_chunks(work_ids: list[int], size: int = 400):
    for offset in range(0, len(work_ids), size):
        yield work_ids[offset : offset + size]


def sync_work_fts(self, work_id: int) -> None:
    row = self.conn.execute(
        "SELECT title, caption, tags, ai_type FROM works WHERE id = ?",
        (work_id,),
    ).fetchone()
    if not row:
        return
    self.conn.execute("DELETE FROM works_fts WHERE work_id = ?", (work_id,))
    self.conn.execute(
        """
        INSERT INTO works_fts(work_id, title, caption, tags, ai_type)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            work_id,
            row["title"] or "",
            row["caption"] or "",
            row["tags"] or "",
            row["ai_type"] or "",
        ),
    )


def sync_work_fts_batch(self, work_ids: list[int]) -> None:
    """Refresh the work FTS rows with one delete/select/insert set per chunk."""

    ids = _unique_ids(work_ids)
    for chunk in _id_chunks(ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = self.conn.execute(
            f"""
            SELECT id, title, caption, tags, ai_type
            FROM works
            WHERE id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        self.conn.execute(
            f"DELETE FROM works_fts WHERE work_id IN ({placeholders})",
            chunk,
        )
        self.conn.executemany(
            """
            INSERT INTO works_fts(work_id, title, caption, tags, ai_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    int(row["id"]),
                    row["title"] or "",
                    row["caption"] or "",
                    row["tags"] or "",
                    row["ai_type"] or "",
                )
                for row in rows
            ],
        )


def sync_prompt_fts_batch(self, work_ids: list[int]) -> None:
    """Refresh prompt indexes once per batch while preserving page order."""

    ids = _unique_ids(work_ids)
    for chunk in _id_chunks(ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = self.conn.execute(
            f"""
            SELECT work_id, prompt_text, ai_json
            FROM work_images
            WHERE work_id IN ({placeholders})
            ORDER BY work_id, page_index
            """,
            chunk,
        ).fetchall()
        self.conn.execute(
            f"DELETE FROM prompt_fts WHERE work_id IN ({placeholders})",
            chunk,
        )
        self.conn.execute(
            f"DELETE FROM prompt_work_fts WHERE work_id IN ({placeholders})",
            chunk,
        )

        prompt_rows: list[tuple[int, str]] = []
        prompts_by_work: dict[int, list[str]] = {}
        for row in rows:
            prompt = (
                row["prompt_text"]
                or decompress_if_needed(row["ai_json"])
                or ""
            ).strip()
            if not prompt:
                continue
            work_id = int(row["work_id"])
            prompt_rows.append((work_id, prompt))
            prompts_by_work.setdefault(work_id, []).append(prompt)

        self.conn.executemany(
            "INSERT INTO prompt_fts(work_id, prompt_text) VALUES (?, ?)",
            prompt_rows,
        )
        self.conn.executemany(
            "INSERT INTO prompt_work_fts(work_id, prompt_text) VALUES (?, ?)",
            [
                (work_id, "\n".join(prompts))
                for work_id, prompts in prompts_by_work.items()
            ],
        )


def configure_crawler_wal(
    self,
    *,
    autocheckpoint_pages: int = 4096,
    journal_limit_bytes: int = 64 * 1024 * 1024,
) -> dict[str, int]:
    """Apply the site crawler's bounded, throughput-oriented WAL policy."""

    pages = max(256, min(int(autocheckpoint_pages), 16384))
    limit = max(16 * 1024 * 1024, min(int(journal_limit_bytes), 512 * 1024 * 1024))

    def action() -> dict[str, int]:
        auto_row = self.conn.execute(
            f"PRAGMA wal_autocheckpoint={pages}"
        ).fetchone()
        limit_row = self.conn.execute(
            f"PRAGMA journal_size_limit={limit}"
        ).fetchone()
        return {
            "autocheckpoint_pages": int(auto_row[0]),
            "journal_limit_bytes": int(limit_row[0]),
        }

    return self._run(action)


def count_scope_works(self, local_scope: str) -> int:
    clause, params = self._local_dataset_clause(local_scope)
    if not clause:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM works").fetchone()
        return int(row["c"])
    row = self.conn.execute(
        f"SELECT COUNT(*) AS c FROM works WHERE {clause}", params
    ).fetchone()
    return int(row["c"])


def cached_scope_total(self, local_scope: str) -> int:
    from db import _SCOPE_TOTAL_CACHE, _SCOPE_TOTAL_TTL_SEC

    key = (local_scope or "all").strip().lower()
    now = time.time()
    cached = _SCOPE_TOTAL_CACHE.get(key)
    if cached and now - cached[1] < _SCOPE_TOTAL_TTL_SEC:
        return cached[0]
    total = self.count_scope_works(local_scope)
    _SCOPE_TOTAL_CACHE[key] = (total, now)
    self.set_state(f"search_total:{key}", str(total))
    return total


def pending_preview_work_ids(
    self,
    limit: int = 100,
    *,
    max_attempts: int = 6,
    arknights_only: bool = False,
) -> list[int]:
    from db import ARK_MATCH_SQL

    ark_sql = f" AND ({ARK_MATCH_SQL})" if arknights_only else ""
    rows = self.conn.execute(
        f"""
        SELECT id FROM works
        WHERE list_json IS NOT NULL
          AND detail_json IS NOT NULL
          AND preview_downloaded = 0
          AND COALESCE(preview_attempts, 0) < ?{ark_sql}
        ORDER BY COALESCE(preview_attempts, 0) ASC,
                 COALESCE(total_bookmarks, 0) DESC,
                 id ASC
        LIMIT ?
        """,
        (max_attempts, limit),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def bump_preview_attempts(self, work_id: int) -> int:
    def action():
        self.conn.execute(
            "UPDATE works SET preview_attempts = COALESCE(preview_attempts, 0) + 1 "
            "WHERE id = ?",
            (work_id,),
        )
        row = self.conn.execute(
            "SELECT preview_attempts FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        self.conn.commit()
        return int(row["preview_attempts"] or 0)

    return self._run(action)


def reset_preview_attempts(self, work_id: int) -> None:
    def action():
        self.conn.execute(
            "UPDATE works SET preview_attempts = 0 WHERE id = ?", (work_id,)
        )
        self.conn.commit()

    self._run(action)


def pending_images_for_work(self, work_id: int, *, cover_only: bool = False):
    # cover_only 也返回同作全部未下载页（按页序）：封面 404 时调用方需要
    # 回退到同作其他页；调用方在首个成功页后 break，不会多抓。
    return self.conn.execute(
        "SELECT page_index, image_type, author_id, file_name, image_path "
        "FROM work_images WHERE work_id = ? AND downloaded = 0"
        " ORDER BY page_index",
        (work_id,),
    ).fetchall()


def requeue_exhausted_previews(
    self,
    *,
    max_attempts: int,
    limit: int = 1000,
) -> list[int]:
    threshold = max(1, int(max_attempts))
    batch_limit = max(1, min(int(limit), 5000))

    def action() -> list[int]:
        rows = self.conn.execute(
            """
            SELECT id
            FROM works
            WHERE preview_downloaded = 0
              AND preview_attempts >= ?
            ORDER BY total_bookmarks DESC, id
            LIMIT ?
            """,
            (threshold, batch_limit),
        ).fetchall()
        work_ids = [int(row["id"]) for row in rows]
        if work_ids:
            placeholders = ",".join("?" for _ in work_ids)
            self.conn.execute(
                f"UPDATE works SET preview_attempts = 0 "
                f"WHERE id IN ({placeholders})",
                work_ids,
            )
            self.conn.commit()
        return work_ids

    return self._run(action)


def upsert_list_items_batch(
    self,
    items: list[dict[str, Any]],
    crawled_at: str,
) -> dict[str, int]:
    """Persist one search page atomically and refresh its FTS rows once."""

    if not items:
        return {"kept": 0, "already_complete": 0, "changed": 0}

    def action() -> dict[str, int]:
        item_ids = _unique_ids([int(item["id"]) for item in items])
        complete_ids: set[int] = set()
        for chunk in _id_chunks(item_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"""
                SELECT id
                FROM works
                WHERE detail_json IS NOT NULL
                  AND id IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            complete_ids.update(int(row["id"]) for row in rows)

        changed = 0
        fts_ids: list[int] = []
        try:
            self.conn.execute("BEGIN")
            for item in items:
                did_change, needs_fts = self._upsert_list_item_impl(
                    item,
                    crawled_at,
                    sync_fts=False,
                    invalidate_cache=False,
                )
                if did_change:
                    changed += 1
                if needs_fts:
                    fts_ids.append(int(item["id"]))
            self._sync_work_fts_batch(fts_ids)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        from db import _invalidate_scope_total_cache

        _invalidate_scope_total_cache()
        return {
            "kept": len(items),
            "already_complete": len(complete_ids),
            "changed": changed,
        }

    return self._run(action)


def save_detail(
    self,
    work_id: int,
    detail: dict[str, Any],
    preview_path: str | None,
    preview_downloaded: bool,
    crawled_at: str,
) -> None:
    def action() -> None:
        self._save_detail_impl(
            work_id,
            detail,
            preview_path,
            preview_downloaded,
            crawled_at,
            commit=True,
        )

    self._run(action)


def save_details_batch(
    self,
    details: list[tuple[int, dict[str, Any], str | None, bool, str]],
) -> int:
    """Persist one fetched detail batch atomically with a single commit."""

    if not details:
        return 0

    def action() -> int:
        saved = 0
        saved_ids: list[int] = []
        try:
            self.conn.execute("BEGIN")
            for (
                work_id,
                detail,
                preview_path,
                preview_downloaded,
                crawled_at,
            ) in details:
                inserted = self._save_detail_impl(
                    work_id,
                    detail,
                    preview_path,
                    preview_downloaded,
                    crawled_at,
                    commit=False,
                    sync_fts=False,
                )
                if inserted:
                    saved += 1
                    saved_ids.append(work_id)
            self._sync_work_fts_batch(saved_ids)
            self._sync_prompt_fts_batch(saved_ids)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        # Imported lazily to avoid a module cycle while db.py attaches this
        # repository operation to Database.
        from db import _invalidate_scope_total_cache

        _invalidate_scope_total_cache()
        return saved

    return self._run(action)
