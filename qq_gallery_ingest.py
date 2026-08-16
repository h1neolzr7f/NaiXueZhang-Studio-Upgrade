"""Shared strict NovelAI ingestion primitives for the QQ gallery."""

from __future__ import annotations

from db_compression import compress_text, decompress_if_needed

import hashlib
import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from gallery_catalog import GALLERY_QQ
from nai_image_metadata import NAIParseResult, PARSER_VERSION, parse_nai_image
from scripts.gallery_import_common import (
    IMAGE_EXTS,
    sanitize_filename,
    stable_work_id,
    upsert_local_work,
)

COMFY_MARKERS = ("comfyui", "comfy", "workflow.json", "prompt.json")
SKIP_DIR_NAMES = {
    "__pycache__",
    "maaresource-main",
    "maa resource-main",
    ".git",
    "node_modules",
}


@dataclass(frozen=True)
class QQIdentity:
    group_key: str
    group_label: str
    account_key: str
    account_label: str


@dataclass(frozen=True)
class QQImageCandidate:
    source: Path
    relative_path: Path
    identity: QQIdentity


def looks_like_comfy(path: Path) -> bool:
    return any(
        marker in part.lower()
        for part in Path(path).parts
        for marker in COMFY_MARKERS
    )


def _identity_value(value: Any, fallback: str = "") -> str:
    return str(value or fallback).strip()


def resolve_qq_identity(
    relative_path: Path,
    *,
    layout: str,
    default_group_key: str,
    default_group_label: str,
    manifest_entry: dict[str, Any] | None = None,
) -> QQIdentity:
    """Resolve a stable group/account identity without guessing from metadata."""

    entry = manifest_entry if isinstance(manifest_entry, dict) else {}
    group_key = _identity_value(
        entry.get("group_id") or entry.get("group_key"),
    )
    group_label = _identity_value(
        entry.get("group_name") or entry.get("group_label"),
        group_key,
    )
    account_key = _identity_value(
        entry.get("sender_id") or entry.get("account_key"),
    )
    account_label = _identity_value(
        entry.get("sender_name") or entry.get("account_label"),
        account_key,
    )
    if group_key and account_key:
        return QQIdentity(
            group_key,
            group_label or group_key,
            account_key,
            account_label or account_key,
        )

    dirs = list(Path(relative_path).parts[:-1])
    normalized_layout = str(layout or "account").strip().lower()
    if normalized_layout == "group_account" and len(dirs) >= 2:
        group_key = group_key or dirs[0]
        group_label = group_label or dirs[0]
        account_key = account_key or dirs[1]
        account_label = account_label or dirs[1]
    elif dirs:
        group_key = group_key or default_group_key
        group_label = group_label or default_group_label or group_key
        account_key = account_key or dirs[0]
        account_label = account_label or dirs[0]

    return QQIdentity(
        _identity_value(group_key, default_group_key),
        _identity_value(group_label, default_group_label or group_key),
        _identity_value(account_key),
        _identity_value(account_label, account_key),
    )


def load_identity_manifest(root: Path) -> dict[str, dict[str, Any]]:
    """Read optional QQ-export identity receipts without requiring a QQ SDK."""

    manifest: dict[str, dict[str, Any]] = {}
    for filename in ("qq-export.jsonl", "qq_manifest.jsonl"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            rel = _identity_value(
                row.get("relative_path") or row.get("path")
            ).replace("\\", "/").lstrip("/")
            if rel and not Path(rel).is_absolute():
                manifest[rel.casefold()] = row
    return manifest


def iter_qq_images(
    root: Path,
    *,
    layout: str,
    default_group_key: str,
    default_group_label: str,
) -> Iterable[QQImageCandidate]:
    if not root.is_dir():
        return
    manifest = load_identity_manifest(root)
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            name
            for name in dirs
            if name.lower() not in SKIP_DIR_NAMES
            and not name.startswith(".")
            and "maaresource" not in name.lower()
        ]
        current_path = Path(current)
        for filename in files:
            source = current_path / filename
            if source.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                relative = source.relative_to(root)
            except ValueError:
                continue
            manifest_entry = manifest.get(relative.as_posix().casefold())
            identity = resolve_qq_identity(
                relative,
                layout=layout,
                default_group_key=default_group_key,
                default_group_label=default_group_label,
                manifest_entry=manifest_entry,
            )
            yield QQImageCandidate(source, relative, identity)


