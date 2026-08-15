import asyncio
import hashlib
import json
import sys
import tempfile
import threading
import time
import subprocess
from datetime import datetime
from typing import Any
from pathlib import Path
import httpx

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from server_shared import (
    CONFIG,
    DB,
    ROOT,
    DATA_DIR,
    WEB_DIR,
    CDN_URL,
    GALLERY_SCOPE,
    GALLERY_LOCAL_ONLY,
    TAG_TRANSLATOR,
    _CDN_CLIENT,
    _CDN_MISS_CACHE,
    _CDN_MISS_TTL,
    record_cdn_miss,
)
from favorites import (
    add as fav_add,
    has as fav_has,
    list_ids as fav_list_ids,
    list_refs as list_refs_favorites,
    remove as fav_remove,
    summary as fav_summary,
    toggle as fav_toggle,
)
from production_queue import (
    add as queue_add,
    clear as queue_clear,
    has as queue_has,
    list_ids as queue_list_ids,
    list_refs as list_refs_queue,
    remove as queue_remove,
    summary as queue_summary,
    toggle as queue_toggle,
)
from paths import canonical_path, path_is_within, storage_paths
from atomic_io import atomic_write_bytes
from gallery_cache import cached
from nai_image_metadata import NAIParseResult, parse_nai_image
from scripts.gallery_import_common import (
    sanitize_filename,
    stable_work_id,
    upsert_local_work,
)
from db_compression import compress_text, decompress_if_needed
from user_prefs import load_prefs
from static_asset_security import is_disallowed_web_asset
from gallery_catalog import (
    GALLERY_IDS,
    get_db as get_gallery_db,
    get_spec as get_gallery_spec,
    list_group_keys,
    normalize_gallery_id,
    public_gallery_list,
    serialize_gallery_payload,
)

router = APIRouter()

_CONFIG_CACHE_TTL = 300.0

GENERATED_DIR = DATA_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _gallery_db(gallery_id: str):
    """Reuse the process-wide site DB; open dedicated DBs for other galleries."""
    gid = normalize_gallery_id(gallery_id)
    return DB if gid == "site" else get_gallery_db(gid)


def _safe_child_file(root: Path, raw_path: str) -> Path:
    """Resolve a browser-supplied path and keep it inside root."""
    normalized = str(raw_path or "").replace("\\", "/").lstrip("/")
    if not normalized or "\x00" in normalized:
        raise HTTPException(status_code=404, detail="not found")
    root_resolved = canonical_path(root)
    candidate = canonical_path(root_resolved / normalized)
    if candidate == root_resolved or not path_is_within(candidate, root_resolved):
        raise HTTPException(status_code=404, detail="not found")
    return candidate


def _build_api_config() -> dict:
    default_query = CONFIG.get("search_query", "")
    calendar = DB.list_rank_calendar()
    return {
        "asset_base_url": "/data/images/",
        "page_size": CONFIG.get("page_size", 60),
        "list_mode": "infinite",
        "announce_enabled": False,
        "ads_enabled": False,
        "config_version": "local-mirror",
        "default_query": default_query,
        "dataset_name": CONFIG.get("dataset_name", "local"),
        "gallery_title_zh": "Pixiv NAI 本地图库",
        "gallery_title_en": "Pixiv NAI Gallery",
        "local_mirror": True,
        "tag_translate_enabled": True,
        "default_lang": "zh",
        "gallery_desc_zh": "从 Pixiv 发现候选作品，经本地 NovelAI 元数据严格验证后入库。",
        "gallery_desc_en": "Candidates are discovered on Pixiv and admitted only after strict local NovelAI metadata verification.",
        "gallery_local_only": GALLERY_LOCAL_ONLY,
        "gallery_scope": GALLERY_SCOPE,
        "gallery_scope_label_zh": "全站本地 NAI",
        "gallery_scope_label_en": "Locally indexed works",
        "gallery_scope_query": "",
        "available_years": calendar.get("years") or [],
        "available_months": calendar.get("months") or [],
        # Absolute filesystem paths are server-only operational details. The
        # browser only needs the stable logical targets accepted by
        # /api/storage/open.
        "storage_targets": sorted(_STORAGE_OPEN_TARGETS),
        "gallery_nai_only_default": bool(CONFIG.get("gallery_nai_only_default", True)),
        "user_prefs": load_prefs(),
    }


@router.get("/api/config")
def api_config() -> JSONResponse:
    payload = cached("api_config", _CONFIG_CACHE_TTL, _build_api_config)
    return JSONResponse(
        payload,
        headers={"Cache-Control": f"private, max-age={int(_CONFIG_CACHE_TTL)}"},
    )


@router.get("/api/galleries")
def api_galleries() -> dict:
    return {"ok": True, "items": public_gallery_list()}


