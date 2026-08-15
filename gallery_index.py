"""Additive gallery index: dirty-set FTS sync, exact/near dups, local similar.

This is not a second task store. Tables live in the existing per-gallery SQLite
file. ``/api/ai_works_search`` JSON is unchanged. Embedding stays off.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from nai_image_metadata import PARSER_VERSION
from paths import canonical_path, normalize_image_relative, path_is_within

TEXT_INDEX_REV = 1
VISUAL_INDEX_REV = 1
EMBED_INDEX_REV = 1
DEFAULT_DHASH_NEAR = 4
DEFAULT_PHASH_NEAR = 8
DEFAULT_PHASH_SIMILAR = 12
MAX_INCREMENTAL_WORK_IDS = 200
MAX_INCREMENTAL_ITEMS = 500
MAX_DUPLICATE_GROUPS = 200
MAX_SIMILAR_LIMIT = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS gallery_index_files (
    image_key TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    file_size INTEGER,
    mtime_ns INTEGER,
    source_sha256 TEXT,
    parser_version TEXT,
    text_rev INTEGER NOT NULL DEFAULT 0,
    visual_rev INTEGER NOT NULL DEFAULT 0,
    embed_rev INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_index_sha
    ON gallery_index_files(source_sha256);
CREATE INDEX IF NOT EXISTS idx_gallery_index_dirty_text
    ON gallery_index_files(text_rev);

CREATE TABLE IF NOT EXISTS gallery_image_hashes (
    image_key TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    sha256 TEXT,
    dhash TEXT,
    phash TEXT,
    width INTEGER,
    height INTEGER,
    algo_rev INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_hashes_sha ON gallery_image_hashes(sha256);
CREATE INDEX IF NOT EXISTS idx_gallery_hashes_dhash ON gallery_image_hashes(dhash);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def image_key(work_id: int, page_index: int) -> str:
    return f"{int(work_id)}:{int(page_index)}"


def resolve_index_image_path(
    relative: str,
    images_dir: Path | None,
    extra_roots: Iterable[Path] | None = None,
) -> Path | None:
    """Resolve a work image only when it stays inside an allowed gallery root.

    Absolute paths that exist outside ``images_dir`` / extra roots are rejected.
    ``..`` traversal and NUL bytes are discarded.
    """

    raw = str(relative or "").strip()
    if not raw or "\x00" in raw:
        return None
    roots: list[Path] = []
    if images_dir is not None:
        roots.append(Path(images_dir))
    for extra in extra_roots or ():
        if extra is None:
            continue
        roots.append(Path(extra))
    if not roots:
        return None
    candidates: list[Path] = []
    incoming = Path(raw)
    if incoming.is_absolute():
        candidates.append(incoming)
    else:
        normalized = normalize_image_relative(raw)
        for root in roots:
            candidates.append(root / raw)
            if normalized and normalized != raw:
                candidates.append(root / normalized)
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = canonical_path(candidate)
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if not resolved.exists() or not resolved.is_file():
                continue
        except OSError:
            continue
        if any(path_is_within(resolved, root) for root in roots):
            return resolved
    return None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def is_dirty(
    row: dict[str, Any] | None,
    *,
    file_size: int | None,
    mtime_ns: int | None,
    source_sha256: str = "",
    parser_version: str = PARSER_VERSION,
    visual_enabled: bool = True,
    embed_enabled: bool = False,
) -> bool:
    if row is None:
        return True
    if file_size is not None and row.get("file_size") not in (None, file_size):
        return True
    if mtime_ns is not None and row.get("mtime_ns") not in (None, mtime_ns):
        return True
    stored_sha = str(row.get("source_sha256") or "")
    if source_sha256 and stored_sha and stored_sha != source_sha256:
        return True
    if str(row.get("parser_version") or "") != parser_version:
        return True
    if int(row.get("text_rev") or 0) < TEXT_INDEX_REV:
        return True
    if visual_enabled and int(row.get("visual_rev") or 0) < VISUAL_INDEX_REV:
        return True
    if embed_enabled and int(row.get("embed_rev") or 0) < EMBED_INDEX_REV:
        return True
    return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_dhash(image: Image.Image) -> int:
    gray = ImageOps.exif_transpose(image).convert("L")
    hashed = gray.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = _image_pixels(hashed)
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def _dct_1d(vector: list[float]) -> list[float]:
    size = len(vector)
    factor = math.pi / (2.0 * size)
    scale0 = math.sqrt(1.0 / size)
    scale = math.sqrt(2.0 / size)
    out: list[float] = []
    for freq in range(size):
        total = 0.0
        for index, sample in enumerate(vector):
            total += sample * math.cos((2 * index + 1) * freq * factor)
        out.append(total * (scale0 if freq == 0 else scale))
    return out


def compute_phash(image: Image.Image) -> int:
    gray = ImageOps.exif_transpose(image).convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    flat = list(map(float, _image_pixels(gray)))
    rows = [flat[row * 32 : (row + 1) * 32] for row in range(32)]
    dct_rows = [_dct_1d(row) for row in rows]
    dct = [_dct_1d([dct_rows[row][col] for row in range(32)]) for col in range(32)]
    low = [dct[col][row] for row in range(8) for col in range(8)]
    median = sorted(low[1:])[len(low[1:]) // 2]
    value = 0
    for coeff in low:
        value = (value << 1) | int(coeff > median)
    return value


def hamming(left: int, right: int) -> int:
    return int(left ^ right).bit_count()


def hash_bucket(value: int) -> int:
    return (int(value) >> 48) & 0xFFFF


def hash_to_text(value: int) -> str:
    return f"{int(value) & ((1 << 64) - 1):016x}"


def hash_from_text(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return int(value) & ((1 << 64) - 1)
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return None


def _image_pixels(image: Image.Image) -> list[int]:
    if hasattr(image, "get_flattened_data"):
        return list(image.get_flattened_data())
    return list(image.getdata())


@dataclass(frozen=True)
class IndexImage:
    work_id: int
    page_index: int = 0
    relative_path: str = ""
    file_size: int | None = None
    mtime_ns: int | None = None
    source_sha256: str = ""
    parser_version: str = PARSER_VERSION
    path: Path | None = None
    pixels: Image.Image | None = None


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _load_index_row(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    return _row_dict(
        conn.execute(
            "SELECT * FROM gallery_index_files WHERE image_key = ?",
            (key,),
        ).fetchone()
    )


def _open_image(item: IndexImage) -> Image.Image | None:
    if item.pixels is not None:
        return item.pixels
    if item.path is None:
        return None
    try:
        with Image.open(item.path) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            return image.copy()
    except (OSError, ValueError, UnidentifiedImageError):
        return None


def index_images(
    conn: sqlite3.Connection,
    items: Iterable[IndexImage],
    *,
    visual_enabled: bool = True,
    embed_enabled: bool = False,
    sync_text: Callable[[int], None] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Index a dirty set. Callers sync FTS via ``sync_text(work_id)``."""

    ensure_schema(conn)
    stamped = now or utc_now()
    scanned = 0
    text_dirty = 0
    visual_dirty = 0
    errors = 0
    touched_works: set[int] = set()
    for item in items:
        scanned += 1
        key = image_key(item.work_id, item.page_index)
        existing = _load_index_row(conn, key)
        sha = item.source_sha256
        size = item.file_size
        mtime_ns = item.mtime_ns
        if item.path is not None and item.path.exists():
            stat = item.path.stat()
            size = size if size is not None else int(stat.st_size)
            mtime_ns = mtime_ns if mtime_ns is not None else int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1e9))
            if not sha and (existing is None or is_dirty(existing, file_size=size, mtime_ns=mtime_ns, source_sha256="", parser_version=item.parser_version)):
                sha = sha256_file(item.path)
        elif item.pixels is not None and not sha:
            from io import BytesIO

            buffer = BytesIO()
            item.pixels.save(buffer, format="PNG")
            sha = sha256_bytes(buffer.getvalue())
        dirty = is_dirty(
            existing,
            file_size=size,
            mtime_ns=mtime_ns,
            source_sha256=sha,
            parser_version=item.parser_version,
            visual_enabled=visual_enabled,
            embed_enabled=embed_enabled,
        )
        if not dirty:
            continue
        last_error = ""
        text_rev = TEXT_INDEX_REV
        visual_rev = int((existing or {}).get("visual_rev") or 0)
        if sync_text is not None:
            sync_text(int(item.work_id))
        text_dirty += 1
        touched_works.add(int(item.work_id))
        if visual_enabled:
            image = _open_image(item)
            if image is None:
                last_error = "visual_unreadable"
                errors += 1
            else:
                width, height = image.size
                dhash = compute_dhash(image)
                phash = compute_phash(image)
                conn.execute(
                    """
                    INSERT INTO gallery_image_hashes(
                        image_key, work_id, page_index, sha256, dhash, phash,
                        width, height, algo_rev, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(image_key) DO UPDATE SET
                        work_id=excluded.work_id,
                        page_index=excluded.page_index,
                        sha256=excluded.sha256,
                        dhash=excluded.dhash,
                        phash=excluded.phash,
                        width=excluded.width,
                        height=excluded.height,
                        algo_rev=excluded.algo_rev,
                        updated_at=excluded.updated_at
                    """,
                    (
                        key,
                        int(item.work_id),
                        int(item.page_index),
                        sha,
                        hash_to_text(dhash),
                        hash_to_text(phash),
                        width,
                        height,
                        VISUAL_INDEX_REV,
                        stamped,
                    ),
                )
                visual_rev = VISUAL_INDEX_REV
                visual_dirty += 1
        conn.execute(
            """
            INSERT INTO gallery_index_files(
                image_key, work_id, page_index, relative_path, file_size, mtime_ns,
                source_sha256, parser_version, text_rev, visual_rev, embed_rev,
                last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_key) DO UPDATE SET
                work_id=excluded.work_id,
                page_index=excluded.page_index,
                relative_path=excluded.relative_path,
                file_size=excluded.file_size,
                mtime_ns=excluded.mtime_ns,
                source_sha256=excluded.source_sha256,
                parser_version=excluded.parser_version,
                text_rev=excluded.text_rev,
                visual_rev=excluded.visual_rev,
                embed_rev=excluded.embed_rev,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (
                key,
                int(item.work_id),
                int(item.page_index),
                item.relative_path,
                size,
                mtime_ns,
                sha,
                item.parser_version,
                text_rev,
                visual_rev,
                EMBED_INDEX_REV if embed_enabled else 0,
                last_error,
                stamped,
            ),
        )
    return {
        "scanned": scanned,
        "text_dirty": text_dirty,
        "visual_dirty": visual_dirty,
        "errors": errors,
        "works": sorted(touched_works),
        "embed": {"provider": "local_none", "outbound": False},
    }


def collect_work_image_items(
    conn: sqlite3.Connection,
    *,
    work_ids: Iterable[int] | None = None,
    images_dir: Path | None = None,
) -> list[IndexImage]:
    sql = """
        SELECT work_id, page_index, local_path, source_sha256
        FROM work_images
        WHERE downloaded = 1
    """
    params: tuple[Any, ...] = ()
    ids = [int(item) for item in (work_ids or [])]
    if ids:
        placeholders = ",".join("?" * len(ids))
        sql += f" AND work_id IN ({placeholders})"
        params = tuple(ids)
    rows = conn.execute(sql, params).fetchall()
    items: list[IndexImage] = []
    for row in rows:
        relative = str(row["local_path"] or "")
        path = resolve_index_image_path(relative, images_dir)
        items.append(
            IndexImage(
                work_id=int(row["work_id"]),
                page_index=int(row["page_index"] or 0),
                relative_path=relative,
                source_sha256=str(row["source_sha256"] or ""),
                path=path,
            )
        )
    return items


def find_exact_duplicates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT source_sha256 AS sha256, image_key, work_id, page_index
        FROM gallery_index_files
        WHERE source_sha256 IS NOT NULL AND source_sha256 != ''
        ORDER BY source_sha256, work_id, page_index
        """
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["sha256"]), []).append(
            {
                "image_key": row["image_key"],
                "work_id": int(row["work_id"]),
                "page_index": int(row["page_index"]),
            }
        )
    groups = [
        {"kind": "exact", "sha256": sha, "items": items}
        for sha, items in grouped.items()
        if len(items) > 1
    ]
    return groups[:MAX_DUPLICATE_GROUPS]


