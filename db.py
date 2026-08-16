import json
import re
import sqlite3
import threading
import time
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

from db_compression import compress_text, decompress_if_needed
from search import build_prompt_fts_query, build_works_fts_query

_SCOPE_TOTAL_CACHE: dict[str, tuple[int, float]] = {}
_SCOPE_TOTAL_TTL_SEC = 300.0
SCHEMA_VERSION = 2


def _invalidate_scope_total_cache() -> None:
    _SCOPE_TOTAL_CACHE.clear()


def _close_sqlite_connections(
    primary: sqlite3.Connection,
    readers: set[sqlite3.Connection],
) -> None:
    """Close every connection owned by one Database instance."""

    for connection in tuple(readers):
        try:
            connection.close()
        except sqlite3.Error:
            pass
    readers.clear()
    try:
        primary.close()
    except sqlite3.Error:
        pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    title TEXT,
    caption TEXT,
    tags TEXT,
    ai_type TEXT,
    create_date TEXT,
    image_count INTEGER,
    total_view INTEGER,
    total_bookmarks INTEGER,
    list_json TEXT,
    detail_json TEXT,
    preview_path TEXT,
    preview_downloaded INTEGER DEFAULT 0,
    crawled_at TEXT
);

CREATE TABLE IF NOT EXISTS work_images (
    id INTEGER,
    work_id INTEGER NOT NULL,
    author_id INTEGER,
    image_type TEXT,
    file_name TEXT,
    image_path TEXT,
    model TEXT,
    ai_json TEXT,
    prompt_text TEXT,
    page_index INTEGER,
    source_page_index INTEGER,
    source_url TEXT,
    source_sha256 TEXT,
    local_path TEXT,
    downloaded INTEGER DEFAULT 0,
    PRIMARY KEY (work_id, page_index)
);

CREATE INDEX IF NOT EXISTS idx_works_ai_type ON works(ai_type);
CREATE INDEX IF NOT EXISTS idx_works_create_date ON works(create_date);
CREATE INDEX IF NOT EXISTS idx_work_images_work_id ON work_images(work_id);
CREATE INDEX IF NOT EXISTS idx_work_images_downloaded_true
    ON work_images(work_id)
    WHERE downloaded = 1;
CREATE INDEX IF NOT EXISTS idx_work_images_work_downloaded
    ON work_images(work_id, downloaded, page_index);
CREATE INDEX IF NOT EXISTS idx_works_detail_present
    ON works(id)
    WHERE detail_json IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_works_preview_downloaded
    ON works(preview_downloaded);
"""


COMPLIANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS author_blacklist (
    author_id INTEGER PRIMARY KEY,
    author_name TEXT NOT NULL,
    reason TEXT DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'crawl',  -- crawl | delete | both
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocked_collection (
    work_id INTEGER PRIMARY KEY,
    source_url TEXT NOT NULL,
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS removed_works (
    work_id INTEGER PRIMARY KEY,
    source_url TEXT NOT NULL,
    removed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'removed'  -- removed | source_gone
);
"""



FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS works_fts USING fts5(
    work_id UNINDEXED,
    title,
    caption,
    tags,
    ai_type,
    tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS prompt_fts USING fts5(
    work_id UNINDEXED,
    prompt_text,
    tokenize='unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS prompt_work_fts USING fts5(
    work_id UNINDEXED,
    prompt_text,
    tokenize='unicode61'
);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._closed = False
        self.conn = sqlite3.connect(
            self.db_path, check_same_thread=False, timeout=30.0
        )
        self._reader_connections: set[sqlite3.Connection] = set()
        self._connection_finalizer = weakref.finalize(
            self,
            _close_sqlite_connections,
            self.conn,
            self._reader_connections,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        from db_crawler_writes import check_schema_version

        check_schema_version(self)
        self.conn.executescript(SCHEMA)
        self._ensure_columns()
        self.conn.executescript(FTS_SCHEMA)
        from nai_tag_index import ensure_nai_tag_schema
        from gallery_index import ensure_schema as ensure_gallery_index_schema

        ensure_nai_tag_schema(self.conn)
        ensure_gallery_index_schema(self.conn)
        self._prompt_work_fts_ready = (
            self.get_state("prompt_work_fts_ready", "0") == "1"
        )
        self.conn.commit()

    def _run(self, fn):
        with self._lock:
            return fn()

    def _count(self, sql: str, params: tuple = ()) -> int:
        return self._run(lambda: int(self.conn.execute(sql, params).fetchone()["c"]))

    def _reader(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError("Database is closed")
            conn = getattr(self._local, "reader_conn", None)
            if conn is None:
                conn = sqlite3.connect(
                    self.db_path, check_same_thread=False, timeout=30.0
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA query_only=ON")
                self._local.reader_conn = conn
                self._reader_connections.add(conn)
            return conn

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection_finalizer()
            self._local.reader_conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_columns(self) -> None:
        cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(work_images)").fetchall()
        }
        if "local_path" not in cols:
            self.conn.execute("ALTER TABLE work_images ADD COLUMN local_path TEXT")
        if "downloaded" not in cols:
            self.conn.execute(
                "ALTER TABLE work_images ADD COLUMN downloaded INTEGER DEFAULT 0"
            )
        if "source_page_index" not in cols:
            self.conn.execute(
                "ALTER TABLE work_images ADD COLUMN source_page_index INTEGER"
            )
        if "source_url" not in cols:
            self.conn.execute("ALTER TABLE work_images ADD COLUMN source_url TEXT")
        if "source_sha256" not in cols:
            self.conn.execute(
                "ALTER TABLE work_images ADD COLUMN source_sha256 TEXT"
            )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_images_source_page "
            "ON work_images(work_id, source_page_index)"
        )
        work_cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(works)").fetchall()
        }
        if "preview_attempts" not in work_cols:
            self.conn.execute(
                "ALTER TABLE works ADD COLUMN preview_attempts INTEGER DEFAULT 0"
            )
        if "user_name" not in work_cols:
            self.conn.execute("ALTER TABLE works ADD COLUMN user_name TEXT")
        if "source_url" not in work_cols:
            self.conn.execute("ALTER TABLE works ADD COLUMN source_url TEXT")
        if "removed_status" not in work_cols:
            # removed_status: NULL=正常, "removed"=源作品已删除,
            # "deleted_local"=用户本地删除, "source_gone"=源 404
            self.conn.execute(
                "ALTER TABLE works ADD COLUMN removed_status TEXT DEFAULT NULL"
            )
        if "no_ai_notice" not in work_cols:
            # 作者声明：禁止 AI / 禁止转载 / 无声明
            self.conn.execute(
                "ALTER TABLE works ADD COLUMN no_ai_notice TEXT DEFAULT NULL"
            )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_works_create_date_id "
            "ON works(create_date, id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_works_local_nai_date "
            "ON works(create_date DESC, id DESC) "
            "WHERE list_json IS NOT NULL"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_works_image_count "
            "ON works(image_count DESC, create_date DESC, id DESC)"
        )
        self.conn.executescript(COMPLIANCE_SCHEMA)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_works_preview_pending "
            "ON works(preview_downloaded, preview_attempts, id) "
            "WHERE list_json IS NOT NULL AND detail_json IS NOT NULL"
        )

    def get_state(self, key: str, default: str = "") -> str:
        def action():
            row = self.conn.execute(
                "SELECT value FROM crawl_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

        return self._run(action)

    def set_state(self, key: str, value: str) -> None:
        def action():
            self.conn.execute(
                "INSERT INTO crawl_state(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.conn.commit()

        self._run(action)

    def _sync_work_fts(self, work_id: int) -> None:
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

    def _sync_prompt_fts(self, work_id: int) -> None:
        self.conn.execute("DELETE FROM prompt_fts WHERE work_id = ?", (work_id,))
        rows = self.conn.execute(
            "SELECT prompt_text, ai_json FROM work_images WHERE work_id = ?",
            (work_id,),
        ).fetchall()
        for row in rows:
            prompt = (row["prompt_text"] or decompress_if_needed(row["ai_json"]) or "").strip()
            if prompt:
                self.conn.execute(
                    "INSERT INTO prompt_fts(work_id, prompt_text) VALUES (?, ?)",
                    (work_id, prompt),
                )

    def rebuild_fts(self) -> None:
        self.conn.execute("DELETE FROM works_fts")
        self.conn.execute("DELETE FROM prompt_fts")
        work_ids = [
            int(row["id"])
            for row in self.conn.execute("SELECT id FROM works").fetchall()
        ]
        for work_id in work_ids:
            self._sync_work_fts(work_id)
            self._sync_prompt_fts(work_id)
        self.conn.commit()
        self.rebuild_prompt_work_fts()

    def upsert_list_item(self, item: dict[str, Any], crawled_at: str) -> None:
        def action():
            self._upsert_list_item_impl(item, crawled_at)

        self._run(action)

    def _upsert_list_item_impl(
        self,
        item: dict[str, Any],
        crawled_at: str,
        *,
        sync_fts: bool = True,
        invalidate_cache: bool = True,
    ) -> tuple[bool, bool]:
        item = self._normalize_list_item(item)
        work_id = int(item["id"])
        existing = self.conn.execute(
            "SELECT list_json, detail_json, title, caption, tags FROM works WHERE id = ?",
            (work_id,),
        ).fetchone()
        new_list_json = json.dumps(item, ensure_ascii=False)
        if (
            existing
            and existing["list_json"] == new_list_json
            and existing["detail_json"]
        ):
            return False, False
        self.conn.execute(
            """
            INSERT INTO works(
                id, user_id, title, caption, tags, ai_type, create_date,
                image_count, total_view, total_bookmarks, list_json, crawled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
                title = excluded.title,
                caption = excluded.caption,
                tags = excluded.tags,
                ai_type = excluded.ai_type,
                create_date = excluded.create_date,
                image_count = excluded.image_count,
                total_view = excluded.total_view,
                total_bookmarks = excluded.total_bookmarks,
                list_json = excluded.list_json,
                crawled_at = excluded.crawled_at
            """,
            (
                work_id,
                item.get("userId"),
                item.get("title"),
                item.get("caption"),
                item.get("tags"),
                item.get("AI_type") or item.get("ai_type"),
                item.get("create_date"),
                item.get("image_count"),
                item.get("total_view"),
                item.get("total_bookmarks"),
                new_list_json,
                crawled_at,
            ),
        )
        needs_fts = not existing or not existing["detail_json"] or _list_text_changed(existing, item)
        if needs_fts and sync_fts:
            self._sync_work_fts(work_id)
        if invalidate_cache:
            _invalidate_scope_total_cache()
        return True, needs_fts

    def has_detail(self, work_id: int) -> bool:
        return self._run(
            lambda: self.conn.execute(
                "SELECT 1 FROM works WHERE id = ? AND detail_json IS NOT NULL",
                (work_id,),
            ).fetchone()
            is not None
        )

    def has_preview(self, work_id: int) -> bool:
        return self._run(
            lambda: bool(
                (row := self.conn.execute(
                    "SELECT preview_downloaded FROM works WHERE id = ?",
                    (work_id,),
                ).fetchone())
                and int(row["preview_downloaded"] or 0) == 1
            )
        )

    @staticmethod
    def _resolve_image_count(
        work: dict[str, Any],
        row_count: int | None = None,
    ) -> int:
        count = int(work.get("image_count") or 0)
        if count > 0:
            return count
        if row_count and int(row_count) > 0:
            return int(row_count)
        original_urls = work.get("original_urls")
        if original_urls:
            try:
                urls = (
                    json.loads(original_urls)
                    if isinstance(original_urls, str)
                    else original_urls
                )
                if isinstance(urls, list) and urls:
                    return len(urls)
            except Exception:
                pass
        return 0

    @staticmethod
    def _row_value(row: sqlite3.Row, key: str) -> Any:
        return row[key] if key in row.keys() else None

    @staticmethod
    def _hydrate_work_item(work: dict[str, Any], row: sqlite3.Row) -> dict[str, Any]:
        work["image_count"] = Database._resolve_image_count(
            work,
            Database._row_value(row, "image_count"),
        )
        row_view = Database._row_value(row, "total_view")
        row_bookmarks = Database._row_value(row, "total_bookmarks")
        if not work.get("total_view") and row_view:
            work["total_view"] = row_view
        if not work.get("total_bookmarks") and row_bookmarks:
            work["total_bookmarks"] = row_bookmarks
        return work

    @staticmethod
    def _normalize_list_item(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        if not int(normalized.get("image_count") or 0):
            count = Database._resolve_image_count(normalized)
            if count > 0:
                normalized["image_count"] = count
        return normalized

    @staticmethod
    def cover_rel_path_from_list_json(list_json: str | None) -> str:
        if not list_json:
            return ""
        try:
            work = json.loads(list_json)
        except Exception:
            return ""
        ai_type = str(work.get("AI_type") or "NAI").strip()
        user_id = work.get("userId")
        work_pk = work.get("id")
        if not ai_type or not user_id or not work_pk:
            return ""
        return f"images/{ai_type}/{user_id}/{work_pk}_p0.webp"

    def reconcile_local_covers(self, data_dir: Path) -> dict[str, int]:
        """把磁盘上已有的封面同步进数据库，避免重复下载。"""

        def action() -> dict[str, int]:
            root = data_dir.resolve()
            images_root = root / "images"
            fixed_works = 0
            fixed_images = 0
            rows = self.conn.execute(
                """
                SELECT id, list_json, preview_path, preview_downloaded
                FROM works
                WHERE COALESCE(preview_downloaded, 0) = 0
                  AND list_json IS NOT NULL
                """
            ).fetchall()
            for row in rows:
                work_id = int(row["id"])
                candidates: list[Path] = []
                rel = str(row["preview_path"] or "").replace("\\", "/").strip()
                if rel:
                    candidates.append(
                        root / rel if rel.startswith("images/") else images_root / rel
                    )
                rel_list = self.cover_rel_path_from_list_json(row["list_json"])
                if rel_list:
                    candidates.append(root / rel_list)

                hit: Path | None = None
                for path in candidates:
                    if path.is_file():
                        hit = path
                        break
                if not hit:
                    continue

                rel_path = str(hit.relative_to(root)).replace("\\", "/")
                self.conn.execute(
                    """
                    UPDATE works
                    SET preview_downloaded = 1,
                        preview_path = COALESCE(preview_path, ?),
                        preview_attempts = 0
                    WHERE id = ?
                    """,
                    (rel_path, work_id),
                )
                updated = self.conn.execute(
                    """
                    UPDATE work_images
                    SET local_path = ?, downloaded = 1
                    WHERE work_id = ? AND page_index = 0
                    """,
                    (rel_path, work_id),
                ).rowcount
                fixed_works += 1
                if updated:
                    fixed_images += int(updated)

            self.conn.commit()
            return {
                "works_marked": fixed_works,
                "image_rows_updated": fixed_images,
            }

        return self._run(action)

    def _save_detail_impl(
        self,
        work_id: int,
        detail: dict[str, Any],
        preview_path: str | None,
        preview_downloaded: bool,
        crawled_at: str,
        *,
        commit: bool = True,
        sync_fts: bool = True,
    ) -> bool:
        if self.has_detail(work_id):
            return False
        work = detail.get("work") or {}
        images = detail.get("images") or []
        existing = self.conn.execute(
            "SELECT preview_downloaded, preview_path FROM works WHERE id = ?",
            (work_id,),
        ).fetchone()
        old_images = {
            int(row["page_index"]): row
            for row in self.conn.execute(
                """
                SELECT page_index, local_path, downloaded
                FROM work_images
                WHERE work_id = ?
                """,
                (work_id,),
            ).fetchall()
        }
        if existing and int(existing["preview_downloaded"] or 0) == 1:
            preview_downloaded = True
            preview_path = preview_path or existing["preview_path"]

        detail_image_count = int(work.get("image_count") or len(images) or 0)
        self.conn.execute(
            """
            UPDATE works SET
                user_id = COALESCE(?, user_id),
                title = COALESCE(?, title),
                caption = COALESCE(?, caption),
                tags = COALESCE(?, tags),
                ai_type = COALESCE(?, ai_type),
                create_date = COALESCE(?, create_date),
                image_count = COALESCE(?, image_count),
                total_view = COALESCE(?, total_view),
                total_bookmarks = COALESCE(?, total_bookmarks),
                detail_json = ?,
                preview_path = COALESCE(?, preview_path),
                preview_downloaded = ?,
                crawled_at = ?
            WHERE id = ?
            """,
            (
                work.get("userId") or work.get("userid"),
                work.get("title"),
                work.get("caption"),
                work.get("tags"),
                work.get("AI_type") or work.get("ai_type"),
                work.get("create_date"),
                detail_image_count or None,
                work.get("total_view"),
                work.get("total_bookmarks"),
                compress_text(json.dumps(detail, ensure_ascii=False)),
                preview_path,
                1 if preview_downloaded else 0,
                crawled_at,
                work_id,
            ),
        )
        if detail_image_count > 0:
            list_row = self.conn.execute(
                "SELECT list_json FROM works WHERE id = ?",
                (work_id,),
            ).fetchone()
            if list_row and list_row["list_json"]:
                try:
                    list_work = json.loads(list_row["list_json"])
                except Exception:
                    list_work = None
                if isinstance(list_work, dict) and int(list_work.get("image_count") or 0) != detail_image_count:
                    list_work["image_count"] = detail_image_count
                    self.conn.execute(
                        "UPDATE works SET list_json = ? WHERE id = ?",
                        (json.dumps(list_work, ensure_ascii=False), work_id),
                    )
        self.conn.execute("DELETE FROM work_images WHERE work_id = ?", (work_id,))
        for index, image in enumerate(images):
            old = old_images.get(index)
            local_path = image.get("local_path")
            downloaded = int(image.get("downloaded") or 0)
            if old:
                if int(old["downloaded"] or 0) == 1:
                    downloaded = 1
                    local_path = old["local_path"] or local_path
                elif (
                    index == 0
                    and preview_downloaded
                    and preview_path
                    and not local_path
                ):
                    local_path = preview_path
                    downloaded = 1
            raw_ai = image.get("ai_json")
            if raw_ai in ("", None):
                ai_blob = None
            elif isinstance(raw_ai, (dict, list)):
                ai_blob = compress_text(json.dumps(raw_ai, ensure_ascii=False))
            else:
                ai_blob = compress_text(str(raw_ai))
            self.conn.execute(
                """
                INSERT INTO work_images(
                    id, work_id, author_id, image_type, file_name, image_path,
                    model, ai_json, prompt_text, page_index, local_path, downloaded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image.get("id"),
                    work_id,
                    image.get("author_id"),
                    image.get("image_type") or "NAI",
                    image.get("file_name"),
                    image.get("image_path"),
                    image.get("model"),
                    ai_blob,
                    image.get("prompt_text"),
                    int(image.get("page_index") if image.get("page_index") is not None else index),
                    local_path,
                    downloaded,
                ),
            )
        if sync_fts:
            self._sync_work_fts(work_id)
            self._sync_prompt_fts(work_id)
        try:
            from nai_char import clear_extract_chars_cache

            clear_extract_chars_cache(work_id)
        except Exception:
            pass
        if commit:
            self.conn.commit()
            _invalidate_scope_total_cache()
        return True

    def mark_image_downloaded(
        self,
        work_id: int,
        page_index: int,
        local_path: str,
        *,
        cover_only: bool = False,
    ) -> None:
        def action():
            self._mark_image_downloaded_impl(
                work_id, page_index, local_path, cover_only=cover_only
            )

        self._run(action)

    def _mark_image_downloaded_impl(
        self,
        work_id: int,
        page_index: int,
        local_path: str,
        *,
        cover_only: bool = False,
    ) -> None:
        self.conn.execute(
            """
            UPDATE work_images
            SET local_path = ?, downloaded = 1
            WHERE work_id = ? AND page_index = ?
            """,
            (local_path, work_id, page_index),
        )
        if cover_only:
            self.conn.execute(
                """
                UPDATE works
                SET preview_downloaded = 1, preview_path = ?
                WHERE id = ?
                """,
                (local_path, work_id),
            )
        else:
            pending = self.conn.execute(
                """
                SELECT COUNT(*) AS c FROM work_images
                WHERE work_id = ? AND downloaded = 0
                """,
                (work_id,),
            ).fetchone()["c"]
            if pending == 0:
                first = self.conn.execute(
                    """
                    SELECT local_path FROM work_images
                    WHERE work_id = ? AND downloaded = 1
                    ORDER BY page_index LIMIT 1
                    """,
                    (work_id,),
                ).fetchone()
                preview_path = first["local_path"] if first else None
                self.conn.execute(
                    """
                    UPDATE works
                    SET preview_downloaded = 1, preview_path = COALESCE(?, preview_path)
                    WHERE id = ?
                    """,
                    (preview_path, work_id),
                )
        self.conn.commit()

    def count_works(self) -> int:
        return self._count("SELECT COUNT(*) AS c FROM works")

    def count_details(self) -> int:
        return self._count("SELECT COUNT(*) AS c FROM works WHERE detail_json IS NOT NULL")

    def count_previews(self) -> int:
        return self._count("SELECT COUNT(*) AS c FROM works WHERE preview_downloaded = 1")

    def count_pending_details(self, *, arknights_only: bool = False) -> int:
        ark_sql = f" AND ({ARK_MATCH_SQL})" if arknights_only else ""
        return self._count(f"SELECT COUNT(*) AS c FROM works WHERE detail_json IS NULL{ark_sql}")

    def count_pending_previews(
        self, *, arknights_only: bool = False, max_attempts: int = 6
    ) -> int:
        ark_sql = f" AND ({ARK_MATCH_SQL})" if arknights_only else ""
        return self._count(
            f"""
            SELECT COUNT(*) AS c FROM works
            WHERE list_json IS NOT NULL
              AND detail_json IS NOT NULL
              AND preview_downloaded = 0
              AND COALESCE(preview_attempts, 0) < ?{ark_sql}
            """,
            (max_attempts,),
        )

    def count_exhausted_previews(
        self, *, arknights_only: bool = False, max_attempts: int = 6
    ) -> int:
        ark_sql = f" AND ({ARK_MATCH_SQL})" if arknights_only else ""
        return self._count(
            f"""
            SELECT COUNT(*) AS c FROM works
            WHERE detail_json IS NOT NULL
              AND preview_downloaded = 0
              AND COALESCE(preview_attempts, 0) >= ?{ark_sql}
            """,
            (max_attempts,),
        )

    def count_downloaded_images(self) -> int:
        return self._count("SELECT COUNT(*) AS c FROM work_images WHERE downloaded = 1")

    def pending_detail_ids(
        self, limit: int = 100, *, arknights_only: bool = False
    ) -> list[int]:
        ark_sql = f" AND ({ARK_MATCH_SQL})" if arknights_only else ""
        rows = self.conn.execute(
            f"""
            SELECT id FROM works
            WHERE detail_json IS NULL{ark_sql}
            ORDER BY COALESCE(total_bookmarks, 0) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def cover_image_from_list_json(self, work_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT list_json FROM works WHERE id = ?", (work_id,)
        ).fetchone()
        if not row or not row["list_json"]:
            return None
        work = json.loads(row["list_json"])
        ai_type = str(work.get("AI_type") or "NAI").strip()
        user_id = work.get("userId")
        work_pk = work.get("id")
        if not ai_type or not user_id or not work_pk:
            return None
        return {
            "page_index": 0,
            "image_type": ai_type,
            "author_id": user_id,
            "file_name": f"{work_pk}_p0",
            "image_path": "",
        }

    @staticmethod
    def thumb_rel_path(
        work: dict[str, Any],
        preview_path: str | None = None,
    ) -> str:
        if preview_path:
            path = str(preview_path).replace("\\", "/")
            if path.startswith("images/"):
                path = path[len("images/") :]
            return path
        ai_type = str(work.get("AI_type") or "").strip()
        user_id = work.get("userId")
        work_id = work.get("id")
        if ai_type and user_id and work_id:
            return f"{ai_type}/{user_id}/{work_id}_p0.webp"
        return ""

    def _local_dataset_clause(self, scope: str) -> tuple[str, list[Any]]:
        return _query_local_dataset_clause(self, scope)
        # 兼容旧配置：回退到 FTS 范围查询
# Query/detail/rank methods are implemented in db_queries.py to keep this
# storage-focused module below the product quality gate size threshold while
# preserving the public Database API used by the rest of the app.
from db_queries import (  # noqa: E402
    ARK_MATCH_SQL,
    get_work_detail as _query_get_work_detail,
    get_work_lite as _query_get_work_lite,
    get_work_prompt_snippet as _query_get_work_prompt_snippet,
    local_dataset_clause as _query_local_dataset_clause,
    list_rank_calendar as _query_list_rank_calendar,
    search_favorite_works as _query_search_favorite_works,
    search_monthly_rank as _query_search_monthly_rank,
    search_works as _query_search_works,
    work_in_scope as _query_work_in_scope,
    _month_rank_clause as _query_month_rank_clause,
    _normalize_rank_period as _query_normalize_rank_period,
    _order_clause as _query_order_clause,
    _search_monthly_rank_impl as _query_search_monthly_rank_impl,
    _search_works_impl as _query_search_works_impl,
    _time_range_clause as _query_time_range_clause,
)
from db_prompt_index import (  # noqa: E402
    prompt_search_table as _prompt_search_table,
    rebuild_prompt_work_fts as _rebuild_prompt_work_fts,
    sync_prompt_fts as _sync_prompt_fts_index,
)
from db_crawler_writes import (  # noqa: E402
    _list_text_changed,
    bump_preview_attempts as _bump_preview_attempts,
    cached_scope_total as _cached_scope_total,
    configure_crawler_wal as _configure_crawler_wal,
    count_scope_works as _count_scope_works,
    pending_images_for_work as _pending_images_for_work,
    pending_preview_work_ids as _pending_preview_work_ids,
    reset_preview_attempts as _reset_preview_attempts,
    save_detail as _batch_save_detail,
    save_details_batch as _save_details_batch,
    requeue_exhausted_previews as _requeue_exhausted_previews,
    sync_prompt_fts_batch as _sync_prompt_fts_batch,
    sync_work_fts_batch as _sync_work_fts_batch,
    upsert_list_items_batch as _upsert_list_items_batch,
)
from nai_tag_index import (  # noqa: E402
    popular_nai_facets as _popular_nai_facets,
    rebuild_nai_tag_index as _rebuild_nai_tag_index,
    sync_work_nai_tag_index as _sync_work_nai_tag_index,
)

Database._sync_prompt_fts = _sync_prompt_fts_index
Database._sync_work_fts_batch = _sync_work_fts_batch
Database._sync_prompt_fts_batch = _sync_prompt_fts_batch
Database.configure_crawler_wal = _configure_crawler_wal
Database.count_scope_works = _count_scope_works
Database.cached_scope_total = _cached_scope_total
Database.pending_preview_work_ids = _pending_preview_work_ids
Database.bump_preview_attempts = _bump_preview_attempts
Database.reset_preview_attempts = _reset_preview_attempts
Database.pending_images_for_work = _pending_images_for_work
Database.upsert_list_items_batch = _upsert_list_items_batch
Database.save_detail = _batch_save_detail
Database.save_details_batch = _save_details_batch
Database.requeue_exhausted_previews = _requeue_exhausted_previews
Database.prompt_search_table = _prompt_search_table
Database.rebuild_prompt_work_fts = _rebuild_prompt_work_fts
Database.rebuild_nai_tag_index = _rebuild_nai_tag_index
Database.popular_nai_facets = _popular_nai_facets
Database._sync_nai_tag_index = _sync_work_nai_tag_index
Database.work_in_scope = _query_work_in_scope
Database._local_dataset_clause = _query_local_dataset_clause
Database.get_work_detail = _query_get_work_detail
Database.get_work_prompt_snippet = _query_get_work_prompt_snippet
Database.get_work_lite = _query_get_work_lite
Database._time_range_clause = _query_time_range_clause
Database._order_clause = _query_order_clause
Database.search_works = _query_search_works
Database._search_works_impl = _query_search_works_impl
Database.search_favorite_works = _query_search_favorite_works
Database._normalize_rank_period = staticmethod(_query_normalize_rank_period)
Database._month_rank_clause = staticmethod(_query_month_rank_clause)
Database.list_rank_calendar = _query_list_rank_calendar
Database.search_monthly_rank = _query_search_monthly_rank
Database._search_monthly_rank_impl = _query_search_monthly_rank_impl