def source_id(path: Path) -> str:
    raw = str(Path(path).resolve()).replace("\\", "/").casefold()
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def work_identity_key(
    identity: QQIdentity,
    title: str,
) -> tuple[str, str, str]:
    """Return the legacy-compatible logical identity of one QQ image."""

    return (
        _identity_value(identity.group_key, "legacy").casefold(),
        _identity_value(identity.account_key).casefold(),
        _identity_value(title).casefold(),
    )


def load_existing_work_id_index(db) -> dict[tuple[str, str, str], int]:
    """Index existing works so upgrades reuse IDs instead of duplicating them.

    The historical QQ importer did not persist the source path or its ID
    algorithm.  Account plus the original filename stem is the strongest
    recoverable identity. Ambiguous historical names are deliberately omitted
    so a new source-path ID is safer than merging two different images.
    """

    candidates: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    rows = db.conn.execute(
        "SELECT id, title, preview_path, list_json FROM works"
    ).fetchall()
    for row in rows:
        try:
            item = json.loads(row["list_json"] or "{}")
        except (TypeError, ValueError):
            continue
        identity = QQIdentity(
            _identity_value(item.get("group_key"), "legacy"),
            _identity_value(item.get("group_label"), "legacy"),
            _identity_value(item.get("account_key")),
            _identity_value(item.get("account_label")),
        )
        key = work_identity_key(identity, row["title"])
        if not key[1] or not key[2]:
            continue
        candidates.setdefault(key, []).append(
            (int(row["id"]), str(row["preview_path"] or ""))
        )

    index: dict[tuple[str, str, str], int] = {}
    for key, values in candidates.items():
        if len(values) == 1:
            index[key] = values[0][0]
            continue
        # During an interrupted upgrade, prefer the historical flat path.
        historical = [
            work_id
            for work_id, preview in values
            if not preview.replace("\\", "/").startswith(f"{key[0]}/")
        ]
        if len(historical) == 1:
            index[key] = historical[0]
    return index


def repair_interrupted_upgrade_duplicates(db) -> dict[str, int]:
    """Remove only the duplicate rows created by the strict-ingest upgrade.

    A pair is eligible only when its logical identity and parsed prompt/model
    match exactly, with one historical flat preview and one new grouped
    preview. Physical image files are intentionally preserved.
    """

    works = db.conn.execute(
        "SELECT id, title, preview_path, list_json FROM works"
    ).fetchall()
    image_rows = db.conn.execute(
        """
        SELECT work_id, prompt_text, model
        FROM work_images
        WHERE page_index = 0
        """
    ).fetchall()
    prompt_by_id = {
        int(row["work_id"]): (
            str(row["prompt_text"] or ""),
            str(row["model"] or ""),
        )
        for row in image_rows
    }
    grouped: dict[
        tuple[str, str, str],
        list[tuple[int, str, dict[str, Any]]],
    ] = {}
    for row in works:
        try:
            item = json.loads(row["list_json"] or "{}")
        except (TypeError, ValueError):
            continue
        identity = QQIdentity(
            _identity_value(item.get("group_key"), "legacy"),
            _identity_value(item.get("group_label"), "legacy"),
            _identity_value(item.get("account_key")),
            _identity_value(item.get("account_label")),
        )
        key = work_identity_key(identity, row["title"])
        if not key[1] or not key[2]:
            continue
        grouped.setdefault(key, []).append(
            (
                int(row["id"]),
                str(row["preview_path"] or "").replace("\\", "/"),
                item,
            )
        )

    duplicate_to_canonical: dict[int, int] = {}
    for key, values in grouped.items():
        if len(values) != 2:
            continue
        grouped_prefix = f"{key[0]}/"
        historical = [
            value for value in values if not value[1].startswith(grouped_prefix)
        ]
        upgraded = [
            value for value in values if value[1].startswith(grouped_prefix)
        ]
        if len(historical) != 1 or len(upgraded) != 1:
            continue
        old_id = historical[0][0]
        new_id = upgraded[0][0]
        old_prompt = prompt_by_id.get(old_id, ("", ""))
        new_prompt = prompt_by_id.get(new_id, ("", ""))
        if not old_prompt[0] or old_prompt != new_prompt:
            continue
        source_name = _identity_value(upgraded[0][2].get("source_file"))
        source_stem = _identity_value(Path(source_name).stem).casefold()
        if not source_name or source_stem != key[2]:
            continue
        duplicate_to_canonical[new_id] = old_id

    if not duplicate_to_canonical:
        return {"detected": 0, "removed": 0}

    try:
        db.conn.execute("BEGIN")
        for duplicate_id, canonical_id in duplicate_to_canonical.items():
            db.conn.execute(
                "UPDATE qq_ingest_files SET work_id = ? WHERE work_id = ?",
                (canonical_id, duplicate_id),
            )
        duplicate_ids = list(duplicate_to_canonical)
        for offset in range(0, len(duplicate_ids), 400):
            chunk = duplicate_ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            for table in (
                "work_images",
                "works_fts",
                "prompt_fts",
                "prompt_work_fts",
                "works",
            ):
                id_column = "id" if table == "works" else "work_id"
                db.conn.execute(
                    f"DELETE FROM {table} "
                    f"WHERE {id_column} IN ({placeholders})",
                    chunk,
                )
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    return {
        "detected": len(duplicate_to_canonical),
        "removed": len(duplicate_to_canonical),
    }


