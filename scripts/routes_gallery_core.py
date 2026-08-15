"""Core-only local gallery routes copied to ``routes/gallery.py`` at release time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from server_shared import CONFIG, DATA_DIR, DB, WEB_DIR


router = APIRouter()
_PUBLIC_WORK_KEYS = {
    "AI_type", "ai_type", "caption", "createDate", "create_date", "height", "id",
    "image_count", "pageCount", "preview_local", "tags", "thumb_path", "title",
    "total_bookmarks", "total_view", "userAccount", "userId", "userName",
    "user_account", "user_id", "user_name", "width",
}
_PUBLIC_IMAGE_KEYS = {
    "ai_json", "comment", "height", "local_path", "metadata", "model", "nai_tags",
    "negative_prompt", "page_index", "parsed_nai_tags", "prompt", "prompt_text",
    "sampler", "seed", "width",
}


def public_work(work: Any) -> dict[str, Any]:
    if not isinstance(work, dict):
        return {}
    return {str(key): value for key, value in work.items() if str(key) in _PUBLIC_WORK_KEYS}


def public_search_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"page": 1, "page_size": 60, "total": 0, "items": []}
    return {
        "page": int(result.get("page") or 1),
        "page_size": int(result.get("page_size") or 60),
        "total": result.get("total"),
        "items": [public_work(item) for item in result.get("items") or []],
    }


def public_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {"work": {}, "images": []}
    images = []
    for image in detail.get("images") or []:
        if isinstance(image, dict):
            images.append({str(key): value for key, value in image.items() if str(key) in _PUBLIC_IMAGE_KEYS})
    return {"work": public_work(detail.get("work")), "images": images}


def _safe_image(raw_path: str) -> Path:
    normalized = str(raw_path or "").replace("\\", "/").lstrip("/")
    if not normalized or "\x00" in normalized:
        raise HTTPException(status_code=404, detail="image not found")
    root = (DATA_DIR / "images").resolve()
    candidate = (root / normalized).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=404, detail="image not found")
    return candidate


def _page(filename: str) -> FileResponse:
    path = WEB_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} missing")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@router.get("/api/config")
def api_config() -> JSONResponse:
    return JSONResponse(
        {
            "asset_base_url": "/data/images/",
            "page_size": int(CONFIG.get("page_size") or 60),
            "default_query": str(CONFIG.get("search_query") or ""),
            "gallery_title_zh": "Pixiv NAI 本地图库",
            "gallery_title_en": "Pixiv NAI Gallery Core",
            "gallery_nai_only_default": True,
            "local_mirror": True,
        },
        headers={"Cache-Control": "private, max-age=120"},
    )


@router.get("/api/ai_works_search")
def api_search(
    q: str = "",
    prompt: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
    sort: str = "new",
    time_range: str = "all",
) -> dict:
    return public_search_result(
        DB.search_works(
            q=q,
            prompt=prompt,
            page=page,
            page_size=page_size,
            sort=sort,
            time_range=time_range,
            local_scope="local",
            nai_only=True,
        )
    )


def _work_detail(work_id: int) -> dict:
    if not DB.work_in_scope(work_id, "local"):
        raise HTTPException(status_code=404, detail="work not found")
    detail = DB.get_work_detail(work_id)
    if not detail:
        raise HTTPException(status_code=404, detail="work not found")
    return public_detail(detail)


@router.get("/api/work/{work_id}")
def api_work(work_id: int) -> dict:
    return _work_detail(work_id)


@router.get("/api/ai_work/{work_id}")
def api_work_compat(work_id: int) -> dict:
    return _work_detail(work_id)


@router.get("/api/work/{work_id}/lite")
def api_work_lite(work_id: int) -> dict:
    if not DB.work_in_scope(work_id, "local"):
        raise HTTPException(status_code=404, detail="work not found")
    payload = DB.get_work_lite(work_id)
    if not payload:
        raise HTTPException(status_code=404, detail="work not found")
    return {str(key): value for key, value in payload.items() if str(key) in _PUBLIC_WORK_KEYS}


@router.get("/data/images/{image_path:path}")
def serve_image(image_path: str) -> FileResponse:
    path = _safe_image(image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


@router.get("/progress")
def intake_page() -> FileResponse:
    return _page("progress.html")


@router.get("/")
def index() -> FileResponse:
    return _page("index.html")


@router.get("/i/{work_id}")
def work_page(work_id: str) -> FileResponse:
    _ = work_id
    return _page("index.html")
