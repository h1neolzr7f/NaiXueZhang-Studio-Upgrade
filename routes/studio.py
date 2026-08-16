from fastapi import APIRouter, Body, HTTPException, Query

from pixiv_launch import save_ai_key
from studio_service import (
    apply_vibe_to_comment,
    attach_image_reference,
    import_from_work,
    list_queue_for_studio,
    optimize_comment,
    preview_work_prompt,
    sanitize_comment,
    source_image_for_work,
    studio_config,
)
from user_prefs import load_prefs
from nai_api import token_status

router = APIRouter(prefix="/api/studio")


@router.get("/config")
def api_studio_config() -> dict:
    cfg = studio_config()
    cfg["prefs"] = load_prefs()
    cfg["token"] = token_status()
    return cfg


@router.get("/queue")
def api_studio_queue(limit: int = Query(40, ge=1, le=120)) -> dict:
    return list_queue_for_studio(limit)


@router.get("/preview")
def api_studio_preview(
    work_id: int = Query(..., ge=1),
    page_index: int = Query(0, ge=0),
) -> dict:
    try:
        return preview_work_prompt(work_id, page_index)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/source-image")
def api_studio_source_image(
    work_id: int = Query(..., ge=1),
    page_index: int = Query(0, ge=0),
    gallery_id: str = Query("site"),
) -> dict:
    try:
        return source_image_for_work(work_id, page_index, gallery_id=gallery_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/import")
def api_studio_import(
    work_id: int = Query(..., ge=1),
    page_index: int = Query(0, ge=0),
    gallery_id: str = Query("site"),
) -> dict:
    try:
        return import_from_work(work_id, page_index, gallery_id=gallery_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sanitize")
def api_studio_sanitize(payload: dict = Body(default_factory=dict)) -> dict:
    comment = payload.get("comment")
    if not comment:
        raise HTTPException(status_code=400, detail="comment is required")
    try:
        return sanitize_comment(
            comment,
            filter_racial=payload.get("filter_racial", True),
            filter_gore=payload.get("filter_gore", True),
            filter_creature=payload.get("filter_creature", False),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/optimize")
def api_studio_optimize(payload: dict = Body(default_factory=dict)) -> dict:
    comment = payload.get("comment")
    if not comment:
        raise HTTPException(status_code=400, detail="comment is required")
    mode = str(payload.get("mode") or "smart")
    if mode == "sanitize":
        return sanitize_comment(comment)
    try:
        return optimize_comment(comment, mode=mode, profile=str(payload.get("profile") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/vibe")
def api_studio_vibe(payload: dict = Body(default_factory=dict)) -> dict:
    comment = payload.get("comment")
    if not comment:
        raise HTTPException(status_code=400, detail="comment is required")
    try:
        return apply_vibe_to_comment(
            comment,
            image_url=str(payload.get("image_url") or ""),
            image_path=str(payload.get("image_path") or ""),
            strength=float(payload.get("strength") or 0.6),
            information_extracted=float(payload.get("information_extracted") or 1.0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai-key")
def api_studio_ai_key(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return save_ai_key(str(payload.get("api_key") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reference")
def api_studio_reference(payload: dict = Body(default_factory=dict)) -> dict:
    comment = payload.get("comment")
    if not comment:
        raise HTTPException(status_code=400, detail="comment is required")
    try:
        return attach_image_reference(
            comment,
            image_url=str(payload.get("image_url") or ""),
            work_id=int(payload["work_id"]) if payload.get("work_id") else None,
            page_index=int(payload.get("page_index") or 0),
            kind=str(payload.get("kind") or "vibe"),
            strength=float(payload.get("strength") or 0.6),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc