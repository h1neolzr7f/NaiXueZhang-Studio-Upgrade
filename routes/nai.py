from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse
import asyncio
from server_shared import DB
from api_schemas import NaiGenerateRequest
from nai_api import (
    token_status,
    queue_status,
    get_subscription,
    list_generation_slots,
    save_token,
    add_token_entry,
    delete_token_entry,
    check_token_pool,
)
from nai_char import clean_plain_ark_workbench_draft, extract_chars
from generated_gallery import (
    list_groups,
    get_cached_source_info,
    delete_item,
    delete_group,
    get_group,
    migrate_legacy_meta,
    restore_deleted,
    list_deleted,
)
from post_pipeline import load_config
from nai_batch import batch_status, start_studio_generate
from gallery_catalog import get_db as get_gallery_db, serialize_gallery_payload

router = APIRouter(prefix="/api")
_SUBSCRIPTION_CACHE: dict[str, object] = {}
_SUBSCRIPTION_CACHE_TTL_SEC = 15.0


def _clear_subscription_cache() -> None:
    _SUBSCRIPTION_CACHE.clear()

@router.get("/nai/status")
def api_nai_status(refresh: bool = Query(False)) -> dict:
    import time

    base = token_status()
    if not base.get("has_token"):
        return {
            **base,
            "ok": False,
            "message": "NAI token is not configured",
            "queue": queue_status(),
            "slots": [],
        }
    try:
        signature = repr(
            (
                base.get("updated_at"),
                [
                    (item.get("id"), item.get("enabled"))
                    for item in (base.get("tokens") or [])
                    if isinstance(item, dict)
                ],
            )
        )
        now = time.monotonic()
        cached = _SUBSCRIPTION_CACHE.get("value")
        if (
            not refresh
            and cached is not None
            and _SUBSCRIPTION_CACHE.get("signature") == signature
            and now - float(_SUBSCRIPTION_CACHE.get("at") or 0.0)
            < _SUBSCRIPTION_CACHE_TTL_SEC
        ):
            sub = dict(cached)
        else:
            sub = get_subscription()
            _SUBSCRIPTION_CACHE.update(
                value=dict(sub),
                signature=signature,
                at=now,
            )
        return {**base, **sub, "queue": queue_status(), "slots": list_generation_slots()}
    except Exception as exc:
        return {
            **base,
            "ok": False,
            "message": str(exc),
            "queue": queue_status(),
            "slots": list_generation_slots(),
        }