@router.get("/api/galleries/{gallery_id}/groups")
def api_gallery_groups(gallery_id: str) -> dict:
    gid = normalize_gallery_id(gallery_id)
    return {"ok": True, "gallery_id": gid, "items": list_group_keys(gid)}


_DROP_MAX_BYTES = 64 * 1024 * 1024
_DROP_MAX_FILES = 250
_DROP_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_DROP_GALLERIES = frozenset({"codex", "qqgroup"})
_DROP_LOCKS_GUARD = threading.Lock()
_DROP_LOCKS: dict[str, threading.Lock] = {}


def _drop_lock(gid: str) -> threading.Lock:
    with _DROP_LOCKS_GUARD:
        lock = _DROP_LOCKS.get(gid)
        if lock is None:
            lock = threading.Lock()
            _DROP_LOCKS[gid] = lock
        return lock


def _plain_folder_key(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("group:"):
        text = text.split(":", 1)[1]
    return text[:80]


def _invalidate_group_index(gid: str) -> None:
    try:
        get_gallery_db(gid).set_state(f"group_index:{gid}", "")
    except Exception:
        pass


def _refresh_group_index(gid: str) -> None:
    _invalidate_group_index(gid)
    try:
        list_group_keys(gid)
    except Exception:
        pass


def _existing_folder_names(gid: str) -> set[str]:
    db = get_gallery_db(gid)

    def read() -> set[str]:
        rows = db.conn.execute(
            """
            SELECT DISTINCT
              COALESCE(
                NULLIF(json_extract(list_json, '$.group_key'), ''),
                NULLIF(json_extract(list_json, '$.category'), '')
              ) AS k
            FROM works
            """
        ).fetchall()
        names = set()
        for row in rows:
            name = _plain_folder_key(str(row["k"] or ""))
            if name:
                names.add(name)
        return names

    try:
        return db._run(read)
    except Exception:
        return set()


def _unique_drop_folder(gid: str, base: str) -> str:
    used = _existing_folder_names(gid)
    used.discard("")
    name = base
    n = 2
    while name in used:
        name = f"{base} ·{n}"
        n += 1
    return name


def _existing_work_folder(gid: str, work_id: int) -> str:
    db = get_gallery_db(gid)

    def read() -> str:
        row = db.conn.execute(
            "SELECT list_json FROM works WHERE id = ?",
            (work_id,),
        ).fetchone()
        if not row or not row["list_json"]:
            return ""
        try:
            item = json.loads(row["list_json"] or "{}")
        except Exception:
            return ""
        if not isinstance(item, dict):
            return ""
        return str(item.get("group_key") or item.get("category") or "").strip()

    try:
        return db._run(read)
    except Exception:
        return ""


def _import_drop_files(
    gid: str,
    category: str,
    spec,
    buffered: list[tuple[str, bytes]],
    *,
    keep_existing_folder: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for name, data in buffered:
        ext = Path(name).suffix.lower() or ".png"
        if ext == ".jpeg":
            ext = ".jpg"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            parsed = parse_nai_image(tmp_path)
        except Exception:
            parsed = NAIParseResult(False, "parse_error")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        if not parsed.accepted:
            rejected.append(
                {"file": name, "reason": parsed.reason or "nai_metadata_missing"}
            )
            continue
        digest = hashlib.sha256(data).hexdigest()
        work_id = stable_work_id("drop", digest)
        folder = category
        existed = False
        if keep_existing_folder:
            previous = _existing_work_folder(gid, work_id)
            if previous:
                folder = previous
                existed = True
        category_safe = sanitize_filename(folder)
        if (
            not category_safe
            or category_safe in {".", ".."}
            or any(part in {".", ".."} for part in Path(category_safe).parts)
        ):
            category_safe = "未分类"
        preview_rel = f"{category_safe}/{work_id}_p0{ext}".replace("\\", "/")
        try:
            dest = _safe_child_file(spec.images_dir, preview_rel)
        except HTTPException:
            category_safe = "未分类"
            preview_rel = f"{category_safe}/{work_id}_p0{ext}".replace("\\", "/")
            dest = _safe_child_file(spec.images_dir, preview_rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_size != len(data):
            atomic_write_bytes(dest, data)
        extra = {
            "group_key": folder,
            "group_label": folder,
        }
        qq_account = ""
        qq_label = ""
        if gid == "qqgroup":
            extra["account_key"] = "local-drop"
            extra["account_label"] = "本地拖入"
            qq_account = "local-drop"
            qq_label = "本地拖入"
        upsert_local_work(
            gid,
            work_id=work_id,
            title=Path(name).stem[:80] or "dropped",
            caption=f"本地拖入导入 · 文件夹 {folder}",
            tags=f"drop,local,NAI,category:{folder}",
            prompt_text=parsed.prompt,
            model=parsed.model,
            ai_json=json.dumps(parsed.storage_metadata(), ensure_ascii=False),
            preview_rel=preview_rel,
            category=folder,
            account_key=qq_account,
            account_label=qq_label,
            source=f"local-drop:{folder}",
            extra=extra,
        )
        accepted.append(
            {
                "file": name,
                "work_id": work_id,
                "category": folder,
                "folder": folder,
                "existing": existed,
            }
        )
    return accepted, rejected


@router.post("/api/gallery/{gallery_id}/import-drop")
async def api_gallery_import_drop(
    gallery_id: str,
    category: str = Form(""),
    files: list[UploadFile] = File(...),
) -> dict:
    """Import locally dropped images after strict NovelAI metadata parsing.

    Only local-import galleries (codex / qqgroup) accept drops.  Every file is
    parsed for NovelAI provenance; non-NAI images are rejected and reported.
    An empty category creates a new folder named after this drop batch.
    """
    gid = normalize_gallery_id(gallery_id)
    if gid not in _DROP_GALLERIES:
        raise HTTPException(
            status_code=400,
            detail="import-drop is only supported for local-import galleries (codex/qqgroup)",
        )
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    explicit = bool(str(category or "").strip())
    category = str(category or "").strip()[:80] or datetime.now().strftime("拖入 %m-%d %H:%M:%S")
    spec = get_gallery_spec(gid)
    buffered: list[tuple[str, bytes]] = []
    rejected: list[dict[str, Any]] = []
    total_bytes = 0
    for upload in files[:_DROP_MAX_FILES]:
        name = str(upload.filename or "image.png").strip() or "image.png"
        try:
            data = await upload.read(_DROP_MAX_BYTES + 1)
        except Exception:
            rejected.append({"file": name, "reason": "read_failed"})
            continue
        if not data:
            rejected.append({"file": name, "reason": "empty"})
            continue
        if len(data) > _DROP_MAX_BYTES:
            rejected.append({"file": name, "reason": "too_large"})
            continue
        if total_bytes + len(data) > _DROP_MAX_TOTAL_BYTES:
            rejected.append({"file": name, "reason": "batch_too_large"})
            continue
        total_bytes += len(data)
        buffered.append((name, data))
    if len(files) > _DROP_MAX_FILES:
        rejected.append(
            {
                "file": "",
                "reason": f"too_many_files_truncated:{_DROP_MAX_FILES}",
            }
        )

    def job() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        with _drop_lock(gid):
            folder = category
            if not explicit:
                folder = _unique_drop_folder(gid, folder)
            accepted_rows, parse_rejected = _import_drop_files(
                gid,
                folder,
                spec,
                buffered,
                keep_existing_folder=not explicit,
            )
            used = [str(item.get("folder") or folder) for item in accepted_rows]
            if accepted_rows and all(item.get("existing") for item in accepted_rows):
                folder = used[0]
            _refresh_group_index(gid)
            return folder, accepted_rows, parse_rejected

    folder, accepted, more_rejected = await asyncio.to_thread(job)
    rejected.extend(more_rejected)
    return {
        "ok": True,
        "gallery_id": gid,
        "category": folder,
        "folder": folder,
        "folder_key": f"group:{folder}",
        "accepted": accepted,
        "rejected": rejected,
    }


def _work_folder_names(item: dict[str, Any]) -> set[str]:
    names = set()
    for key in ("category", "group_key"):
        value = _plain_folder_key(str(item.get(key) or ""))
        if value:
            names.add(value)
    return names


def _merge_gallery_folders(gid: str, source_keys: list[str], target_key: str) -> dict[str, Any]:
    target = _plain_folder_key(target_key)
    sources = {_plain_folder_key(key) for key in source_keys if _plain_folder_key(key)}
    sources.discard("")
    if not target:
        raise HTTPException(status_code=400, detail="target folder is required")
    if not sources:
        raise HTTPException(status_code=400, detail="source folders are required")
    sources.discard(target)
    db = get_gallery_db(gid)
    moved = 0

    def action() -> None:
        nonlocal moved
        rows = db.conn.execute("SELECT id, tags, list_json, detail_json FROM works").fetchall()
        for row in rows:
            try:
                item = json.loads(row["list_json"] or "{}")
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if not (_work_folder_names(item) & sources):
                continue
            item["category"] = target
            item["group_key"] = target
            item["group_label"] = target
            item["source"] = f"local-drop:{target}"
            if gid == "qqgroup":
                item["account_key"] = item.get("account_key") or "local-drop"
                item["account_label"] = item.get("account_label") or "本地拖入"
            tags = [
                part
                for part in str(row["tags"] or item.get("tags") or "").split(",")
                if part.strip() and not part.strip().startswith("category:")
            ]
            tags.append(f"category:{target}")
            tag_text = ",".join(dict.fromkeys(tags))
            item["tags"] = tag_text
            item["caption"] = f"本地拖入导入 · 文件夹 {target}"
            new_detail = None
            detail_blob = row["detail_json"]
            if detail_blob:
                try:
                    detail = json.loads(decompress_if_needed(detail_blob) or "{}")
                except Exception:
                    detail = None
                if isinstance(detail, dict):
                    work = detail.get("work")
                    if isinstance(work, dict):
                        work["category"] = target
                        work["group_key"] = target
                        work["group_label"] = target
                        work["source"] = f"local-drop:{target}"
                        work["tags"] = tag_text
                        work["caption"] = item["caption"]
                        if gid == "qqgroup":
                            work["account_key"] = work.get("account_key") or "local-drop"
                            work["account_label"] = work.get("account_label") or "本地拖入"
                        detail["work"] = work
                    new_detail = compress_text(json.dumps(detail, ensure_ascii=False))
            if new_detail is not None:
                db.conn.execute(
                    "UPDATE works SET tags = ?, caption = ?, list_json = ?, detail_json = ? WHERE id = ?",
                    (tag_text, item["caption"], json.dumps(item, ensure_ascii=False), new_detail, row["id"]),
                )
            else:
                db.conn.execute(
                    "UPDATE works SET tags = ?, caption = ?, list_json = ? WHERE id = ?",
                    (tag_text, item["caption"], json.dumps(item, ensure_ascii=False), row["id"]),
                )
            db._sync_work_fts(row["id"])
            moved += 1
        db.conn.commit()

    with _drop_lock(gid):
        db._run(action)
        _refresh_group_index(gid)
    return {
        "ok": True,
        "gallery_id": gid,
        "folder": target,
        "folder_key": f"group:{target}",
        "moved": moved,
        "sources": sorted(sources),
    }


@router.get("/api/gallery/{gallery_id}/index/status")
def api_gallery_index_status(gallery_id: str) -> dict:
    from gallery_index import index_status

    gid = normalize_gallery_id(gallery_id)
    db = _gallery_db(gid)
    return index_status(db.conn, gid)


@router.post("/api/gallery/{gallery_id}/index/incremental")
def api_gallery_index_incremental(
    gallery_id: str,
    payload: dict = Body(default_factory=dict),
) -> dict:
    from gallery_index import run_incremental

    gid = normalize_gallery_id(gallery_id)
    spec = get_gallery_spec(gid)
    db = _gallery_db(gid)
    raw_ids = payload.get("work_ids") if isinstance(payload, dict) else None
    work_ids: list[int] | None = None
    if isinstance(raw_ids, list):
        work_ids = [int(item) for item in raw_ids if str(item).strip().lstrip("-").isdigit()]
    visual = True if not isinstance(payload, dict) else bool(payload.get("visual", True))
    result = run_incremental(db, work_ids, visual=visual, images_dir=spec.images_dir)
    result["gallery_id"] = gid
    return result


@router.get("/api/gallery/{gallery_id}/duplicates")
def api_gallery_duplicates(
    gallery_id: str,
    kind: str = Query("exact"),
) -> dict:
    from gallery_index import find_exact_duplicates, find_near_duplicates

    gid = normalize_gallery_id(gallery_id)
    db = _gallery_db(gid)
    mode = str(kind or "exact").strip().lower()
    if mode == "near":
        groups = find_near_duplicates(db.conn)
    else:
        groups = find_exact_duplicates(db.conn)
    return {"ok": True, "gallery_id": gid, "kind": mode, "groups": groups}


@router.get("/api/gallery/{gallery_id}/similar")
def api_gallery_similar(
    gallery_id: str,
    work_id: int = Query(..., ge=1),
    page_index: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=80),
) -> dict:
    from gallery_index import find_similar

    gid = normalize_gallery_id(gallery_id)
    db = _gallery_db(gid)
    payload = find_similar(
        db.conn,
        work_id=int(work_id),
        page_index=int(page_index),
        limit=int(limit),
    )
    payload["ok"] = True
    payload["gallery_id"] = gid
    return payload


@router.post("/api/gallery/{gallery_id}/folders/merge")
async def api_gallery_merge_folders(gallery_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    gid = normalize_gallery_id(gallery_id)
    if gid not in _DROP_GALLERIES:
        raise HTTPException(
            status_code=400,
            detail="folder merge is only supported for local-import galleries (codex/qqgroup)",
        )
    sources = payload.get("source_keys") or payload.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list):
        raise HTTPException(status_code=400, detail="source_keys must be a list")
    target = str(payload.get("target_key") or payload.get("target") or "").strip()
    return await asyncio.to_thread(
        _merge_gallery_folders,
        gid,
        [str(item) for item in sources],
        target,
    )


_STORAGE_OPEN_TARGETS = {
    "images": "images_dir",
    "data": "data_dir",
    "generated": "generated_dir",
    "root": "project_root",
}


@router.post("/api/storage/open")
def api_storage_open(target: str = "images") -> dict:
    """Open a local storage folder in Windows Explorer."""
    key = _STORAGE_OPEN_TARGETS.get(str(target or "").strip().lower())
    if not key:
        raise HTTPException(
            status_code=400,
            detail="invalid target; choose images/data/generated/root",
        )
    paths = storage_paths(CONFIG, ROOT)
    folder = Path(paths[key])
    if not folder.exists():
        raise HTTPException(
            status_code=404, detail="folder does not exist"
        )
    if sys.platform != "win32":
        return {
            "ok": True,
            "opened": False,
            "target": str(target or "images").strip().lower(),
            "message": "Only Windows can open folders automatically",
        }
    subprocess.Popen(["explorer", str(folder)])
    return {
        "ok": True,
        "opened": True,
        "target": str(target or "images").strip().lower(),
        "message": "Opened in Explorer",
    }


@router.post("/api/generated/reveal/{image_id}")
def api_generated_reveal(image_id: str) -> dict:
    stem = Path(str(image_id or "").strip()).stem
    if not stem:
        raise HTTPException(status_code=400, detail="image_id cannot be empty")
    path = _safe_child_file(GENERATED_DIR, f"{stem}.png")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="generated image not found")
    if sys.platform != "win32":
        return {
            "ok": True,
            "opened": False,
            "path": path.name,
            "message": "Only Windows can reveal files automatically",
        }
    subprocess.Popen(["explorer", "/select,", str(path)])
    return {
        "ok": True,
        "opened": True,
        # Do not leak absolute filesystem paths to the browser.
        "path": path.name,
        "message": f"Revealed file: {path.name}",
    }


@router.get("/api/tags/dict")
def api_tag_dict() -> JSONResponse:
    TAG_TRANSLATOR.reload_if_stale()
    return JSONResponse(
        TAG_TRANSLATOR.mapping,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/tags/translate")
def api_tags_translate(tags: str = "") -> dict:
    items = [part.strip() for part in tags.split(",") if part.strip()]
    return {
        "items": TAG_TRANSLATOR.translate_many(items),
        "dict_size": TAG_TRANSLATOR.size,
    }


@router.get("/api/favorites")
def api_favorites_summary() -> dict:
    return fav_summary()


@router.get("/api/favorites/works")
def api_favorites_works(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    gallery_id: str = Query("site"),
) -> dict:
    gid = normalize_gallery_id(gallery_id)
    ids = [
        int(item["work_id"])
        for item in list_refs_favorites()
        if item.get("gallery_id") == gid
    ]
    return serialize_gallery_payload(
        _gallery_db(gid).search_favorite_works(
            ids,
            q=q,
            page=page,
            page_size=page_size,
        ),
        gid,
    )


@router.get("/api/favorites/{work_id}")
def api_favorite_status(work_id: int, gallery_id: str = Query("site")) -> dict:
    gid = normalize_gallery_id(gallery_id)
    return {"ok": True, "gallery_id": gid, "work_id": str(work_id), "favorited": fav_has(work_id, gid)}


@router.post("/api/favorites/{work_id}")
def api_favorite_add(work_id: int, gallery_id: str = Query("site")) -> dict:
    return fav_add(work_id, normalize_gallery_id(gallery_id))


@router.delete("/api/favorites/{work_id}")
def api_favorite_remove(work_id: int, gallery_id: str = Query("site")) -> dict:
    return fav_remove(work_id, normalize_gallery_id(gallery_id))


@router.post("/api/favorites/{work_id}/toggle")
def api_favorite_toggle(work_id: int, gallery_id: str = Query("site")) -> dict:
    return fav_toggle(work_id, normalize_gallery_id(gallery_id))


@router.get("/api/queue")
def api_queue_summary() -> dict:
    return queue_summary()


@router.get("/api/queue/works")
def api_queue_works(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    gallery_id: str = Query("site"),
) -> dict:
    gid = normalize_gallery_id(gallery_id)
    ids = [
        int(item["work_id"])
        for item in list_refs_queue()
        if item.get("gallery_id") == gid
    ]
    return serialize_gallery_payload(
        _gallery_db(gid).search_favorite_works(
            ids,
            q=q,
            page=page,
            page_size=page_size,
        ),
        gid,
    )


@router.post("/api/queue/clear")
def api_queue_clear() -> dict:
    return queue_clear()


@router.get("/api/queue/{work_id}")
def api_queue_status(work_id: int, gallery_id: str = Query("site")) -> dict:
    gid = normalize_gallery_id(gallery_id)
    return {"ok": True, "gallery_id": gid, "work_id": str(work_id), "queued": queue_has(work_id, gid)}


@router.post("/api/queue/{work_id}")
def api_queue_add(
    work_id: int,
    payload: dict = Body(default_factory=dict),
    gallery_id: str = Query("site"),
) -> dict:
    note = str((payload or {}).get("note") or "")
    gid = normalize_gallery_id((payload or {}).get("gallery_id") or gallery_id)
    return queue_add(work_id, note=note, gallery_id=gid)


@router.delete("/api/queue/{work_id}")
def api_queue_remove(work_id: int, gallery_id: str = Query("site")) -> dict:
    return queue_remove(work_id, normalize_gallery_id(gallery_id))


@router.post("/api/queue/{work_id}/toggle")
def api_queue_toggle(work_id: int, gallery_id: str = Query("site")) -> dict:
    return queue_toggle(work_id, normalize_gallery_id(gallery_id))


@router.get("/api/ai_works_search")
def api_search(
    q: str = "",
    prompt: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    sort: str = "new",
    time_range: str = "all",
    skip_total: bool = Query(False),
    nai_only: bool | None = Query(None),
    gallery_id: str = Query("site"),
    group: str = Query(""),
    seed: int = Query(0, ge=0),
) -> dict:
    try:
        gid = normalize_gallery_id(gallery_id)
        spec = get_gallery_spec(gid)
        db = _gallery_db(gid)
        local_scope = spec.local_scope
        # Product invariant: this package never exposes SD/Comfy/unknown rows,
        # even when an older database or a forged query parameter is supplied.
        nai_filter = True
        result = db.search_works(
            q=q,
            prompt=prompt,
            page=page,
            page_size=page_size,
            sort=sort,
            time_range=time_range,
            local_scope=local_scope,
            skip_total=skip_total,
            nai_only=nai_filter,
            group=group,
            seed=seed,
        )
        for item in result.get("items") or []:
            if isinstance(item, dict):
                item["gallery_id"] = gid
        result["gallery_id"] = gid
        return serialize_gallery_payload(result, gid)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "page": page,
                "page_size": page_size,
                "total": 0,
                "items": [],
                "error": "search_failed",
                "message": str(exc),
                "message_zh": f"搜索失败：{exc}",
                "message_en": f"Search failed: {exc}",
            },
        )


