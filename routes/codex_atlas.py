"""Read-only 法典图鉴 discovery and prompt-only Studio draft bridge."""

from __future__ import annotations

import math
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from aitag_core.draft_store import public_draft_response, save_studio_draft
from nai_char_modules.snapshots import prompt_snapshot_from_comment
from codex_atlas.external import CodexAtlasEntry, atlas_image_url
from codex_atlas.online import (
    ATLAS_DATA_ORIGIN,
    ATLAS_SITE_URL,
    DEFAULT_BOOK_ID,
    CodexAtlasClient,
    CodexAtlasClientError,
    parse_atlas_work_id,
)
from server_shared import CONFIG, DATA_DIR

router = APIRouter(prefix="/api/nai/codex-atlas")
_CLIENT: CodexAtlasClient | None = None
_CLIENT_LOCK = threading.Lock()
_DEFAULT_DRAFT_TTL_SECONDS = 30 * 24 * 60 * 60
_GALLERY_ID = "codex-atlas"


def _online_enabled() -> bool:
    return bool(CONFIG.get("codex_atlas_online_enabled", True))


def _draft_ttl_seconds() -> float:
    try:
        value = float(CONFIG.get("codex_atlas_draft_ttl_sec", _DEFAULT_DRAFT_TTL_SECONDS))
    except (TypeError, ValueError):
        return float(_DEFAULT_DRAFT_TTL_SECONDS)
    return value if math.isfinite(value) and value > 0 else float(_DEFAULT_DRAFT_TTL_SECONDS)


def get_atlas_client() -> CodexAtlasClient:
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = CodexAtlasClient(
                    cache_root=DATA_DIR / ".cache" / "codex-atlas",
                    cache_ttl_seconds=float(CONFIG.get("codex_atlas_cache_ttl_sec", 600) or 600),
                    cache_max_bytes=int(CONFIG.get("codex_atlas_cache_max_bytes", 96 * 1024 * 1024) or 0),
                    timeout_seconds=float(CONFIG.get("codex_atlas_timeout_sec", 30) or 30),
                )
    return _CLIENT


def _require_online() -> CodexAtlasClient:
    if not _online_enabled():
        raise HTTPException(status_code=503, detail="法典图鉴 online discovery is disabled in configuration")
    try:
        return get_atlas_client()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"法典图鉴 online discovery is unavailable: {exc}") from exc


def _remote_error(exc: CodexAtlasClientError) -> HTTPException:
    status = 404 if exc.status_code == 404 else 502
    return HTTPException(status_code=status, detail=str(exc))


def _cover_proxy(entry: CodexAtlasEntry) -> str:
    return f"/api/nai/codex-atlas/cover/{entry.work_id}"


def _public_item(entry: CodexAtlasEntry) -> dict[str, Any]:
    cover = _cover_proxy(entry) if entry.image else ""
    return {
        "id": entry.work_id,
        "work_id": entry.work_id,
        "book_id": entry.book_id,
        "entry_id": entry.entry_id,
        "title": entry.title,
        "creator": entry.author,
        "userName": entry.author,
        "AI_type": "NAI",
        "ai_type": "NAI",
        "caption": entry.note,
        "tags": [part.strip() for part in entry.tags.split(",") if part.strip()][:80],
        "prompt": entry.tags,
        "negative": entry.negative,
        "path": list(entry.path),
        "character_prompts": [dict(item) for item in entry.character_prompts],
        "image_count": 1 if entry.image else 0,
        "thumbnail_url": cover,
        "cover_url": cover,
        "source_gallery_id": _GALLERY_ID,
        "external_url": entry.source_url or f"{ATLAS_SITE_URL}/?codex={entry.book_id}",
        "attribution": "词条归原编纂者；配图与汇编结构归 法典图鉴 / 各贡献者。本应用只做只读发现，不入库、不转授。",
    }


def _public_detail(entry: CodexAtlasEntry) -> dict[str, Any]:
    item = _public_item(entry)
    cover = item.get("cover_url") or ""
    images = []
    if cover:
        images.append(
            {
                "id": f"{entry.work_id}_p0",
                "image_id": f"{entry.work_id}_p0",
                "page_index": 0,
                "url": cover,
                "thumbnail_url": cover,
                "ai_json": {
                    "prompt": entry.tags,
                    "uc": entry.negative,
                },
            }
        )
    item["images"] = images
    return {
        "ok": True,
        "source": _GALLERY_ID,
        "generation_calls": 0,
        "work": item,
        "images": images,
        "attribution": item["attribution"],
    }


def _compile_prompt_draft(entry: CodexAtlasEntry) -> dict[str, Any]:
    comment = {
        "prompt": entry.tags,
        "uc": entry.negative,
        "width": 832,
        "height": 1216,
        "steps": 28,
        "scale": 5.0,
        "sampler": "k_euler_ancestral",
        "seed": -1,
    }
    if entry.character_prompts:
        comment["v4_prompt"] = {
            "caption": {
                "base_caption": entry.tags,
                "char_captions": [
                    {
                        "char_caption": item.get("prompt") or "",
                        "centers": [{"x": 0.5, "y": 0.5}],
                    }
                    for item in entry.character_prompts
                    if item.get("prompt")
                ],
            }
        }
    cover = _cover_proxy(entry) if entry.image else ""
    draft = {
        "galleryId": _GALLERY_ID,
        "workId": 0,
        "pageIndex": 0,
        "title": entry.title or entry.work_id,
        "thumb": cover,
        "comment": comment,
        "texts": prompt_snapshot_from_comment(comment),
        "params": {
            "width": comment["width"],
            "height": comment["height"],
            "steps": comment["steps"],
            "scale": comment["scale"],
            "sampler": comment["sampler"],
            "seed": comment["seed"],
            "batch": 1,
        },
        "refs": {"vibe": "", "char": "", "strength": "0.6"},
        "source": {
            "provider": _GALLERY_ID,
            "workId": entry.work_id,
            "workIdStr": entry.work_id,
            "bookId": entry.book_id,
            "entryId": entry.entry_id,
            "title": entry.title,
            "thumb": cover,
            "site": ATLAS_SITE_URL,
        },
    }
    return {
        "draft": draft,
        "work_id": entry.work_id,
        "image_index": 0,
        "partial": False,
    }