@router.post("/nai/token")
def api_nai_token_set(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return save_token(str(payload.get("token") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/nai/tokens")
def api_nai_tokens() -> dict:
    return token_status() | {"ok": True}

@router.post("/nai/token/add")
def api_nai_token_add(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return add_token_entry(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.delete("/nai/token/{token_id}")
def api_nai_token_delete(token_id: str) -> dict:
    try:
        return delete_token_entry(token_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc

@router.post("/nai/token/check")
def api_nai_token_check(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return check_token_pool(
            str(payload.get("token_id") or ""),
            remove_bad=payload.get("remove_bad") is not False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc)) from exc

@router.get("/nai/queue")
def api_nai_queue() -> dict:
    return {"ok": True, "queue": queue_status()}

@router.get("/nai/jobs")
def api_nai_jobs(task_id: str = Query("")) -> dict:
    job = batch_status(task_id or None)
    if task_id and job is None:
        raise HTTPException(status_code=404, detail="generation task not found")
    return {"ok": True, "job": job}


@router.post("/nai/generate")
async def api_nai_generate(payload: NaiGenerateRequest) -> dict:
    data = payload.model_dump()
    comment = data.get("patched_comment")
    if not comment:
        raise HTTPException(status_code=400, detail="patched_comment is required")
    # Accept string work_id (AITag large IDs lose precision if forced through JS Number).
    work_id = None
    raw_work_id = data.get("work_id")
    if raw_work_id is not None and str(raw_work_id).strip() != "":
        try:
            work_id = int(str(raw_work_id).strip())
            if work_id <= 0:
                work_id = None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="work_id must be an integer string") from exc
    page_index = int(data.get("page_index") or 0)
    source_gallery_id = str(data.get("source_gallery_id") or "site").strip() or "site"
    comment = clean_plain_ark_workbench_draft(
        comment,
        work_id,
        page_index,
        gallery_id=source_gallery_id,
    )
    remote_work_id = str(data.get("remote_work_id") or data.get("work_id_str") or "").strip()
    source_title = str(data.get("source_title") or "").strip()
    source_thumb = str(data.get("source_thumb") or "").strip()
    if isinstance(comment, dict):
        comment.setdefault("_aitag_source", {})
        if isinstance(comment["_aitag_source"], dict):
            if remote_work_id:
                comment["_aitag_source"]["work_id"] = remote_work_id
            comment["_aitag_source"]["page_index"] = page_index
            if source_title:
                comment["_aitag_source"]["title"] = source_title
            if source_thumb:
                comment["_aitag_source"]["thumb"] = source_thumb
            source_title = str(comment["_aitag_source"].get("title") or source_title).strip()
            source_thumb = str(comment["_aitag_source"].get("thumb") or source_thumb).strip()
            remote_work_id = str(comment["_aitag_source"].get("work_id") or remote_work_id).strip()
    try:
        copies = int(data.get("copies") or data.get("batch_count") or 1)
    except (TypeError, ValueError):
        copies = 1
    result = await asyncio.to_thread(
        start_studio_generate,
        comment if isinstance(comment, dict) else {},
        work_id=work_id,
        page_index=page_index,
        copies=copies,
        source_gallery_id=source_gallery_id if source_gallery_id in {"site", "aitag-online", "codex", "qqgroup"} else "site",
        seed_policy=str(data.get("seed_policy") or ""),
        force_free=bool(data.get("force_free", True)),
        prompt_profile=str(data.get("prompt_profile") or "native"),
        source_title=source_title,
        source_thumb=source_thumb,
        remote_work_id=remote_work_id,
        token_id=str(data.get("token_id") or ""),
    )
    if not result.get("ok"):
        error = str(result.get("error") or "")
        if error == "missing_token":
            raise HTTPException(status_code=400, detail=str(result.get("message") or "NovelAI token is not configured"))
        if error == "persistence_failed":
            raise HTTPException(status_code=503, detail=str(result.get("message") or "generation job could not be persisted"))
        return result
    return result

def _start_generated_maintenance_once() -> None:
    # This will be run inside server.py lifespan, so we just declare it or delegate it.
    pass

@router.get("/generated")
def api_generated_list() -> dict:
    groups = list_groups()
    for g in groups:
        wid = g.get("work_id")
        if not wid:
            g["source_title"] = "Standalone generation"
            g["source_thumb"] = ""
            continue
        gallery_id = str(g.get("source_gallery_id") or "site")
        # Online AITag sources are not in the local site/codex DBs.
        if gallery_id in {"aitag-online", "aitag"}:
            remote = str(g.get("remote_work_id") or wid or "").strip()
            title = str(g.get("source_title") or "").strip()
            if not title:
                title = f"AITag #{remote}" if remote else "AITag 在线生成"
            elif remote and remote not in title:
                title = f"{title} · AITag #{remote}"
            g["source_title"] = title
            g["source_thumb"] = str(
                g.get("source_thumb") or g.get("cover_thumb") or g.get("cover_url") or ""
            )
            continue
        try:
            db = DB if gallery_id == "site" else get_gallery_db(gallery_id)
            info = get_cached_source_info(
                int(wid),
                db.get_work_detail,
                gallery_id=gallery_id,
            )
            g["source_title"] = info.get("title") or f"作品 {wid}"
            g["source_thumb"] = info.get("thumb") or ""
        except Exception:
            g["source_title"] = f"作品 {wid}"
            g["source_thumb"] = ""
    groups = [
        serialize_gallery_payload(
            group,
            str(group.get("source_gallery_id") or "site"),
        )
        for group in groups
    ]
    pipe_cfg = load_config()
    return {
        "ok": True,
        "total": len(groups),
        "groups": groups,
        "queue": queue_status(),
        "batch": batch_status(),
        "pipeline_config": {
            "auto_after_generate": bool(pipe_cfg.get("auto_after_generate")),
        },
    }

@router.delete("/generated/item/{image_id}")
def api_generated_delete_item(image_id: str) -> dict:
    try:
        return delete_item(image_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.delete("/generated/group/{group_id}")
def api_generated_delete_group(group_id: str) -> dict:
    try:
        return delete_group(group_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/generated/trash/{trash_id}/restore")
def api_generated_restore(trash_id: str) -> dict:
    try:
        return restore_deleted(trash_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/generated/trash")
def api_generated_trash() -> dict:
    items = []
    for row in list_deleted():
        items.append(
            {
                "trash_id": row.get("trash_id"),
                "kind": row.get("kind") or "item",
                "group_id": row.get("group_id") or "",
                "image_ids": row.get("image_ids") or [],
                "created_at": row.get("created_at") or "",
                "file_count": int(row.get("file_count") or 0),
            }
        )
    return {"ok": True, "items": items}

def _is_generated_group_active(group_id: str, batch: dict, queue: dict) -> bool:
    gid = str(group_id or "").strip()
    if not gid:
        return False
    if batch.get("status") == "running" and batch.get("current_work_id") is not None:
        if str(batch.get("current_work_id")) == gid:
            return True
    if queue.get("status") == "running" and queue.get("work_id") is not None:
        if str(queue.get("work_id")) == gid:
            return True
    return False

def _pending_generated_group(group_id: str) -> dict:
    wid = None
    gallery_id = "site"
    raw = str(group_id or "").strip()
    base = raw
    if base.startswith("gallery:"):
        parts = base.split(":", 2)
        if len(parts) == 3:
            gallery_id, base = parts[1], parts[2]
    if base.startswith("run:"):
        parts = base.split(":", 2)
        if len(parts) == 3 and parts[2] != "standalone":
            try:
                wid = int(parts[2])
            except ValueError:
                wid = None
    elif base not in {"", "standalone"}:
        try:
            wid = int(base)
        except ValueError:
            wid = None
    return {
        "group_id": group_id,
        "work_id": wid,
        "source_gallery_id": gallery_id,
        "count": 0,
        "cover_url": "",
        "latest_at": "",
        "items": [],
        "pending": True,
    }

def _generated_source_prompt(wid: int, gallery_id: str = "site") -> dict | None:
    try:
        ex = extract_chars(int(wid), 0, gallery_id=str(gallery_id or "site"))
        return {
            "base_caption": ex.get("base_caption") or "",
            "chars": [
                {
                    "index": c.get("index"),
                    "summary": c.get("summary") or "",
                    "caption": c.get("char_caption") or "",
                    "creature_tags": c.get("creature_tags") or [],
                }
                for c in ex.get("chars") or []
            ],
        }
    except Exception:
        return None

@router.get("/generated/{group_id}/source-prompt")
def api_generated_source_prompt(group_id: str) -> dict:
    group = get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="生成组不存在")
    wid = group.get("work_id")
    if not wid:
        return {"ok": True, "source_prompt": None}
    gallery_id = str(group.get("source_gallery_id") or "site")
    return {
        "ok": True,
        "source_prompt": _generated_source_prompt(int(wid), gallery_id=gallery_id),
    }

@router.get("/generated/{group_id}")
def api_generated_group(group_id: str, include_source_prompt: bool = Query(True)) -> dict:
    from generated_gallery import _public_source_thumb_url

    migrate_legacy_meta()
    batch = batch_status()
    queue = queue_status()
    group = get_group(group_id)
    if not group:
        if _is_generated_group_active(group_id, batch, queue):
            group = _pending_generated_group(group_id)
        else:
            raise HTTPException(status_code=404, detail="生成组不存在")
    wid = group.get("work_id")
    gallery_id = str(group.get("source_gallery_id") or "site")
    source = None
    source_prompt = None
    if wid:
        try:
            db = DB if gallery_id == "site" else get_gallery_db(gallery_id)
            detail = db.get_work_detail(int(wid))
            if detail:
                work = detail.get("work") or {}
                source = {
                    "work_id": wid,
                    "title": work.get("title") or work.get("caption") or f"作品 {wid}",
                    "url": f"/i/{wid}?gallery={gallery_id}" if gallery_id != "site" else f"/i/{wid}",
                    "thumb": "",
                }
                images = detail.get("images") or []
                if images:
                    local_path = str(images[0].get("local_path") or "").replace("\\", "/").lstrip("/")
                    if local_path:
                        source["thumb"] = _public_source_thumb_url(
                            local_path, gallery_id=gallery_id
                        )
                    elif images[0].get("file_name"):
                        source["thumb"] = _public_source_thumb_url(
                            str(images[0]["file_name"]), gallery_id=gallery_id
                        )
        except Exception:
            source = {
                "work_id": wid,
                "title": f"作品 {wid}",
                "url": f"/i/{wid}",
                "thumb": "",
            }
        if include_source_prompt:
            source_prompt = _generated_source_prompt(int(wid), gallery_id=gallery_id)
    return serialize_gallery_payload({
        "ok": True,
        "group": group,
        "source": source,
        "source_prompt": source_prompt,
        "queue": queue,
        "batch": batch,
    }, gallery_id)