def _monthly_rank_scope() -> str:
    return GALLERY_SCOPE if GALLERY_LOCAL_ONLY else ""


def _api_monthly_rank(
    *,
    period: str = "current",
    month: str = "",
    q: str = "",
    prompt: str = "",
    page: int = 1,
    page_size: int = 60,
    skip_total: bool = False,
    nai_only: bool | None = None,
) -> dict:
    try:
        nai_filter = True
        return DB.search_monthly_rank(
            period=period,
            month=month,
            q=q,
            prompt=prompt,
            page=page,
            page_size=page_size,
            local_scope=_monthly_rank_scope(),
            skip_total=skip_total,
            nai_only=nai_filter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "page": page,
                "page_size": page_size,
                "total": 0,
                "items": [],
                "error": "search_failed",
                "message": str(exc),
                "message_zh": f"搜索失败：{exc}",
                "message_en": f"Search failed: {exc}",
            },
        )


@router.get("/api/rank/monthly/real")
def api_rank_monthly_real(
    q: str = "",
    prompt: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    skip_total: bool = Query(False),
) -> dict:
    return _api_monthly_rank(
        period="current",
        q=q,
        prompt=prompt,
        page=page,
        page_size=page_size,
        skip_total=skip_total,
    )


@router.get("/api/rank/monthly/fixed")
def api_rank_monthly_fixed(
    month: str = "",
    q: str = "",
    prompt: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    skip_total: bool = Query(False),
) -> dict:
    return _api_monthly_rank(
        month=month,
        q=q,
        prompt=prompt,
        page=page,
        page_size=page_size,
        skip_total=skip_total,
    )