def ensure_ingest_schema(db) -> None:
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qq_ingest_files(
            source_id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            parser_version TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            group_key TEXT NOT NULL,
            group_label TEXT NOT NULL,
            account_key TEXT NOT NULL,
            account_label TEXT NOT NULL,
            work_id INTEGER,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qq_ingest_status "
        "ON qq_ingest_files(status, reason)"
    )
    db.conn.commit()


def load_ingest_cache(db) -> dict[str, tuple[int, int, str, str]]:
    ensure_ingest_schema(db)
    rows = db.conn.execute(
        """
        SELECT source_id, file_size, mtime_ns, parser_version, status
        FROM qq_ingest_files
        """
    ).fetchall()
    return {
        str(row["source_id"]): (
            int(row["file_size"]),
            int(row["mtime_ns"]),
            str(row["parser_version"]),
            str(row["status"]),
        )
        for row in rows
    }


def record_ingest_rows(db, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    db.conn.executemany(
        """
        INSERT INTO qq_ingest_files(
            source_id, source_name, file_size, mtime_ns, parser_version,
            status, reason, group_key, group_label, account_key,
            account_label, work_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_name = excluded.source_name,
            file_size = excluded.file_size,
            mtime_ns = excluded.mtime_ns,
            parser_version = excluded.parser_version,
            status = excluded.status,
            reason = excluded.reason,
            group_key = excluded.group_key,
            group_label = excluded.group_label,
            account_key = excluded.account_key,
            account_label = excluded.account_label,
            work_id = excluded.work_id,
            updated_at = excluded.updated_at
        """,
        rows,
    )
    db.conn.commit()


def import_parsed_nai(
    *,
    src: Path,
    identity: QQIdentity,
    parsed: NAIParseResult,
    images_root: Path,
    hardlink: bool,
    work_id_override: int | None = None,
    commit: bool = True,
) -> int:
    if not parsed.accepted:
        raise ValueError(f"refusing non-NAI image: {parsed.reason}")
    if not identity.group_key or not identity.account_key:
        raise ValueError("group/account identity missing")

    src_id = source_id(src)
    if work_id_override is not None:
        work_id = int(work_id_override)
    elif identity.group_key == "legacy":
        # Preserve the original crawler identity so the first strict scan
        # enriches an accepted legacy work instead of duplicating it.
        work_id = stable_work_id(
            "qq",
            identity.account_key,
            str(src.resolve()),
        )
    else:
        work_id = stable_work_id(
            "qq",
            identity.group_key,
            identity.account_key,
            src_id,
        )
    ext = src.suffix.lower() or ".png"
    if ext == ".jpeg":
        ext = ".jpg"
    group_safe = sanitize_filename(identity.group_key)
    account_safe = sanitize_filename(identity.account_key)
    preview_rel = (
        f"{group_safe}/{account_safe}/{work_id}_p0{ext}".replace("\\", "/")
    )
    dest = images_root / preview_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.exists()
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        if hardlink:
            try:
                if dest.exists():
                    dest.unlink()
                dest.hardlink_to(src)
            except OSError:
                shutil.copy2(src, dest)
        else:
            shutil.copy2(src, dest)

    storage_metadata = parsed.storage_metadata()
    try:
        upsert_local_work(
            GALLERY_QQ,
            work_id=work_id,
            title=src.stem,
            caption=f"来自 {identity.group_label} / {identity.account_label}",
            tags=(
                f"qqgroup,NAI,group:{identity.group_key},"
                f"account:{identity.account_key}"
            ),
            prompt_text=parsed.prompt,
            model=parsed.model,
            ai_json=json.dumps(storage_metadata, ensure_ascii=False),
            preview_rel=preview_rel,
            account_key=identity.account_key,
            account_label=identity.account_label,
            source=(
                f"qq-crawler:{identity.group_key}:{identity.account_key}"
            ),
            extra={
                "source_file": src.name,
                "group_key": identity.group_key,
                "group_label": identity.group_label,
                "metadata_source": parsed.metadata_source,
                "metadata_parser": PARSER_VERSION,
                "nai_seed": parsed.seed,
                "nai_model": parsed.model,
            },
            commit=commit,
        )
    except Exception:
        if not existed:
            from library_writer import discard_unreferenced_file

            discard_unreferenced_file(GALLERY_QQ, preview_rel, dest)
        raise
    return work_id


def rebuild_group_index(db) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT list_json FROM works WHERE list_json IS NOT NULL"
    ).fetchall()
    group_counts: Counter[str] = Counter()
    account_counts: Counter[tuple[str, str]] = Counter()
    group_labels: dict[str, str] = {}
    account_labels: dict[tuple[str, str], str] = {}
    for row in rows:
        try:
            item = json.loads(row[0] or "{}")
        except (TypeError, ValueError):
            continue
        group_key = _identity_value(item.get("group_key"), "legacy")
        group_label = _identity_value(
            item.get("group_label"),
            "历史未分组" if group_key == "legacy" else group_key,
        )
        account_key = _identity_value(item.get("account_key"))
        if not account_key:
            continue
        account_label = _identity_value(
            item.get("account_label"),
            account_key,
        )
        group_counts[group_key] += 1
        account_counts[(group_key, account_key)] += 1
        group_labels[group_key] = group_label
        account_labels[(group_key, account_key)] = account_label

    groups: list[dict[str, Any]] = []
    for group_key in sorted(
        group_counts,
        key=lambda key: (-group_counts[key], group_labels[key]),
    ):
        filter_key = f"group:{group_key}"
        members = [
            pair for pair in account_counts if pair[0] == group_key
        ]
        drop_only = bool(members) and all(pair[1] == "local-drop" for pair in members)
        groups.append(
            {
                "key": filter_key,
                "label": group_labels[group_key],
                "count": group_counts[group_key],
                "kind": "folder" if drop_only else "group",
                "group_key": group_key,
            }
        )
        if drop_only:
            continue
        for pair in sorted(
            members,
            key=lambda value: (
                -account_counts[value],
                account_labels[value],
            ),
        ):
            account_key = pair[1]
            groups.append(
                {
                    "key": f"account:{group_key}:{account_key}",
                    "label": account_labels[pair],
                    "count": account_counts[pair],
                    "kind": "account",
                    "parent_key": filter_key,
                    "group_key": group_key,
                    "account_key": account_key,
                }
            )
    return groups


