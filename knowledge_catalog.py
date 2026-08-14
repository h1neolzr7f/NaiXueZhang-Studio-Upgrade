"""Local, zero-token retrieval for trusted Gallery and NovelAI documentation.

This module intentionally keeps the first retrieval adapter small: trusted
Markdown files are chunked by heading and indexed with SQLite FTS5.  It does
not load an embedding model, accept arbitrary filesystem paths, or call an
LLM.  A semantic adapter can be added later only if measured misses justify
the extra latency and memory cost.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from paths import data_dir


DEFAULT_SOURCE_PATHS = (
    "README.md",
    "PRODUCT.md",
    "ROADMAP.md",
    "CONTEXT.md",
    "DISCLAIMER.md",
    "RESPONSIBLE_USE.md",
    "SECURITY.md",
    "docs/user-guide.md",
)
DEFAULT_SOURCE_GLOBS = ("docs/**/*.md",)
MAX_CHUNK_CHARS = 1_200
MAX_QUERY_CHARS = 300
KNOWLEDGE_SCHEMA_VERSION = 1
KNOWLEDGE_INDEX_VERSION = "markdown-fts5-v1"


class KnowledgeRefreshCancelled(RuntimeError):
    """Raised at a trusted-source boundary when a rebuild is cancelled."""

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ENGLISH_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,}", re.IGNORECASE)
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_QUERY_STOP_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "怎么",
        "如何",
        "什么",
        "哪些",
        "是否",
        "可以",
        "这个",
        "那个",
        "里面",
    }
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _search_tokens(value: str) -> str:
    """Build portable English tokens and Chinese bigrams for FTS5."""

    folded = str(value or "").casefold()
    tokens = list(_ENGLISH_TOKEN_RE.findall(folded))
    for run in _CJK_RUN_RE.findall(folded):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return " ".join(dict.fromkeys(token for token in tokens if token))


def _split_markdown(text: str) -> list[dict[str, str]]:
    heading = ""
    paragraphs: list[str] = []
    chunks: list[dict[str, str]] = []

    def flush() -> None:
        nonlocal paragraphs
        body = "\n\n".join(part.strip() for part in paragraphs if part.strip()).strip()
        paragraphs = []
        if not body:
            return
        while body:
            part = body[:MAX_CHUNK_CHARS].strip()
            if len(body) > MAX_CHUNK_CHARS:
                cut = max(part.rfind("。"), part.rfind(". "), part.rfind("\n"))
                if cut >= MAX_CHUNK_CHARS // 2:
                    part = body[: cut + 1].strip()
            chunks.append({"heading": heading, "text": part})
            body = body[len(part) :].strip()

    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        match = _HEADING_RE.match(raw_line)
        if match:
            flush()
            heading = match.group(2).strip()
            continue
        if raw_line.strip():
            paragraphs.append(raw_line.strip())
        elif paragraphs:
            paragraphs.append("")
    flush()
    return chunks


class KnowledgeCatalog:
    """SQLite-backed catalogue for trusted software and NAI knowledge."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        source_root: Path | str | None = None,
    ) -> None:
        self.source_root = Path(source_root) if source_root else Path(__file__).resolve().parent
        self.db_path = Path(db_path) if db_path else data_dir() / "knowledge_catalog.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._refresh_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    source UNINDEXED,
                    title UNINDEXED,
                    heading UNINDEXED,
                    text,
                    tokens,
                    tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS knowledge_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(f"PRAGMA user_version={KNOWLEDGE_SCHEMA_VERSION}")

    @staticmethod
    def _write_meta(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
        conn.executemany(
            """
            INSERT INTO knowledge_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            [(str(key), str(value or "")) for key, value in values.items()],
        )

    @staticmethod
    def _content_version(conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            "SELECT source, fingerprint FROM knowledge_sources ORDER BY source"
        ).fetchall()
        if not rows:
            return ""
        payload = "\n".join(f"{row['source']}:{row['fingerprint']}" for row in rows)
        return _fingerprint(payload)[:16]

    def status(self) -> dict[str, Any]:
        with self._connection() as conn:
            meta = {
                str(row["key"]): str(row["value"])
                for row in conn.execute("SELECT key, value FROM knowledge_meta").fetchall()
            }
            sources = [
                dict(row)
                for row in conn.execute(
                    "SELECT source, title, chunk_count FROM knowledge_sources ORDER BY source"
                ).fetchall()
            ]
            chunks = int(conn.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0])
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            content_version = meta.get("content_version") or self._content_version(conn)
        state = meta.get("last_refresh_status") or ("ready" if sources else "never_built")
        try:
            duration_ms = round(float(meta.get("last_duration_ms") or 0), 3)
        except ValueError:
            duration_ms = 0.0
        return {
            "ok": state != "failed",
            "state": state,
            "usable": bool(sources),
            "schema_version": schema_version,
            "index_version": KNOWLEDGE_INDEX_VERSION,
            "content_version": content_version,
            "documents": len(sources),
            "chunks": chunks,
            "sources": sources,
            "last_started_at": meta.get("last_started_at", ""),
            "last_attempt_at": meta.get("last_started_at", ""),
            "last_completed_at": meta.get("last_completed_at", ""),
            "last_success_at": meta.get("last_success_at", ""),
            "last_duration_ms": duration_ms,
            "last_error": meta.get("last_error", ""),
            "model_calls": 0,
        }

    def _source_files(self) -> list[Path]:
        files: list[Path] = []
        for relative in DEFAULT_SOURCE_PATHS:
            candidate = self.source_root / relative
            if candidate.is_file():
                files.append(candidate)
        for pattern in DEFAULT_SOURCE_GLOBS:
            files.extend(path for path in self.source_root.glob(pattern) if path.is_file())
        return sorted(set(path.resolve() for path in files), key=lambda path: path.as_posix())

    def refresh_builtin_sources(
        self,
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        with self._refresh_lock:
            return self._refresh_builtin_sources(
                on_progress=on_progress,
                should_cancel=should_cancel,
            )

    def _refresh_builtin_sources(
        self,
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        started_at = _now()
        started = time.perf_counter()
        with self._connection() as conn:
            self._write_meta(
                conn,
                {
                    "last_refresh_status": "running",
                    "last_started_at": started_at,
                    "last_error": "",
                },
            )
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0}
        try:
            source_files = self._source_files()
            total_sources = len(source_files)
            if on_progress:
                on_progress(
                    {
                        "state": "running",
                        "processed": 0,
                        "total": total_sources,
                        "current_source": "",
                        **counts,
                    }
                )
            with self._connection() as conn:
                existing = {
                    str(row["source"]): dict(row)
                    for row in conn.execute(
                        "SELECT source, fingerprint, chunk_count FROM knowledge_sources"
                    ).fetchall()
                }
                seen: set[str] = set()
                processed = 0
                for path in source_files:
                    if should_cancel and should_cancel():
                        raise KnowledgeRefreshCancelled("知识库更新已取消")
                    source = path.relative_to(self.source_root.resolve()).as_posix()
                    text = path.read_text(encoding="utf-8", errors="replace")
                    chunks = _split_markdown(text)
                    if chunks:
                        seen.add(source)
                        title = chunks[0]["heading"] or path.stem
                        fingerprint = _fingerprint(text)
                        previous = existing.get(source)
                        if previous and str(previous["fingerprint"]) == fingerprint:
                            counts["unchanged"] += 1
                        else:
                            conn.execute("DELETE FROM knowledge_fts WHERE source=?", (source,))
                            conn.execute(
                                """
                                INSERT INTO knowledge_sources(source, title, fingerprint, chunk_count)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(source) DO UPDATE SET
                                    title=excluded.title,
                                    fingerprint=excluded.fingerprint,
                                    chunk_count=excluded.chunk_count
                                """,
                                (source, title, fingerprint, len(chunks)),
                            )
                            for chunk in chunks:
                                searchable = " ".join((title, chunk["heading"], chunk["text"]))
                                conn.execute(
                                    "INSERT INTO knowledge_fts(source, title, heading, text, tokens) VALUES (?, ?, ?, ?, ?)",
                                    (source, title, chunk["heading"], chunk["text"], _search_tokens(searchable)),
                                )
                            counts["updated" if previous else "inserted"] += 1
                    processed += 1
                    if on_progress:
                        on_progress(
                            {
                                "state": "running",
                                "processed": processed,
                                "total": total_sources,
                                "current_source": source,
                                **counts,
                            }
                        )
                for removed in set(existing) - seen:
                    conn.execute("DELETE FROM knowledge_fts WHERE source=?", (removed,))
                    conn.execute("DELETE FROM knowledge_sources WHERE source=?", (removed,))
                    counts["removed"] += 1
                documents = int(conn.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0])
                chunk_total = int(conn.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0])
                completed_at = _now()
                duration_ms = round((time.perf_counter() - started) * 1000, 3)
                content_version = self._content_version(conn)
                self._write_meta(
                    conn,
                    {
                        "last_refresh_status": "ready",
                        "last_completed_at": completed_at,
                        "last_success_at": completed_at,
                        "last_duration_ms": duration_ms,
                        "last_error": "",
                        "content_version": content_version,
                    },
                )
        except Exception as exc:
            cancelled = isinstance(exc, KnowledgeRefreshCancelled)
            with self._connection() as conn:
                self._write_meta(
                    conn,
                    {
                        "last_refresh_status": "cancelled" if cancelled else "failed",
                        "last_completed_at": _now(),
                        "last_duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "last_error": "" if cancelled else str(exc)[:500],
                    },
                )
            raise
        return {
            "ok": True,
            "state": "ready",
            "schema_version": KNOWLEDGE_SCHEMA_VERSION,
            "index_version": KNOWLEDGE_INDEX_VERSION,
            "content_version": content_version,
            "documents": documents,
            "chunks": chunk_total,
            "last_started_at": started_at,
            "last_completed_at": completed_at,
            "last_duration_ms": duration_ms,
            "processed": total_sources,
            "total": total_sources,
            **counts,
            "model_calls": 0,
        }

    def search(self, query: Any, *, limit: int = 3, char_budget: int = 1_200) -> dict[str, Any]:
        question = " ".join(str(query or "").strip().split())[:MAX_QUERY_CHARS]
        tokens = [
            token
            for token in _search_tokens(question).split()
            if token not in _QUERY_STOP_TOKENS
        ]
        if not tokens:
            return {"ok": True, "query": question, "items": [], "model_calls": 0}
        bounded_limit = max(1, min(int(limit), 8))
        bounded_budget = max(200, min(int(char_budget), 4_000))
        expression = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:32])
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT source, title, heading, text, bm25(knowledge_fts) AS rank
                FROM knowledge_fts
                WHERE knowledge_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, bounded_limit * 3),
            ).fetchall()

        items: list[dict[str, Any]] = []
        used = 0
        seen: set[tuple[str, str]] = set()
        for row in rows:
            text = str(row["text"] or "").strip()
            key = (str(row["source"]), text)
            if not text or key in seen or used >= bounded_budget:
                continue
            seen.add(key)
            remaining = bounded_budget - used
            excerpt = text[:remaining].strip()
            if not excerpt:
                break
            items.append(
                {
                    "source": str(row["source"]),
                    "title": str(row["title"]),
                    "heading": str(row["heading"]),
                    "text": excerpt,
                    "score": float(-row["rank"]),
                }
            )
            used += len(excerpt)
            if len(items) >= bounded_limit:
                break
        return {"ok": True, "query": question, "items": items, "model_calls": 0}


_DEFAULT_CATALOG: KnowledgeCatalog | None = None
_DEFAULT_LOCK = threading.Lock()


def get_knowledge_catalog(*, ensure_ready: bool = True) -> KnowledgeCatalog:
    """Return the process-wide trusted knowledge catalog.

    Status callers pass ``ensure_ready=False`` so a settings-page read never
    starts work. Software help keeps the historical lazy first-build behavior.
    """

    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_CATALOG is None:
                _DEFAULT_CATALOG = KnowledgeCatalog()
    catalog = _DEFAULT_CATALOG
    if ensure_ready and not catalog.status()["usable"]:
        catalog.refresh_builtin_sources()
    return catalog