@router.get("/api/rank/monthly")
def api_rank_monthly(
    period: str = "current",
    q: str = "",
    prompt: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    skip_total: bool = Query(False),
) -> dict:
    return _api_monthly_rank(
        period=period,
        q=q,
        prompt=prompt,
        page=page,
        page_size=page_size,
        skip_total=skip_total,
    )


def _work_scope_guard(work_id: int, gallery_id: str = "site") -> None:
    gid = normalize_gallery_id(gallery_id)
    spec = get_gallery_spec(gid)
    db = _gallery_db(gid)
    if spec.local_scope and not db.work_in_scope(
        work_id, spec.local_scope
    ):
        raise HTTPException(status_code=404, detail="work not in local dataset")


@router.get("/api/work/{work_id}")
def api_work(work_id: int, gallery_id: str = Query("site")) -> dict:
    gid = normalize_gallery_id(gallery_id)
    _work_scope_guard(work_id, gid)
    detail = _gallery_db(gid).get_work_detail(work_id)
    if not detail:
        raise HTTPException(status_code=404, detail="work not found")
    detail["gallery_id"] = gid
    return serialize_gallery_payload(detail, gid)


@router.get("/api/ai_work/{work_id}")
def api_ai_work_legacy(work_id: int, gallery_id: str = Query("site")) -> dict:
    """Legacy detail alias kept for older gallery builds and saved links."""
    return api_work(work_id, gallery_id)