def revalidate_existing_batch(
    db,
    images_root: Path,
    *,
    limit: int = 500,
    apply: bool = False,
) -> dict[str, Any]:
    """Revalidate visible legacy works; rejected source files stay untouched."""

    rows = db.conn.execute(
        """
        SELECT id, list_json, detail_json, preview_path
        FROM works
        WHERE COALESCE(
            json_extract(list_json, '$.metadata_parser'),
            ''
        ) <> ?
        ORDER BY id
        LIMIT ?
        """,
        (PARSER_VERSION, max(1, int(limit))),
    ).fetchall()
    images_base = Path(images_root).resolve()
    decisions: list[
        tuple[Any, dict[str, Any], dict[str, Any], NAIParseResult]
    ] = []
    reasons: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = {}

    for row in rows:
        try:
            item = json.loads(row["list_json"] or "{}")
        except (TypeError, ValueError):
            item = {}
        try:
            detail = json.loads(decompress_if_needed(row["detail_json"]) or "{}")
        except (TypeError, ValueError):
            detail = {}
        preview_rel = str(row["preview_path"] or "").replace("\\", "/")
        candidate = (images_base / preview_rel).resolve()
        account_key = _identity_value(item.get("account_key"))
        if not preview_rel or not candidate.is_relative_to(images_base):
            parsed = NAIParseResult(False, "unsafe_preview_path")
        elif not candidate.is_file():
            parsed = NAIParseResult(False, "source_missing")
        elif not account_key:
            parsed = NAIParseResult(False, "identity_missing")
        elif looks_like_comfy(candidate):
            parsed = NAIParseResult(False, "comfy_path")
        else:
            parsed = parse_nai_image(candidate)
        decisions.append((row, item, detail, parsed))
        if not parsed.accepted:
            reasons[parsed.reason] += 1
            bucket = examples.setdefault(parsed.reason, [])
            if len(bucket) < 10:
                bucket.append(
                    {
                        "file": Path(preview_rel).name,
                        "account": _identity_value(
                            item.get("account_label"),
                            account_key,
                        ),
                    }
                )

    accepted = sum(parsed.accepted for _, _, _, parsed in decisions)
    rejected = len(decisions) - accepted
    if apply and decisions:
        try:
            db.conn.execute("BEGIN")
            rejected_ids = [
                int(row["id"])
                for row, _, _, parsed in decisions
                if not parsed.accepted
            ]
            for offset in range(0, len(rejected_ids), 400):
                chunk = rejected_ids[offset : offset + 400]
                placeholders = ",".join("?" for _ in chunk)
                for table in (
                    "work_images",
                    "works_fts",
                    "prompt_fts",
                    "prompt_work_fts",
                    "works",
                ):
                    db.conn.execute(
                        f"DELETE FROM {table} "
                        f"WHERE {'id' if table == 'works' else 'work_id'} "
                        f"IN ({placeholders})",
                        chunk,
                    )
            accepted_ids: list[int] = []
            for row, item, detail, parsed in decisions:
                work_id = int(row["id"])
                if not parsed.accepted:
                    continue
                accepted_ids.append(work_id)

                group_key = _identity_value(
                    item.get("group_key"),
                    "legacy",
                )
                group_label = _identity_value(
                    item.get("group_label"),
                    "历史未分组" if group_key == "legacy" else group_key,
                )
                account_key = _identity_value(item.get("account_key"))
                account_label = _identity_value(
                    item.get("account_label"),
                    account_key,
                )
                item.update(
                    {
                        "AI_type": "NAI",
                        "ai_type": "NAI",
                        "caption": f"来自 {group_label} / {account_label}",
                        "tags": (
                            f"qqgroup,NAI,group:{group_key},"
                            f"account:{account_key}"
                        ),
                        "group_key": group_key,
                        "group_label": group_label,
                        "metadata_source": parsed.metadata_source,
                        "metadata_parser": PARSER_VERSION,
                        "nai_seed": parsed.seed,
                        "nai_model": parsed.model,
                    }
                )
                detail_work = detail.get("work")
                if not isinstance(detail_work, dict):
                    detail_work = {}
                detail_work.update(item)
                detail["work"] = detail_work
                images = detail.get("images")
                if not isinstance(images, list) or not images:
                    images = [{"page_index": 0}]
                image = images[0] if isinstance(images[0], dict) else {}
                image.update(
                    {
                        "image_type": "NAI",
                        "model": parsed.model,
                        "ai_json": json.dumps(
                            parsed.storage_metadata(),
                            ensure_ascii=False,
                        ),
                        "prompt_text": parsed.prompt,
                    }
                )
                images[0] = image
                detail["images"] = images
                db.conn.execute(
                    """
                    UPDATE works
                    SET caption = ?, tags = ?, ai_type = 'NAI',
                        list_json = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (
                        item["caption"],
                        item["tags"],
                        json.dumps(item, ensure_ascii=False),
                        compress_text(json.dumps(detail, ensure_ascii=False)),
                        work_id,
                    ),
                )
                db.conn.execute(
                    """
                    UPDATE work_images
                    SET image_type = 'NAI', model = ?, ai_json = ?,
                        prompt_text = ?
                    WHERE work_id = ? AND page_index = 0
                    """,
                    (
                        parsed.model or None,
                        compress_text(image["ai_json"]),
                        parsed.prompt,
                        work_id,
                    ),
                )
            db._sync_work_fts_batch(accepted_ids)
            db._sync_prompt_fts_batch(accepted_ids)
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise

        from db import _invalidate_scope_total_cache

        _invalidate_scope_total_cache()

    remaining = int(
        db.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM works
            WHERE COALESCE(
                json_extract(list_json, '$.metadata_parser'),
                ''
            ) <> ?
            """,
            (PARSER_VERSION,),
        ).fetchone()["c"]
    )
    return {
        "ok": True,
        "apply": bool(apply),
        "parser_version": PARSER_VERSION,
        "processed": len(decisions),
        "accepted": accepted,
        "rejected": rejected,
        "rejected_by_reason": dict(reasons.most_common()),
        "examples": examples,
        "remaining": remaining,
        "source_files_deleted": 0,
    }
