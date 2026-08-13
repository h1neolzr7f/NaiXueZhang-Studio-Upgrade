"""本地试生成图库：按源作品分组，封面 + 组内多图。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

logger = logging.getLogger("generated_gallery")

from paths import DeferredDataPath, data_dir

_SCAN_CACHE: dict[str, Any] = {"sig": None, "items": None, "groups": None}
_LEGACY_META_MIGRATED = False
META_SUFFIX = ".meta.json"
STEM_RE = re.compile(r"^(\d{8})_(\d{6})(?:_(\d+))?$")

DATA_DIR = DeferredDataPath(lambda: data_dir())
GENERATED_DIR = DeferredDataPath(lambda: data_dir() / "generated")
_CACHE_DIR = DeferredDataPath(lambda: data_dir() / "cache")
_ITEMS_CACHE_FILE = DeferredDataPath(lambda: data_dir() / "cache" / "generated_gallery.items.json")
_GROUPS_CACHE_FILE = DeferredDataPath(lambda: data_dir() / "cache" / "generated_gallery.groups.json")


class GeneratedArtifactBusy(RuntimeError):
    """Post-processing still owns the requested generated artifact."""

def _load_persistent_items_cache() -> list[dict[str, Any]] | None:
    try:
        using_legacy_cache = not _ITEMS_CACHE_FILE.exists()
        cache_file = (
            GENERATED_DIR / ".items_cache.json"
            if using_legacy_cache
            else _ITEMS_CACHE_FILE
        )
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                signature = tuple(data.get("sig") or ())
                if len(signature) >= 3:
                    if int(signature[2]) != GENERATED_DIR.stat().st_mtime_ns:
                        if not using_legacy_cache:
                            return None
                        current = _scan_signature()
                        if tuple(signature[:2]) != tuple(current[:2]):
                            return None
                elif signature != _scan_signature():
                    return None
            items = data.get("items") if isinstance(data, dict) else data
            if isinstance(items, list):
                return items
    except Exception:
        pass
    return None

def _save_persistent_items_cache(items: list[dict[str, Any]]) -> None:
    try:
        _ITEMS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "items": items,
            "sig": list(_scan_signature()),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write_text(
            _ITEMS_CACHE_FILE,
            json.dumps(payload, ensure_ascii=False, indent=0) + "\n",
        )
    except Exception:
        pass


def _is_primary_stem(stem: str) -> bool:
    """试生成原图 id（排除后处理 *_final / *_up2x 等衍生文件）。"""
    return bool(STEM_RE.match(str(stem or "").strip()))


def _paths_for_stem(stem: str) -> list[Path]:
    """主图 + meta + 后处理衍生 png。"""
    safe = Path(stem).stem
    if not _is_primary_stem(safe):
        return []
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    base = GENERATED_DIR / f"{safe}.png"
    _add(base)
    _add(_meta_path(base))
    _add(_thumb_path(base))
    for pattern in (
        f"{safe}_up*x.png",
        f"{safe}_up*x_clean.png",
        f"{safe}_clean.png",
        f"{safe}_final.png",
        f"{safe}_mosaic.png",
        f"{safe}_up*_mosaic.png",
    ):
        for path in GENERATED_DIR.glob(pattern):
            _add(path)
            meta = _meta_path(path)
            if meta.exists():
                _add(meta)
    return paths


def _meta_path(png_path: Path) -> Path:
    return png_path.with_suffix(png_path.suffix + ".meta.json")


def _thumb_path(png_path: Path) -> Path:
    """缩略图路径：同名 .thumb.webp"""
    return png_path.with_suffix(".thumb.webp")


def _thumb_url(png_path: Path) -> str:
    """缩略图的 URL 路径"""
    thumb = _thumb_path(png_path)
    if thumb.exists():
        return f"/data/generated/{thumb.name}"
    return f"/data/generated/{png_path.name}"


def ensure_thumbnail(png_path: Path) -> bool:
    """为 PNG 生成 webp 缩略图（最长边 320px），避免生成图库浏览时加载全尺寸 PNG。"""
    thumb = _thumb_path(png_path)
    if thumb.exists():
        return True
    # 跳过已知损坏的文件（之前尝试失败过）
    broken_marker = png_path.with_suffix(png_path.suffix + ".broken_thumb")
    if broken_marker.exists():
        return False
    try:
        from PIL import Image
        img = Image.open(png_path)
        w, h = img.size
        max_edge = 320
        if max(w, h) > max_edge:
            if w >= h:
                new_w = max_edge
                new_h = max(64, int(h * max_edge / w / 8) * 8)
            else:
                new_h = max_edge
                new_w = max(64, int(w * max_edge / h / 8) * 8)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(thumb, "WEBP", quality=80, method=4)
        return True
    except Exception:
        # 创建损坏标记，避免后续反复尝试
        try:
            broken_marker.write_text("")
        except Exception:
            pass
        logger.warning("Skipped corrupted PNG (thumbnail): %s", png_path.name)
        return False


def _parse_stem(stem: str) -> dict[str, Any]:
    m = STEM_RE.match(stem)
    if not m:
        return {"work_id": None, "created_at": ""}
    date_part, time_part, work_part = m.group(1), m.group(2), m.group(3)
    created_at = ""
    try:
        created_at = datetime.strptime(
            f"{date_part}_{time_part}", "%Y%m%d_%H%M%S"
        ).isoformat(timespec="seconds")
    except ValueError:
        pass
    work_id = int(work_part) if work_part else None
    return {"work_id": work_id, "created_at": created_at}


def _read_meta(png_path: Path) -> dict[str, Any] | None:
    meta_path = _meta_path(png_path)
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _item_from_png(png_path: Path) -> dict[str, Any] | None:
    if not png_path.is_file() or png_path.suffix.lower() != ".png":
        return None
    stem = png_path.stem
    if not _is_primary_stem(stem):
        return None
    parsed = _parse_stem(stem)
    meta = _read_meta(png_path) or {}
    item = {
        "id": stem,
        "filename": png_path.name,
        "image_url": f"/data/generated/{png_path.name}",
        "thumb_url": _thumb_url(png_path),
        "work_id": meta.get("work_id", parsed["work_id"]),
        "source_gallery_id": str(meta.get("source_gallery_id") or "site"),
        "created_at": meta.get("created_at") or parsed["created_at"],
        "model": meta.get("model", ""),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "steps": meta.get("steps"),
        "free_eligible": meta.get("free_eligible"),
        "processed_url": meta.get("processed_url") or "",
        "pipeline_at": meta.get("pipeline_at") or "",
        "pipeline_steps": meta.get("pipeline_steps") or [],
        "prompt_snapshot": meta.get("prompt_snapshot") or None,
        "generation_series_id": str(meta.get("generation_series_id") or ""),
        "source_title": str(meta.get("source_title") or "").strip(),
        "source_thumb": str(meta.get("source_thumb") or "").strip(),
        "remote_work_id": str(meta.get("remote_work_id") or "").strip(),
    }
    if not item["created_at"]:
        try:
            item["created_at"] = datetime.fromtimestamp(
                png_path.stat().st_mtime
            ).isoformat(timespec="seconds")
        except OSError:
            item["created_at"] = ""
    return item


def register_generated(
    filename: str,
    *,
    work_id: int | None = None,
    source_gallery_id: str = "site",
    model: str = "",
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    free_eligible: bool | None = None,
    prompt_snapshot: dict[str, Any] | None = None,
    generation_series_id: str = "",
    source_title: str = "",
    source_thumb: str = "",
    remote_work_id: str = "",
) -> dict[str, Any]:
    png_path = GENERATED_DIR / filename
    if not png_path.exists():
        raise FileNotFoundError(f"生成图不存在: {filename}")
    # 生成缩略图
    ensure_thumbnail(png_path)
    parsed = _parse_stem(png_path.stem)
    existing = _read_meta(png_path) or {}
    payload = {
        **existing,
        "id": png_path.stem,
        "filename": filename,
        "work_id": (
            work_id
            if work_id is not None
            else existing.get("work_id", parsed.get("work_id"))
        ),
        "created_at": existing.get("created_at")
        or datetime.now().isoformat(timespec="seconds"),
    }
    optional = {
        "model": model,
        "width": width,
        "height": height,
        "steps": steps,
        "free_eligible": free_eligible,
        "generation_series_id": str(generation_series_id or ""),
        "source_gallery_id": str(source_gallery_id or "site"),
        "source_title": str(source_title or "").strip(),
        "source_thumb": str(source_thumb or "").strip(),
        "remote_work_id": str(remote_work_id or "").strip(),
    }
    payload.update(
        {key: value for key, value in optional.items() if value not in ("", None)}
    )
    if isinstance(prompt_snapshot, dict) and prompt_snapshot:
        payload["prompt_snapshot"] = prompt_snapshot
    atomic_write_text(
        _meta_path(png_path),
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    invalidate_scan_cache()
    # Incremental cache update: append new item without full rescan
    try:
        if isinstance(_SCAN_CACHE.get("items"), list):
            new_item = _item_from_png(png_path)
            if new_item:
                # dedup
                _SCAN_CACHE["items"] = [it for it in _SCAN_CACHE["items"] if it.get("id") != new_item["id"]]
                _SCAN_CACHE["items"].append(new_item)
                _SCAN_CACHE["items"].sort(key=lambda x: x.get("created_at") or "", reverse=True)
                _save_persistent_items_cache(_SCAN_CACHE["items"])
    except Exception:
        pass
    return payload


def _scan_signature() -> tuple[int, float, int]:
    """Cheap signature: only count primary PNGs + their mtime. Uses glob to skip non-PNG files.
    
    Optimized: uses directory mtime as a fast pre-filter to avoid full traversal when nothing changed.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    # 快速路径：目录自身 mtime 没变且缓存有效，跳过全量遍历
    try:
        dir_mtime_ns = GENERATED_DIR.stat().st_mtime_ns
        cached = _SCAN_CACHE.get("sig")
        if (
            isinstance(cached, (tuple, list))
            and len(cached) >= 3
            and int(cached[2]) == dir_mtime_ns
        ):
            # 目录没变过，用旧 sig 即可
            return cached
    except OSError:
        pass
    
    count = 0
    latest = 0.0
    try:
        for png_path in GENERATED_DIR.glob("*.png"):
            if _is_primary_stem(png_path.stem):
                count += 1
                try:
                    latest = max(latest, png_path.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    try:
        directory_version = GENERATED_DIR.stat().st_mtime_ns
    except OSError:
        directory_version = 0
    return count, latest, directory_version


def invalidate_scan_cache() -> None:
    _SCAN_CACHE["sig"] = None
    _SCAN_CACHE["items"] = None
    _SCAN_CACHE["groups"] = None
    try:
        from post_pipeline import invalidate_backlog_cache

        invalidate_backlog_cache()
    except Exception:
        pass


def scan_all_items(*, force: bool = False) -> list[dict[str, Any]]:
    cached_signature = _SCAN_CACHE.get("sig")
    try:
        directory_unchanged = (
            isinstance(cached_signature, (tuple, list))
            and len(cached_signature) >= 3
            and int(cached_signature[2]) == GENERATED_DIR.stat().st_mtime_ns
        )
    except OSError:
        directory_unchanged = False
    if (
        not force
        and isinstance(_SCAN_CACHE.get("items"), list)
        and directory_unchanged
    ):
        return list(_SCAN_CACHE["items"])

    # Try persistent cache first (fast load, no FS scan)
    if not force:
        cached = _load_persistent_items_cache()
        if cached is not None:
            _SCAN_CACHE["items"] = cached
            _SCAN_CACHE["sig"] = _scan_signature()  # refresh sig without full rebuild
            _SCAN_CACHE["groups"] = None
            return list(cached)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    sig = _scan_signature()

    items: list[dict[str, Any]] = []
    for png_path in GENERATED_DIR.glob("*.png"):
        # 全量扫描时补生成缺失的缩略图（非阻塞）
        _thumb_path(png_path)  # 仅触发路径构造，不生成
        item = _item_from_png(png_path)
        if item:
            items.append(item)
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    _SCAN_CACHE["sig"] = sig
    _SCAN_CACHE["items"] = items
    _SCAN_CACHE["groups"] = None
    _save_persistent_items_cache(items)
    return items


_THUMBNAIL_MIGRATED = False


def migrate_legacy_meta() -> int:
    """为无 meta 的旧 PNG 补写 sidecar。"""
    global _LEGACY_META_MIGRATED
    if _LEGACY_META_MIGRATED:
        return 0
    count = 0
    for png_path in GENERATED_DIR.glob("*.png"):
        if _meta_path(png_path).exists():
            continue
        item = _item_from_png(png_path)
        if not item:
            continue
        _meta_path(png_path).write_text(
            json.dumps(
                {
                    "id": item["id"],
                    "filename": item["filename"],
                    "work_id": item.get("work_id"),
                    "created_at": item.get("created_at"),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        count += 1
    _LEGACY_META_MIGRATED = True
    return count


def ensure_all_thumbnails() -> int:
    """为所有没有缩略图的 PNG 批量补生成 webp 缩略图（并行，最多 4 线程）。"""
    pending: list[Path] = []
    for png_path in GENERATED_DIR.glob("*.png"):
        if not _is_primary_stem(png_path.stem):
            continue
        thumb = _thumb_path(png_path)
        if thumb.exists():
            continue
        broken_marker = png_path.with_suffix(png_path.suffix + ".broken_thumb")
        if broken_marker.exists():
            continue
        pending.append(png_path)
    if not pending:
        return 0
    count = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_map = {pool.submit(ensure_thumbnail, p): p for p in pending}
        for fut in as_completed(fut_map):
            if fut.result():
                count += 1
    if count:
        logger.info("Generated %d/%d thumbnails", count, len(pending))
    return count


def _group_key(
    work_id: int | None,
    *,
    source_gallery_id: str = "site",
    generation_series_id: str = "",
) -> str:
    base = (
        f"run:{generation_series_id}:{work_id if work_id else 'standalone'}"
        if generation_series_id
        else (str(work_id) if work_id else "standalone")
    )
    gallery_id = str(source_gallery_id or "site").strip() or "site"
    return base if gallery_id == "site" else f"gallery:{gallery_id}:{base}"


def group_key_for_item(item: dict[str, Any]) -> str:
    return _group_key(
        item.get("work_id"),
        source_gallery_id=str(item.get("source_gallery_id") or "site"),
        generation_series_id=str(item.get("generation_series_id") or "").strip(),
    )


# 缓存每个 work_id 的 source_title/source_thumb，避免 N+1 查询
_SOURCE_CACHE: dict[tuple[str, int], dict[str, str]] = {}
_SOURCE_CACHE_TTL = 300.0
_SOURCE_CACHE_AT: float = 0.0


def _public_source_thumb_url(local_path: str, *, gallery_id: str = "site") -> str:
    """Map a stored local_path to the public static URL for this gallery."""
    path = str(local_path or "").replace("\\", "/").lstrip("/")
    if not path:
        return ""
    for prefix in ("data/images/", "data/", "images/"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break
    gid = str(gallery_id or "site").strip() or "site"
    if gid in {"codex", "qqgroup"}:
        base = f"/data/gallery/{gid}/"
    else:
        base = "/data/images/"
    return f"{base}{path}"


def get_cached_source_info(
    work_id: int,
    db_getter,
    *,
    gallery_id: str = "site",
) -> dict[str, str]:
    """批量获取 work 的标题和封面，带缓存，避免 N+1 查询。"""
    import time
    global _SOURCE_CACHE, _SOURCE_CACHE_AT
    now = time.time()
    if now - _SOURCE_CACHE_AT > _SOURCE_CACHE_TTL:
        _SOURCE_CACHE = {}
        _SOURCE_CACHE_AT = now
    gid = str(gallery_id or "site").strip() or "site"
    cache_key = (gid, int(work_id))
    if cache_key in _SOURCE_CACHE:
        return dict(_SOURCE_CACHE[cache_key])
    try:
        detail = db_getter(int(work_id))
        work = (detail or {}).get("work") or {}
        title = str(work.get("title") or work.get("caption") or f"作品 {work_id}")[:80]
        thumb = ""
        images = (detail or {}).get("images") or []
        if images:
            local_path = str(images[0].get("local_path") or "").replace("\\", "/").lstrip("/")
            if local_path:
                thumb = _public_source_thumb_url(local_path, gallery_id=gid)
            elif images[0].get("file_name"):
                thumb = _public_source_thumb_url(
                    str(images[0]["file_name"]), gallery_id=gid
                )
        result = {"title": title, "thumb": thumb}
        _SOURCE_CACHE[cache_key] = result
        return dict(result)
    except Exception:
        return {"title": f"作品 {work_id}", "thumb": ""}


def invalidate_source_cache(
    work_id: int | None = None,
    *,
    gallery_id: str | None = None,
) -> None:
    global _SOURCE_CACHE
    if work_id is not None:
        numeric_id = int(work_id)
        if gallery_id is not None:
            key = (str(gallery_id or "site").strip() or "site", numeric_id)
            _SOURCE_CACHE.pop(key, None)
        else:
            _SOURCE_CACHE = {
                key: value
                for key, value in _SOURCE_CACHE.items()
                if key[1] != numeric_id
            }
    else:
        _SOURCE_CACHE = {}


def _load_persistent_groups_cache() -> list[dict[str, Any]] | None:
    try:
        validated_signature: tuple[Any, ...] | None = None
        using_legacy_cache = not _GROUPS_CACHE_FILE.exists()
        cache_file = (
            GENERATED_DIR / ".groups_cache.json"
            if using_legacy_cache
            else _GROUPS_CACHE_FILE
        )
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                signature = tuple(data.get("sig") or ())
                if len(signature) >= 3:
                    if int(signature[2]) != GENERATED_DIR.stat().st_mtime_ns:
                        if not using_legacy_cache:
                            return None
                        current = _scan_signature()
                        if tuple(signature[:2]) != tuple(current[:2]):
                            return None
                        validated_signature = tuple(current)
                    else:
                        validated_signature = signature
                else:
                    current = _scan_signature()
                    if signature != current:
                        return None
                    validated_signature = tuple(current)
            items = data.get("groups") if isinstance(data, dict) else data
            if isinstance(items, list):
                if validated_signature is not None:
                    _SCAN_CACHE["sig"] = validated_signature
                return items
    except Exception:
        pass
    return None


def _save_persistent_groups_cache(groups: list[dict[str, Any]]) -> None:
    try:
        _GROUPS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "groups": groups,
            "sig": list(_scan_signature()),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write_text(
            _GROUPS_CACHE_FILE,
            json.dumps(payload, ensure_ascii=False, indent=0) + "\n",
        )
    except Exception:
        pass


def list_groups(*, force: bool = False) -> list[dict[str, Any]]:
    cached_signature = _SCAN_CACHE.get("sig")
    try:
        directory_unchanged = (
            isinstance(cached_signature, (tuple, list))
            and len(cached_signature) >= 3
            and int(cached_signature[2]) == GENERATED_DIR.stat().st_mtime_ns
        )
    except OSError:
        directory_unchanged = False
    if (
        not force
        and isinstance(_SCAN_CACHE.get("groups"), list)
        and directory_unchanged
    ):
        return list(_SCAN_CACHE["groups"])

    # Try persistent groups cache
    if not force:
        cached = _load_persistent_groups_cache()
        if cached is not None:
            _SCAN_CACHE["groups"] = cached
            return list(cached)

    sig = _scan_signature()

    groups: dict[str, dict[str, Any]] = {}
    for item in scan_all_items(force=force):
        wid = item.get("work_id")
        source_gallery_id = str(item.get("source_gallery_id") or "site")
        key = group_key_for_item(item)
        bucket = groups.get(key)
        if not bucket:
            bucket = {
                "group_id": key,
                "work_id": wid,
                "source_gallery_id": source_gallery_id,
                "count": 0,
                "cover_url": item["image_url"],
                "cover_thumb": item.get("thumb_url") or item["image_url"],
                "cover_id": item["id"],
                "latest_at": item.get("created_at") or "",
                "source_title": str(item.get("source_title") or "").strip(),
                "source_thumb": str(item.get("source_thumb") or "").strip(),
                "remote_work_id": str(item.get("remote_work_id") or "").strip(),
                "items": [],
            }
            groups[key] = bucket
        if not bucket.get("source_title") and item.get("source_title"):
            bucket["source_title"] = str(item.get("source_title") or "").strip()
        if not bucket.get("source_thumb") and item.get("source_thumb"):
            bucket["source_thumb"] = str(item.get("source_thumb") or "").strip()
        if not bucket.get("remote_work_id") and item.get("remote_work_id"):
            bucket["remote_work_id"] = str(item.get("remote_work_id") or "").strip()
        bucket["items"].append(item)
        bucket["count"] += 1
        created = item.get("created_at") or ""
        if created >= bucket["latest_at"]:
            bucket["latest_at"] = created
            bucket["cover_url"] = item["image_url"]
            bucket["cover_thumb"] = item.get("thumb_url") or item["image_url"]
            bucket["cover_id"] = item["id"]
    result = list(groups.values())
    result.sort(key=lambda g: g.get("latest_at") or "", reverse=True)
    for g in result:
        g["items"].sort(key=lambda x: x.get("created_at") or "", reverse=True)
        del g["items"]
    _SCAN_CACHE["sig"] = sig
    _SCAN_CACHE["groups"] = result
    _save_persistent_groups_cache(result)
    if isinstance(_SCAN_CACHE.get("items"), list):
        pass
    else:
        scan_all_items(force=force)
    return result
def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trash_root() -> Path:
    return GENERATED_DIR / ".trash"


def _assert_artifacts_idle(image_ids: list[str]) -> None:
    try:
        from post_pipeline import active_pipeline_ids
    except ImportError:
        return
    active = set(active_pipeline_ids())
    busy = next((image_id for image_id in image_ids if image_id in active), "")
    if busy:
        raise GeneratedArtifactBusy(
            f"post-processing still owns generated image: {busy}"
        )


def _move_artifacts_to_trash(
    image_ids: list[str],
    *,
    kind: str,
    group_id: str = "",
) -> dict[str, Any]:
    _assert_artifacts_idle(image_ids)
    trash_id = uuid.uuid4().hex
    entry = _trash_root() / trash_id
    entry.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for image_id in image_ids:
            for source in _paths_for_stem(image_id):
                if not source.exists() or source.name in seen:
                    continue
                seen.add(source.name)
                target = entry / source.name
                digest = _artifact_sha256(source)
                source.replace(target)
                files.append(
                    {
                        "name": source.name,
                        "sha256": digest,
                        "size": target.stat().st_size,
                    }
                )
        if not files:
            raise FileNotFoundError("no generated artifacts found")
        manifest = {
            "version": 1,
            "trash_id": trash_id,
            "kind": kind,
            "group_id": group_id,
            "image_ids": image_ids,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "files": files,
        }
        (entry / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        for moved in files:
            source = entry / moved["name"]
            if source.exists():
                source.replace(GENERATED_DIR / moved["name"])
        shutil.rmtree(entry, ignore_errors=True)
        raise
    invalidate_scan_cache()
    return {
        "ok": True,
        "trash_id": trash_id,
        "undo_available": True,
        "removed_files": len(files),
        "file_count": len(files),
    }


def list_deleted() -> list[dict[str, Any]]:
    root = _trash_root()
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for entry in root.iterdir():
        manifest_path = entry / "manifest.json"
        if not entry.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        result.append(
            {
                **manifest,
                "file_count": len(manifest.get("files") or []),
            }
        )
    result.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return result


def restore_deleted(trash_id: str) -> dict[str, Any]:
    safe = str(trash_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", safe):
        raise ValueError("invalid trash id")
    entry = _trash_root() / safe
    manifest_path = entry / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("trash entry not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restore_rows: list[tuple[Path, Path]] = []
    already_present_sources: list[Path] = []
    seen_names: set[str] = set()
    for row in manifest.get("files") or []:
        if not isinstance(row, dict):
            raise ValueError("invalid trash manifest row")
        name = Path(str(row.get("name") or "")).name
        if not name or name in seen_names:
            raise ValueError("invalid or duplicate trash artifact name")
        seen_names.add(name)
        source = entry / name
        target = GENERATED_DIR / name
        expected_digest = str(row.get("sha256") or "")
        if target.exists():
            if expected_digest and _artifact_sha256(target) == expected_digest:
                already_present_sources.append(source)
                continue
            raise FileExistsError(f"restore target already exists: {name}")
        if not source.is_file():
            raise FileNotFoundError(f"trash artifact missing: {name}")
        if expected_digest and _artifact_sha256(source) != expected_digest:
            raise ValueError(f"trash artifact checksum mismatch: {name}")
        restore_rows.append((source, target))

    moved: list[tuple[Path, Path]] = []
    try:
        for source, target in restore_rows:
            if target.exists():
                raise FileExistsError(f"restore target already exists: {target.name}")
            source.replace(target)
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            if target.exists() and not source.exists():
                target.replace(source)
        raise
    for source in already_present_sources:
        source.unlink(missing_ok=True)
    shutil.rmtree(entry)
    invalidate_scan_cache()
    return {
        "ok": True,
        "trash_id": safe,
        "restored_files": len(moved),
        "already_present_files": len(already_present_sources),
    }


def delete_item(image_id: str) -> dict[str, Any]:
    safe_id = Path(image_id).stem
    if not _is_primary_stem(safe_id):
        raise ValueError("invalid generated image id")
    png_path = GENERATED_DIR / f"{safe_id}.png"
    if not png_path.is_file():
        raise FileNotFoundError(f"generated image not found: {image_id}")
    meta = _read_meta(png_path) or {}
    moved = _move_artifacts_to_trash([safe_id], kind="item")
    return {
        **moved,
        "id": safe_id,
        "work_id": meta.get("work_id"),
        "message": "moved to recycle bin",
    }


def _coerce_work_id(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        return None


def _matches_group(item: dict[str, Any], group_id: str) -> bool:
    base_group_id = str(group_id or "").strip()
    expected_gallery_id = "site"
    if base_group_id.startswith("gallery:"):
        parts = base_group_id.split(":", 2)
        if len(parts) != 3 or not parts[1]:
            return False
        expected_gallery_id, base_group_id = parts[1], parts[2]
    elif base_group_id.startswith("site:"):
        base_group_id = base_group_id.removeprefix("site:")
    if str(item.get("source_gallery_id") or "site") != expected_gallery_id:
        return False
    item_work = _coerce_work_id(item.get("work_id"))
    if base_group_id == "standalone":
        return item_work is None and not item.get("generation_series_id")
    if base_group_id.startswith("run:"):
        parts = base_group_id.split(":", 2)
        if len(parts) != 3:
            return False
        series_id, work_text = parts[1], parts[2]
        try:
            expected_work = None if work_text == "standalone" else int(work_text)
        except ValueError:
            return False
        return (
            str(item.get("generation_series_id") or "") == series_id
            and item_work == expected_work
        )
    # Bare work id (or gallery:{gid}:{work}): include ALL series for that work
    # so batch run:{task}:{work} still appears under the work-scoped group view.
    try:
        expected = int(base_group_id)
    except ValueError:
        return False
    return item_work == expected


def get_group(
    group_id: str,
    *,
    rescan_if_missing: bool = True,
) -> dict[str, Any] | None:
    items = scan_all_items()
    matched = [item for item in items if _matches_group(item, group_id)]
    if not matched and rescan_if_missing:
        matched = [
            item
            for item in scan_all_items(force=True)
            if _matches_group(item, group_id)
        ]
    if not matched:
        return None
    matched.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    cover = matched[0]
    return {
        "group_id": group_id,
        "work_id": cover.get("work_id"),
        "source_gallery_id": str(cover.get("source_gallery_id") or "site"),
        "count": len(matched),
        "cover_url": cover["image_url"],
        "cover_thumb": cover.get("thumb_url") or cover["image_url"],
        "latest_at": cover.get("created_at") or "",
        "items": matched,
    }


def delete_group(group_id: str) -> dict[str, Any]:
    group = get_group(group_id)
    if not group:
        raise FileNotFoundError("generated group not found")
    image_ids = [
        str(item.get("id") or "").strip()
        for item in (group.get("items") or [])
        if str(item.get("id") or "").strip()
    ]
    moved = _move_artifacts_to_trash(
        image_ids,
        kind="group",
        group_id=group_id,
    )
    return {
        **moved,
        "group_id": group_id,
        "deleted": len(image_ids),
        "extra_removed": 0,
        "message": f"moved {len(image_ids)} generated images to recycle bin",
    }