@router.get("/api/work/{work_id}/lite")
def api_work_lite(work_id: int, gallery_id: str = Query("site")) -> JSONResponse:
    gid = normalize_gallery_id(gallery_id)
    _work_scope_guard(work_id, gid)
    payload = cached(
        f"work_lite:{gid}:{work_id}",
        180.0,
        lambda: _gallery_db(gid).get_work_lite(work_id),
    )
    if not payload:
        raise HTTPException(status_code=404, detail="work not found")
    return JSONResponse(
        serialize_gallery_payload({**payload, "gallery_id": gid}, gid),
        headers={"Cache-Control": "private, max-age=120"},
    )


# 图库素材内容按路径基本不可变（重发布覆盖同路径的场景极少），给一天缓存，
# 避免每次进页面对每张图都发一次条件请求（200 图列表 = 200 次往返）。
_IMAGE_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}
# generated/ 下的图会被流水线重跑以同文件名覆盖，只给短缓存。
_GENERATED_CACHE_HEADERS = {"Cache-Control": "private, max-age=300"}


def _image_response(path: Path) -> FileResponse:
    return FileResponse(path, headers=_IMAGE_CACHE_HEADERS)


@router.get("/data/generated/{filename}")
def serve_generated(filename: str) -> FileResponse:
    path = _safe_child_file(GENERATED_DIR, filename)
    if path.exists() and path.is_file():
        return FileResponse(path, headers=_GENERATED_CACHE_HEADERS)
    # 与 serve_image 一致：允许兄弟扩展名命中（如历史 .webp/.jpg 产物），
    # 避免前端写死 .png 时非 PNG 生成图 404。
    stem = Path(filename)
    if stem.suffix:
        for alt_ext in (".png", ".webp", ".jpg", ".jpeg"):
            if alt_ext.lower() == stem.suffix.lower():
                continue
            try:
                alt_path = _safe_child_file(GENERATED_DIR, stem.with_suffix(alt_ext).as_posix())
            except Exception:
                continue
            if alt_path.exists() and alt_path.is_file():
                return FileResponse(alt_path, headers=_GENERATED_CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="generated image not found")