@router.get("/status")
def api_atlas_status() -> dict[str, Any]:
    if not _online_enabled():
        return {
            "ok": False,
            "enabled": False,
            "source": _GALLERY_ID,
            "local_fallback": True,
            "generation_calls": 0,
        }
    try:
        client = get_atlas_client()
        return {
            "ok": True,
            "enabled": True,
            "source": _GALLERY_ID,
            "site_url": ATLAS_SITE_URL,
            "local_fallback": True,
            "generation_calls": 0,
            **client.status(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "source": _GALLERY_ID,
            "local_fallback": True,
            "generation_calls": 0,
            "error": str(exc),
        }


@router.get("/books")
def api_atlas_books(safe_only: bool = Query(True)) -> dict[str, Any]:
    client = _require_online()
    try:
        books = client.list_books(safe_only=safe_only)
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    items = []
    for book in books:
        cover = ""
        if book.cover:
            cover = atlas_image_url(
                image_base=ATLAS_DATA_ORIGIN,
                book_id=book.book_id,
                file_name=book.cover,
            )
        items.append(
            {
                **book.to_dict(),
                "id": book.book_id,
                "label": book.title,
                "kind": "book",
                "key": book.book_id,
                "group_key": book.book_id,
                "count": book.entry_count,
                "cover_url": cover,
                "default": book.book_id == DEFAULT_BOOK_ID,
            }
        )
    return {
        "ok": True,
        "source": _GALLERY_ID,
        "safe_only": safe_only,
        "default_book_id": DEFAULT_BOOK_ID,
        "items": items,
        "generation_calls": 0,
    }


@router.get("/search")
def api_atlas_search(
    q: str = Query("", max_length=2_000),
    prompt: str = Query("", max_length=2_000),
    book_id: str = Query("", max_length=64),
    group: str = Query("", max_length=64),
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(60, ge=1, le=120),
    sort: str = Query("relevance", max_length=40),
    safe_only: bool = Query(True),
) -> dict[str, Any]:
    client = _require_online()
    query = str(q or prompt or "").strip()
    selected = str(book_id or group or "").strip()
    try:
        result = client.search(
            query=query,
            book_id=selected,
            page=page,
            page_size=page_size,
            sort=sort,
            safe_only=safe_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    items = [_public_item(entry) for entry in result.entries]
    return {
        "ok": True,
        "source": _GALLERY_ID,
        "query": result.query,
        "book_id": result.book_id,
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        "has_more": result.has_more,
        "items": items,
        "works": items,
        "safe_only": safe_only,
        "local_only": False,
        "generation_calls": 0,
        "attribution": "数据来自 novelai.quicktagcloud.com 的公开发布层；只读发现，不写入本地主库。",
    }


@router.get("/entry/{work_id:path}")
def api_atlas_entry(work_id: str, safe_only: bool = Query(True)) -> dict[str, Any]:
    client = _require_online()
    try:
        parse_atlas_work_id(work_id)
        entry = client.get_entry(work_id, safe_only=safe_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    return _public_detail(entry)


@router.get("/cover/{work_id:path}")
def api_atlas_cover(work_id: str, safe_only: bool = Query(True)) -> Response:
    client = _require_online()
    try:
        entry = client.get_entry(work_id, safe_only=safe_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    if not entry.image:
        raise HTTPException(status_code=404, detail="法典图鉴 cover was not found")
    try:
        content, content_type = client.get_image(entry.book_id, entry.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=600", "X-Generation-Calls": "0"},
    )


@router.post("/entry/{work_id:path}/draft")
def api_atlas_draft(work_id: str, safe_only: bool = Query(True)) -> dict[str, Any]:
    client = _require_online()
    try:
        entry = client.get_entry(work_id, safe_only=safe_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CodexAtlasClientError as exc:
        raise _remote_error(exc) from exc
    if not entry.tags.strip():
        raise HTTPException(status_code=400, detail="该词条没有可送入 Studio 的 Prompt")
    compiled = _compile_prompt_draft(entry)
    record = save_studio_draft(
        compiled,
        source=_GALLERY_ID,
        root=DATA_DIR,
        ttl_seconds=_draft_ttl_seconds(),
    )
    payload = public_draft_response(record)
    draft_id = str(payload.get("draft_id") or "")
    payload["source"] = _GALLERY_ID
    payload["provider"] = _GALLERY_ID
    payload["studio_url"] = f"/studio?source=codex-atlas&draft={draft_id}"
    payload["work_id"] = entry.work_id
    payload["message"] = "已把词条 Prompt 做成零生成 Studio 草稿；点击生成后才会调用 NAI。"
    return payload
