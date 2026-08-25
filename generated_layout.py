"""Generated-folder layout: one work directory, then images vs sidecars.

    data/generated/{work}/images/原图/*.png          # still has NAI metadata
    data/generated/{work}/images/已去元数据/*.png    # _clean / _final
    data/generated/{work}/files/*                    # meta.json, thumbs
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator

from paths import data_dir

IMAGES_DIR = "images"
FILES_DIR = "files"
ORIGINAL_DIR = "原图"
CLEANED_DIR = "已去元数据"
IMAGE_BUCKETS = (ORIGINAL_DIR, CLEANED_DIR)
STANDALONE_FOLDER = "_standalone"
RESERVED_DIR_NAMES = {".trash", ".pipeline", IMAGES_DIR, FILES_DIR}

STEM_RE = re.compile(r"^(\d{8})_(\d{6})(?:_(\d+))?$")
_DERIVED_SUFFIX_RE = re.compile(r"(?:_up\d+x|_clean|_final|_mosaic)+$", re.I)
_ILLEGAL_FOLDER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}

_INDEX_LOCK = threading.Lock()
_INDEX: dict[str, tuple[int, dict[str, str]]] = {}


def generated_root(root: Path | None = None) -> Path:
    return Path(root) if root is not None else Path(data_dir()) / "generated"


def safe_basename(name: str) -> str:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw in {".", ".."} or ".." in Path(raw).parts:
        return ""
    return Path(raw).name


def is_sidecar_name(name: str) -> bool:
    lower = str(name or "").lower()
    return (
        lower.endswith(".meta.json")
        or lower.endswith(".thumb.webp")
        or lower.endswith(".broken_thumb")
        or lower.endswith(".json")
    )


def is_image_name(name: str) -> bool:
    if is_sidecar_name(name):
        return False
    return Path(name).suffix.lower() in _IMAGE_SUFFIXES


def is_metadata_stripped_name(name: str) -> bool:
    """True for pipeline outputs that dropped NovelAI PNG metadata."""
    stem = Path(safe_basename(name) or name).stem.lower()
    return stem.endswith("_final") or stem.endswith("_clean") or "_clean" in stem


def image_bucket(name: str) -> str:
    return CLEANED_DIR if is_metadata_stripped_name(name) else ORIGINAL_DIR


def primary_stem(name: str) -> str:
    raw = Path(str(name or "").strip()).name
    if raw.lower().endswith(".png.meta.json"):
        raw = raw[: -len(".png.meta.json")]
    elif raw.lower().endswith(".thumb.webp"):
        raw = raw[: -len(".thumb.webp")]
    elif raw.lower().endswith(".png.broken_thumb"):
        raw = raw[: -len(".broken_thumb")]
        raw = Path(raw).stem
    else:
        raw = Path(raw).stem
    while True:
        nxt = _DERIVED_SUFFIX_RE.sub("", raw)
        if nxt == raw:
            break
        raw = nxt
    return raw


def is_primary_stem(stem: str) -> bool:
    return bool(STEM_RE.match(str(stem or "").strip()))


def work_id_from_name(name: str) -> int | None:
    stem = primary_stem(name)
    match = STEM_RE.match(stem)
    if not match or not match.group(3):
        return None
    try:
        return int(match.group(3))
    except (TypeError, ValueError):
        return None


def slug_title(title: str, max_len: int = 40) -> str:
    text = _ILLEGAL_FOLDER.sub("_", str(title or "").strip())
    text = re.sub(r"[\s_]+", "_", text).strip("._")
    if len(text) > max_len:
        text = text[:max_len].rstrip("._")
    return text


def _gallery_token(gallery_id: str) -> str:
    text = _ILLEGAL_FOLDER.sub("-", str(gallery_id or "site").strip()) or "site"
    text = re.sub(r"-{2,}", "-", text).strip("-")[:40] or "site"
    return text


def work_folder_prefix(work_id: int | None, gallery_id: str = "site") -> str:
    if work_id is None:
        return STANDALONE_FOLDER
    gallery = _gallery_token(gallery_id)
    if gallery == "site":
        return str(int(work_id))
    return f"{gallery}-{int(work_id)}"


def _is_work_dir(path: Path) -> bool:
    return path.is_dir() and (
        (path / IMAGES_DIR).is_dir() or (path / FILES_DIR).is_dir()
    )


def iter_work_dirs(root: Path | None = None) -> Iterator[Path]:
    base = generated_root(root)
    try:
        children = list(base.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in RESERVED_DIR_NAMES:
            continue
        if _is_work_dir(child):
            yield child


def find_work_dir(
    work_id: int | None,
    *,
    gallery_id: str = "site",
    root: Path | None = None,
) -> Path | None:
    base = generated_root(root)
    prefix = work_folder_prefix(work_id, gallery_id)
    exact = base / prefix
    if _is_work_dir(exact):
        return exact
    matches: list[Path] = []
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name == prefix or name.startswith(f"{prefix}_"):
                if _is_work_dir(child):
                    matches.append(child)
    except OSError:
        return None
    if not matches:
        return None
    matches.sort(key=lambda path: (len(path.name), path.name))
    return matches[0]


def plan_work_dir(
    work_id: int | None,
    *,
    source_title: str = "",
    source_gallery_id: str = "site",
    root: Path | None = None,
    create: bool = False,
) -> Path:
    base = generated_root(root)
    existing = find_work_dir(work_id, gallery_id=source_gallery_id, root=base)
    if existing is not None:
        dest = existing
    else:
        prefix = work_folder_prefix(work_id, source_gallery_id)
        slug = slug_title(source_title)
        name = f"{prefix}_{slug}" if slug and prefix != STANDALONE_FOLDER else prefix
        dest = base / name
    if create:
        for bucket in IMAGE_BUCKETS:
            (dest / IMAGES_DIR / bucket).mkdir(parents=True, exist_ok=True)
        (dest / FILES_DIR).mkdir(parents=True, exist_ok=True)
    return dest


def image_dir_for(png_path: Path) -> Path:
    parent = Path(png_path).parent
    if parent.name in IMAGE_BUCKETS and parent.parent.name == IMAGES_DIR:
        return parent
    if parent.name == IMAGES_DIR:
        return parent / image_bucket(png_path.name)
    return parent


def sidecar_dir_for(png_path: Path) -> Path:
    parent = Path(png_path).parent
    if parent.name in IMAGE_BUCKETS and parent.parent.name == IMAGES_DIR:
        return parent.parent.parent / FILES_DIR
    if parent.name == IMAGES_DIR:
        return parent.parent / FILES_DIR
    return parent


def planned_image_path(work: Path, name: str) -> Path:
    return work / IMAGES_DIR / image_bucket(name) / Path(name).name


def sidecar_path_for(png_path: Path, name: str) -> Path:
    safe = safe_basename(name)
    if not safe:
        raise ValueError("invalid sidecar name")
    return sidecar_dir_for(png_path) / safe


def work_root_for(path: Path, *, root: Path | None = None) -> Path | None:
    base = generated_root(root)
    try:
        rel = Path(path).resolve().relative_to(Path(base).resolve())
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[1] in {IMAGES_DIR, FILES_DIR}:
        candidate = base / parts[0]
        return candidate if _is_work_dir(candidate) else None
    return None


def common_work_dir(paths: Iterable[Path], *, root: Path | None = None) -> Path | None:
    found: set[str] = set()
    result: Path | None = None
    for path in paths:
        work = work_root_for(path, root=root)
        if work is None:
            return None
        key = str(work)
        found.add(key)
        result = work
        if len(found) > 1:
            return None
    return result


def touch_generated_root(root: Path | None = None) -> None:
    base = generated_root(root)
    try:
        base.mkdir(parents=True, exist_ok=True)
        os.utime(base, None)
    except OSError:
        pass


def invalidate_layout_index(root: Path | None = None) -> None:
    with _INDEX_LOCK:
        if root is None:
            _INDEX.clear()
            return
        _INDEX.pop(str(Path(generated_root(root))), None)


def note_generated_change(root: Path | None = None) -> None:
    base = generated_root(root)
    invalidate_layout_index(base)
    touch_generated_root(base)


def _index_for(root: Path) -> dict[str, str]:
    base = generated_root(root)
    try:
        mtime = base.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = str(Path(base))
    with _INDEX_LOCK:
        cached = _INDEX.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
    mapping: dict[str, str] = {}
    for work in iter_work_dirs(base):
        for item in _iter_work_files(work):
            if item.is_file():
                mapping[item.name] = item.relative_to(base).as_posix()
    try:
        for item in base.iterdir():
            if item.is_file() and not item.name.startswith("."):
                mapping.setdefault(item.name, item.name)
    except OSError:
        pass
    with _INDEX_LOCK:
        _INDEX[key] = (mtime, mapping)
    return mapping


def find_generated_file(name: str, *, root: Path | None = None) -> Path | None:
    base = generated_root(root)
    filename = safe_basename(name)
    if not filename:
        return None
    rel = _index_for(base).get(filename)
    if rel:
        path = base / rel
        if path.is_file():
            return path
    legacy = base / filename
    if legacy.is_file():
        return legacy
    return None


def _iter_work_files(work: Path) -> Iterator[Path]:
    files = work / FILES_DIR
    if files.is_dir():
        try:
            yield from (item for item in files.iterdir() if item.is_file())
        except OSError:
            pass
    images = work / IMAGES_DIR
    if not images.is_dir():
        return
    try:
        children = list(images.iterdir())
    except OSError:
        return
    for item in children:
        if item.is_file():
            yield item
            continue
        if item.is_dir() and item.name in IMAGE_BUCKETS:
            try:
                yield from (child for child in item.iterdir() if child.is_file())
            except OSError:
                continue


def iter_pngs(
    root: Path | None = None,
    *,
    primary_only: bool = False,
) -> Iterator[Path]:
    base = generated_root(root)
    seen: set[str] = set()
    for work in iter_work_dirs(base):
        for path in _iter_work_files(work):
            if path.suffix.lower() != ".png":
                continue
            if primary_only and not is_primary_stem(path.stem):
                continue
            seen.add(path.name)
            yield path
    try:
        items = list(base.iterdir())
    except OSError:
        return
    for path in items:
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        if path.name in seen:
            continue
        if primary_only and not is_primary_stem(path.stem):
            continue
        yield path


def glob_pngs(pattern: str, *, root: Path | None = None) -> list[Path]:
    from fnmatch import fnmatch

    return [path for path in iter_pngs(root) if fnmatch(path.name, pattern)]


def resolve_png(
    name: str,
    *,
    root: Path | None = None,
    work_id: int | None = None,
    source_title: str = "",
    source_gallery_id: str = "site",
    create_dirs: bool = False,
) -> Path:
    base = generated_root(root)
    filename = safe_basename(name)
    if not filename:
        raise ValueError("invalid generated filename")
    if Path(filename).suffix.lower() not in _IMAGE_SUFFIXES:
        filename = f"{filename}.png"
    found = find_generated_file(filename, root=base)
    if found is not None:
        return found
    primary = primary_stem(filename)
    if primary and primary != Path(filename).stem:
        primary_found = find_generated_file(f"{primary}.png", root=base)
        if primary_found is not None:
            work = work_root_for(primary_found, root=base)
            dest = (
                planned_image_path(work, filename)
                if work is not None
                else image_dir_for(primary_found) / filename
            )
            if create_dirs:
                dest.parent.mkdir(parents=True, exist_ok=True)
            return dest
    wid = work_id if work_id is not None else work_id_from_name(filename)
    work = plan_work_dir(
        wid,
        source_title=source_title,
        source_gallery_id=source_gallery_id,
        root=base,
        create=create_dirs,
    )
    dest = planned_image_path(work, filename)
    if create_dirs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        (work / FILES_DIR).mkdir(parents=True, exist_ok=True)
    return dest


def destination_png(
    name: str,
    *,
    root: Path | None = None,
    work_id: int | None = None,
    source_title: str = "",
    source_gallery_id: str = "site",
) -> Path:
    return resolve_png(
        name,
        root=root,
        work_id=work_id,
        source_title=source_title,
        source_gallery_id=source_gallery_id,
        create_dirs=True,
    )


def related_png_name(name: str) -> str:
    filename = safe_basename(name)
    lower = filename.lower()
    if lower.endswith(".png.meta.json"):
        return filename[: -len(".meta.json")]
    if lower.endswith(".thumb.webp"):
        return f"{filename[: -len('.thumb.webp')]}.png"
    if lower.endswith(".png.broken_thumb"):
        return filename[: -len(".broken_thumb")]
    if is_image_name(filename):
        return filename
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _identity_from_meta(meta: dict[str, Any], name: str) -> tuple[int | None, str, str]:
    work_id = meta.get("work_id")
    try:
        parsed_id = int(work_id) if work_id not in (None, "") else None
    except (TypeError, ValueError):
        parsed_id = None
    if parsed_id is None:
        parsed_id = work_id_from_name(name)
    title = str(meta.get("source_title") or "").strip()
    gallery = str(meta.get("source_gallery_id") or "site").strip() or "site"
    return parsed_id, title, gallery


def _collect_root_metas(root: Path, entries: list[Path]) -> dict[str, dict[str, Any]]:
    metas: dict[str, dict[str, Any]] = {}
    for path in entries:
        if not path.is_file() or not path.name.lower().endswith(".meta.json"):
            continue
        data = _read_json(path)
        if not data:
            continue
        related = related_png_name(path.name)
        key = primary_stem(related or path.name)
        if not key:
            continue
        current = metas.get(key) or {}
        if not current.get("source_title") or path.name == f"{key}.png.meta.json":
            metas[key] = {**current, **data}
        else:
            metas[key] = {**data, **current}
    return metas


def _identity_for_root_file(
    path: Path,
    root: Path,
    metas: dict[str, dict[str, Any]] | None = None,
) -> tuple[int | None, str, str]:
    related = related_png_name(path.name)
    key = primary_stem(related or path.name)
    meta: dict[str, Any] = {}
    if metas and key:
        meta = dict(metas.get(key) or {})
    if not meta and path.name.lower().endswith(".meta.json"):
        meta = _read_json(path)
    if not meta and related:
        sibling_meta = root / f"{related}.meta.json"
        if sibling_meta.is_file():
            meta = _read_json(sibling_meta)
    if not meta and key:
        primary_meta = root / f"{key}.png.meta.json"
        if primary_meta.is_file():
            meta = _read_json(primary_meta)
    return _identity_from_meta(meta, related or path.name)


def _split_work_image_buckets(work: Path) -> int:
    images = work / IMAGES_DIR
    if not images.is_dir():
        return 0
    moved = 0
    try:
        entries = list(images.iterdir())
    except OSError:
        return 0
    for path in entries:
        if not path.is_file() or not is_image_name(path.name):
            continue
        dest = images / image_bucket(path.name) / path.name
        if dest.exists():
            try:
                if dest.stat().st_size == path.stat().st_size:
                    path.unlink()
                    moved += 1
            except OSError:
                pass
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
            moved += 1
        except OSError:
            continue
    return moved


def migrate_generated_layout(root: Path | None = None) -> dict[str, Any]:
    """Move leftover flat files into per-work images/ and files/ folders."""

    base = generated_root(root)
    base.mkdir(parents=True, exist_ok=True)
    moved = 0
    skipped = 0
    errors: list[str] = []
    try:
        entries = list(base.iterdir())
    except OSError as exc:
        return {"ok": False, "moved": 0, "skipped": 0, "errors": [str(exc)]}

    metas = _collect_root_metas(base, entries)
    for path in entries:
        if path.is_dir() or path.name.startswith("."):
            continue
        if not (is_image_name(path.name) or is_sidecar_name(path.name)):
            skipped += 1
            continue
        work_id, title, gallery = _identity_for_root_file(path, base, metas)
        work = plan_work_dir(
            work_id,
            source_title=title,
            source_gallery_id=gallery,
            root=base,
            create=True,
        )
        dest_dir = (
            work / IMAGES_DIR / image_bucket(path.name)
            if is_image_name(path.name)
            else work / FILES_DIR
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if dest.exists():
            try:
                if dest.stat().st_size == path.stat().st_size:
                    path.unlink()
                    moved += 1
                    continue
            except OSError:
                pass
            skipped += 1
            continue
        try:
            shutil.move(str(path), str(dest))
            moved += 1
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            skipped += 1

    for work in iter_work_dirs(base):
        moved += _split_work_image_buckets(work)

    note_generated_change(base)
    return {
        "ok": not errors,
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
    }