@router.get("/data/images/{image_path:path}")
def serve_image(image_path: str) -> Response:
    """Serve local cached images, falling back to the configured CDN."""
    local_path = _safe_child_file(DATA_DIR / "images", image_path)
    if local_path.exists() and local_path.is_file():
        return _image_response(local_path)

    # Mixed PNG/WebP storage (pre/post migration): try sibling extensions first
    # so a stale .webp request still hits the real .png original (and vice versa).
    stem = Path(image_path)
    if stem.suffix:
        for alt_ext in (".png", ".webp", ".jpg", ".jpeg"):
            if alt_ext.lower() == stem.suffix.lower():
                continue
            alt_rel = stem.with_suffix(alt_ext).as_posix()
            try:
                alt_path = _safe_child_file(DATA_DIR / "images", alt_rel)
            except Exception:
                continue
            if alt_path.exists() and alt_path.is_file():
                return _image_response(alt_path)
    else:
        # 无扩展名请求（旧 file_name 字段可能不带后缀）：逐个尝试已知图片扩展，
        # 前端不需要再猜测/捏造扩展名。
        for alt_ext in (".webp", ".png", ".jpg", ".jpeg"):
            alt_rel = f"{image_path}{alt_ext}"
            try:
                alt_path = _safe_child_file(DATA_DIR / "images", alt_rel)
            except Exception:
                continue
            if alt_path.exists() and alt_path.is_file():
                return _image_response(alt_path)

    # Local-first product: CDN is best-effort. Upstream/network failure must not
    # surface as 502 for a missing local file (browser treats it as hard error).
    base = str(CDN_URL or "").strip()
    if not base:
        raise HTTPException(status_code=404, detail="image not found")
    base = base if base.endswith("/") else base + "/"
    remote_url = base + image_path.lstrip("/")
    now = time.monotonic()
    miss_at = _CDN_MISS_CACHE.get(remote_url)
    if miss_at is not None and now - miss_at < _CDN_MISS_TTL:
        raise HTTPException(status_code=404, detail="image not found")
    try:
        response = _CDN_CLIENT.get(remote_url)
        if response.status_code == 200:
            _CDN_MISS_CACHE.pop(remote_url, None)
            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "image/webp"),
                headers=_IMAGE_CACHE_HEADERS,
            )
        # Any non-200 (including upstream 5xx) is treated as a soft miss.
        record_cdn_miss(remote_url, now)
        raise HTTPException(status_code=404, detail="image not found")
    except httpx.HTTPError:
        record_cdn_miss(remote_url, now)
        raise HTTPException(status_code=404, detail="image not found") from None