def find_near_duplicates(
    conn: sqlite3.Connection,
    *,
    dhash_threshold: int = DEFAULT_DHASH_NEAR,
    phash_threshold: int = DEFAULT_PHASH_NEAR,
) -> list[dict[str, Any]]:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT image_key, work_id, page_index, dhash, phash FROM gallery_image_hashes"
    ).fetchall()
    buckets: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        dhash = hash_from_text(row["dhash"])
        if dhash is None:
            continue
        buckets.setdefault(hash_bucket(dhash), []).append(row)
    seen: set[tuple[str, str]] = set()
    groups: list[dict[str, Any]] = []
    for bucket_rows in buckets.values():
        for index, left in enumerate(bucket_rows):
            members = [
                {
                    "image_key": left["image_key"],
                    "work_id": int(left["work_id"]),
                    "page_index": int(left["page_index"]),
                    "distance": 0,
                }
            ]
            for right in bucket_rows[index + 1 :]:
                pair = tuple(sorted((left["image_key"], right["image_key"])))
                if pair in seen:
                    continue
                left_d = hash_from_text(left["dhash"])
                right_d = hash_from_text(right["dhash"])
                left_p = hash_from_text(left["phash"])
                right_p = hash_from_text(right["phash"])
                d_dist = hamming(left_d or 0, right_d or 0)
                p_dist = hamming(left_p, right_p) if left_p is not None and right_p is not None else 99
                if d_dist <= dhash_threshold or p_dist <= phash_threshold:
                    seen.add(pair)
                    members.append(
                        {
                            "image_key": right["image_key"],
                            "work_id": int(right["work_id"]),
                            "page_index": int(right["page_index"]),
                            "distance": min(d_dist, p_dist),
                        }
                    )
            if len(members) > 1:
                groups.append({"kind": "near", "items": members})
            if len(groups) >= MAX_DUPLICATE_GROUPS:
                return groups[:MAX_DUPLICATE_GROUPS]
    return groups[:MAX_DUPLICATE_GROUPS]


def find_similar(
    conn: sqlite3.Connection,
    *,
    work_id: int,
    page_index: int = 0,
    limit: int = 24,
    threshold: int = DEFAULT_PHASH_SIMILAR,
) -> dict[str, Any]:
    ensure_schema(conn)
    key = image_key(work_id, page_index)
    source = conn.execute(
        "SELECT * FROM gallery_image_hashes WHERE image_key = ?",
        (key,),
    ).fetchone()
    if source is None:
        return {
            "query": {"work_id": work_id, "page_index": page_index},
            "items": [],
            "reason": "hash_missing",
        }
    rows = conn.execute(
        "SELECT image_key, work_id, page_index, dhash, phash FROM gallery_image_hashes WHERE image_key != ?",
        (key,),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        source_p = hash_from_text(source["phash"])
        row_p = hash_from_text(row["phash"])
        source_d = hash_from_text(source["dhash"])
        row_d = hash_from_text(row["dhash"])
        p_dist = hamming(source_p, row_p) if source_p is not None and row_p is not None else 99
        d_dist = hamming(source_d, row_d) if source_d is not None and row_d is not None else 99
        distance = min(p_dist, d_dist)
        if distance > threshold:
            continue
        kind = "phash" if p_dist <= d_dist else "dhash"
        scored.append(
            {
                "work_id": int(row["work_id"]),
                "page_index": int(row["page_index"]),
                "distance": distance,
                "kind": kind,
            }
        )
    scored.sort(key=lambda item: (item["distance"], item["work_id"], item["page_index"]))
    capped = min(max(0, int(limit)), MAX_SIMILAR_LIMIT)
    return {
        "query": {"work_id": work_id, "page_index": page_index},
        "items": scored[:capped],
        "limit": capped,
    }


def index_status(conn: sqlite3.Connection, gallery_id: str = "") -> dict[str, Any]:
    ensure_schema(conn)
    def _count(sql: str, params: tuple[Any, ...] = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0])

    works = 0
    images_local = 0
    try:
        works = _count("SELECT COUNT(*) FROM works")
        images_local = _count("SELECT COUNT(*) FROM work_images WHERE downloaded = 1")
    except sqlite3.Error:
        pass
    return {
        "gallery_id": gallery_id,
        "works": works,
        "images_local": images_local,
        "text_dirty": _count(
            "SELECT COUNT(*) FROM gallery_index_files WHERE text_rev < ?",
            (TEXT_INDEX_REV,),
        ),
        "visual_dirty": _count(
            "SELECT COUNT(*) FROM gallery_index_files WHERE visual_rev < ?",
            (VISUAL_INDEX_REV,),
        ),
        "embed_dirty": 0,
        "embed": {"provider": "local_none", "model": None, "outbound": False},
        "indexed": _count("SELECT COUNT(*) FROM gallery_index_files"),
        "hashed": _count("SELECT COUNT(*) FROM gallery_image_hashes"),
        "notes": "Counts are SQLite metadata, not a Windows 10k/100k bench.",
    }