@router.get("/data/gallery/{gallery_id}/{image_path:path}")
def serve_gallery_image(gallery_id: str, image_path: str) -> FileResponse:
    """Serve assets from the isolated Codex/QQ gallery roots without CDN fallback."""
    requested = str(gallery_id or "").strip().lower()
    if requested not in GALLERY_IDS or requested == "site":
        raise HTTPException(status_code=404, detail="gallery image not found")
    spec = get_gallery_spec(requested)
    path = _safe_child_file(spec.images_dir, image_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="gallery image not found")
    return _image_response(path)


# Page Routes
def _serve_index_html() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(
            {"message": "web assets missing, run setup_web.ps1 first"},
            status_code=503,
        )
    return FileResponse(
        index_path,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


def _serve_web_page(filename: str) -> FileResponse:
    page = WEB_DIR / filename
    if not page.exists():
        raise HTTPException(status_code=404, detail=f"{filename} missing")
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/favorites")
def favorites_page() -> FileResponse:
    return _serve_index_html()


@router.get("/studio")
def studio_page() -> FileResponse:
    return _serve_web_page("studio.html")


# React /app/* shells are incomplete clones. Send people to the classic pages
# that already have thumbnails, Live2D 小镜, crawler tables, and drafts.
_APP_CLASSIC_PAGES = {
    "": "/",
    "gallery": "/",
    "studio": "/studio",
    "generated": "/generated",
    "butler": "/butler",
    "remix": "/remix",
    "progress": "/progress",
    "tags": "/nai-tags",
    "nai-tags": "/nai-tags",
    "pixiv": "/pixiv",
    "settings": "/settings",
    "pipeline": "/pipeline",
    "director": "/director",
    "ops": "/ops",
    "compliance": "/compliance",
}


def _classic_app_redirect(rest: str, request: Request) -> RedirectResponse | None:
    key = (rest or "").strip("/").split("/", 1)[0]
    dest = _APP_CLASSIC_PAGES.get(key)
    if dest is None:
        return None
    query = request.url.query
    return RedirectResponse(url=dest + (f"?{query}" if query else ""), status_code=303)


@router.get("/app")
def workspace_root(request: Request) -> RedirectResponse:
    return _classic_app_redirect("", request) or RedirectResponse(url="/", status_code=303)


@router.get("/app/{rest:path}", response_model=None)
def workspace_page(rest: str, request: Request) -> FileResponse | RedirectResponse:
    redirect = _classic_app_redirect(rest, request)
    if redirect is not None:
        return redirect
    return _serve_web_page("workspace.html")


@router.get("/settings")
def settings_page() -> FileResponse:
    return _serve_web_page("settings.html")


@router.get("/remix")
def remix_page() -> FileResponse:
    return _serve_web_page("remix.html")


@router.get("/generated")
def generated_page() -> FileResponse:
    page = WEB_DIR / "generated.html"
    if not page.exists():
        raise HTTPException(
            status_code=404, detail="generated gallery page missing"
        )
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/codex")
def codex_page() -> FileResponse:
    page = WEB_DIR / "codex.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="codex page missing")
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/progress")
def progress_page() -> FileResponse:
    page = WEB_DIR / "progress.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="progress page missing")
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/")
def index() -> FileResponse:
    return _serve_index_html()


@router.get("/i/{work_id}")
def work_detail_page(work_id: int) -> FileResponse:
    """Serve the SPA shell for direct /i/<work_id> links."""
    _ = work_id
    return _serve_index_html()


@router.get("/queue")
def queue_page() -> FileResponse:
    """Serve gallery SPA; frontend can open ?mode=queue."""
    return _serve_index_html()


@router.get("/{filename}")
def static_file(filename: str) -> FileResponse:
    reserved = {
        "progress",
        "generated",
        "pixiv",
        "favorites",
        "studio",
        "remix",
        "settings",
        "api",
        "ops",
        "pipeline",
        "queue",
        "tag-assets",
        "codex",
        "app",
    }
    if filename in reserved:
        raise HTTPException(status_code=404, detail="not found")
    if is_disallowed_web_asset(filename):
        raise HTTPException(status_code=404, detail="not found")
    path = WEB_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="not found")