def run_incremental(
    db: Any,
    work_ids: list[int] | None = None,
    *,
    visual: bool = True,
    images_dir: Path | None = None,
) -> dict[str, Any]:
    """Dirty-set index on an existing ``Database``. ``rebuild_fts`` stays the repair path.

    Lives here so ``db.py`` does not grow past the quality-gate line budget.
    """

    ids = [int(item) for item in work_ids] if work_ids is not None else None
    if ids is not None and len(ids) > MAX_INCREMENTAL_WORK_IDS:
        raise ValueError(f"work_ids exceeds {MAX_INCREMENTAL_WORK_IDS}")

    def action() -> dict[str, Any]:
        items = collect_work_image_items(
            db.conn, work_ids=ids, images_dir=images_dir
        )
        truncated = len(items) > MAX_INCREMENTAL_ITEMS
        if truncated:
            items = items[:MAX_INCREMENTAL_ITEMS]

        def sync_text(work_id: int) -> None:
            db._sync_work_fts(work_id)
            db._sync_prompt_fts(work_id)

        result = index_images(
            db.conn,
            items,
            visual_enabled=visual,
            sync_text=sync_text,
        )
        result["truncated"] = truncated
        result["item_limit"] = MAX_INCREMENTAL_ITEMS
        db.conn.commit()
        return result

    return db._run(action)
