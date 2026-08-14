"""AITag online discovery and explicit NAI character replacement bridge."""

from __future__ import annotations

import math
import threading
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Body, HTTPException, Query, Response

from aitag_core.external import (
    AitagConfig,
    AitagImage,
    AitagWorkDetail,
    aitag_image_url,
    aitag_work_is_nai,
    aitag_work_is_safe,
    strip_aitag_html,
    to_reference_record,
)
from aitag_core.draft_store import (
    get_latest_studio_draft,
    get_studio_draft,
    public_draft_response,
    save_studio_draft,
)
from aitag_core.online import AITAG_SITE_URL, AitagClient, AitagClientError
from aitag_core.recipe import (
    CharacterCandidate,
    discover_character_candidates,
    select_character_candidate,
)
from aitag_core.studio import compile_aitag_studio_draft, compile_aitag_studio_drafts
from favorites import add as add_favorite
from favorites import has as has_favorite
from favorites import list_refs as list_favorite_refs
from favorites import remove as remove_favorite
from ark_char_library import search_library as search_builtin_character_library
from nai_anima_adapter import apply_anima_character_to_comment
from nai_char import list_char_presets
from nai_char_modules.snapshots import prompt_snapshot_from_comment
from reference_catalog import get_reference_catalog
from server_shared import CONFIG, DATA_DIR

router = APIRouter(prefix="/api/nai/aitag")
_CLIENT: AitagClient | None = None
_CLIENT_LOCK = threading.Lock()
_DEFAULT_DRAFT_TTL_SECONDS = 30 * 24 * 60 * 60
_AITAG_GALLERY_ID = "aitag-online"


def _online_enabled() -> bool:
    return bool(CONFIG.get("aitag_online_enabled", True))


def _draft_ttl_seconds() -> float:
    try:
        value = float(CONFIG.get("aitag_draft_ttl_sec", _DEFAULT_DRAFT_TTL_SECONDS))
    except (TypeError, ValueError):
        return float(_DEFAULT_DRAFT_TTL_SECONDS)
    return value if math.isfinite(value) and value > 0 else float(_DEFAULT_DRAFT_TTL_SECONDS)


def get_aitag_client() -> AitagClient:
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = AitagClient(
                    # The online discovery origin is a fixed trust boundary,
                    # not a browser- or config-controlled proxy target.
                    base_url=AITAG_SITE_URL,
                    cache_root=DATA_DIR / ".cache" / "aitag-online",
                    cache_ttl_seconds=float(CONFIG.get("aitag_online_cache_ttl_sec", 600) or 600),
                    cache_max_bytes=int(CONFIG.get("aitag_online_cache_max_bytes", 64 * 1024 * 1024) or 0),
                    timeout_seconds=float(CONFIG.get("aitag_online_timeout_sec", 30) or 30),
                )
    return _CLIENT


def _require_online() -> AitagClient:
    if not _online_enabled():
        raise HTTPException(status_code=503, detail="AITag online discovery is disabled in configuration")
    try:
        return get_aitag_client()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"AITag online discovery is unavailable: {exc}") from exc


def _remote_error(exc: AitagClientError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def _image_with_url(client: AitagClient, image: AitagImage, config: AitagConfig | None = None) -> AitagImage:
    if image.url and image.thumbnail_url:
        return image
    try:
        resolved = config or client.get_config()
    except Exception:
        resolved = AitagConfig()
    url = aitag_image_url(resolved, image)
    return replace(image, url=image.url or url, thumbnail_url=image.thumbnail_url or url)


def _decorate_detail(client: AitagClient, detail: AitagWorkDetail) -> AitagWorkDetail:
    try:
        config = client.get_config()
    except Exception:
        config = AitagConfig()
    images = tuple(_image_with_url(client, image, config) for image in detail.images)
    return AitagWorkDetail(work=detail.work, images=images)


def _search_cover(client: AitagClient, work: Any, config: AitagConfig) -> dict[str, Any] | None:
    """Expose one CDN cover without downloading or persisting remote bytes."""

    synthetic = not work.images
    if work.images:
        image = _image_with_url(client, work.images[0], config)
    else:
        image_type = str(work.ai_type or "").strip()
        author_id = str(work.user_id or "").strip()
        if not image_type or not author_id or not work.work_id:
            return None
        image = _image_with_url(
            client,
            AitagImage(
                image_id=f"{work.work_id}_p0",
                work_id=work.work_id,
                author_id=author_id,
                image_type=image_type,
                file_name=f"{work.work_id}_p0",
            ),
            config,
        )
    if not image.url and not image.thumbnail_url:
        return None
    data = image.to_dict()
    data["id"] = data["image_id"]
    if not synthetic:
        data["remote_url"] = data.get("url") or data.get("thumbnail_url") or ""
    else:
        data.pop("remote_url", None)
    proxy_url = f"/api/nai/aitag/cover/{work.work_id}"
    data["url"] = proxy_url
    data["thumbnail_url"] = proxy_url
    return data


def _filter_tokens(value: str, *, limit: int = 20) -> tuple[str, ...]:
    text = str(value or "").replace("，", ",").replace("\n", ",")
    result: list[str] = []
    for part in text.split(","):
        token = part.strip().casefold()
        if token and token not in result:
            result.append(token)
        if len(result) >= limit:
            break
    return tuple(result)


def _matches_advanced_filters(
    work: Any,
    *,
    creator: str,
    tags: tuple[str, ...],
    model: str,
    min_images: int,
    max_images: int,
) -> bool:
    creator_query = str(creator or "").strip().casefold()
    if creator_query:
        creator_haystack = " ".join(
            str(value or "").casefold()
            for value in (work.creator, work.user_id)
        )
        if creator_query not in creator_haystack:
            return False
    work_tags = tuple(str(value or "").strip().casefold() for value in work.tags)
    if tags and not all(any(token in value for value in work_tags) for token in tags):
        return False
    model_query = str(model or "").strip().casefold()
    if model_query:
        model_haystack = " ".join(
            [str(work.ai_type or "").casefold()]
            + [str(image.model or "").casefold() for image in work.images]
        )
        if model_query not in model_haystack:
            return False
    image_count = max(0, int(work.image_count or len(work.images) or 0))
    if min_images > 0 and image_count < min_images:
        return False
    if max_images > 0 and image_count > max_images:
        return False
    return True


def _favorite_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title": 500,
        "creator": 300,
        "cover_url": 2_000,
        "ai_type": 80,
        "create_date": 80,
    }
    snapshot = {
        key: str(payload.get(key) or "").strip()[:limit]
        for key, limit in allowed.items()
        if str(payload.get(key) or "").strip()
    }
    try:
        snapshot["image_count"] = max(0, min(int(payload.get("image_count") or 0), 100_000))
    except (TypeError, ValueError):
        snapshot["image_count"] = 0
    raw_tags = payload.get("tags")
    if isinstance(raw_tags, (list, tuple)):
        snapshot["tags"] = [str(value or "").strip()[:200] for value in raw_tags[:100] if str(value or "").strip()]
    return snapshot


def _image_proxy_url(image: AitagImage) -> str:
    from urllib.parse import quote

    if not image.image_type or not image.author_id or not image.file_name:
        return ""
    file_name = str(image.file_name)
    if not file_name.casefold().endswith(".webp"):
        file_name += ".webp"
    parts = [image.image_type, image.author_id, file_name]
    return "/api/nai/aitag/image/" + "/".join(quote(str(part), safe="") for part in parts)


def _detail_payload(detail: AitagWorkDetail) -> dict[str, Any]:
    work = detail.work.to_dict()
    work["id"] = work["work_id"]
    work["external_url"] = f"https://aitag.win/i/{work['work_id']}"
    work["title"] = strip_aitag_html(work.get("title") or work["work_id"])
    images = []
    for image_index, image in enumerate(detail.images):
        data = image.to_dict()
        data["id"] = data["image_id"]
        # Always 0-based array index. Do not reuse remote page numbers here —
        # draft/generate APIs index detail.images the same way.
        data["page_index"] = image_index
        data["remote_url"] = data.get("url") or data.get("thumbnail_url") or ""
        proxy_url = _image_proxy_url(image)
        if proxy_url:
            data["url"] = proxy_url
            data["thumbnail_url"] = proxy_url
        images.append(data)
    work["images"] = images
    candidates = [item.to_dict() for item in discover_character_candidates(detail)]
    return {
        "work": work,
        "images": images,
        "source": "aitag-online",
        "external_url": work["external_url"],
        "character_candidates": candidates,
        "local_only": False,
        "generation_calls": 0,
    }


def _pick_image(detail: AitagWorkDetail, index: Any) -> AitagImage:
    try:
        image_index = int(index or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="image_index must be an integer") from exc
    if image_index < 0 or image_index >= len(detail.images):
        raise HTTPException(status_code=404, detail="AITag work image was not found")
    return detail.images[image_index]


def _pick_candidate(
    detail: AitagWorkDetail,
    *,
    image_index: int,
    slot_index: int,
    candidate_id: str = "",
) -> CharacterCandidate | None:
    """Resolve one explicit remote character slot without guessing across images."""

    candidates = discover_character_candidates(detail)
    if not candidates and not candidate_id:
        return None
    try:
        return select_character_candidate(
            candidates,
            candidate_id=candidate_id,
            image_index=image_index,
            slot_index=slot_index,
        )
    except ValueError as exc:
        status_code = 400 if candidate_id else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _builtin_target_record(target_reference_id: str) -> dict[str, Any] | None:
    """Resolve the same built-in character choices used by the local swap panel."""

    parts = str(target_reference_id or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in {"preset", "ark"}:
        return None
    kind, gender, item_id = parts
    if gender not in {"female", "male"} or not item_id:
        raise HTTPException(status_code=400, detail="Invalid built-in target character reference")
    if kind == "preset":
        items = list_char_presets(gender)
    else:
        items = search_builtin_character_library(
            gender=gender,
            q=item_id,
            limit=200,
        ).get("items") or []
    item = next((value for value in items if str(value.get("id") or "") == item_id), None)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Built-in target character was not found")

    identity = [str(value).strip() for value in item.get("identity") or [] if str(value).strip()]
    appearance = [
        str(value).strip()
        for value in [*(item.get("body") or []), *(item.get("appearance") or [])]
        if str(value).strip()
    ]
    caption = str(item.get("char_caption") or "").strip()
    preset_kind = str(item.get("kind") or "").strip().lower()
    if caption and preset_kind != "oc":
        appearance.extend(value.strip() for value in caption.replace("\n", ",").split(",") if value.strip())
    if caption:
        preset_kind = preset_kind or "oc"
    trigger = next(
        (value for value in identity if value not in {"1girl", "1boy", "female_focus", "male_focus", "original_character"}),
        str(item.get("tag") or "").strip(),
    )
    return {
        "id": item_id,
        "reference_id": target_reference_id,
        "name": str(item.get("label") or item_id),
        "character": str(item.get("label") or item_id),
        "gender": gender,
        "kind": preset_kind,
        "char_caption": caption,
        "trigger": trigger,
        "identity": identity,
        "appearance": appearance,
        "body": [str(value).strip() for value in item.get("body") or [] if str(value).strip()],
        "core_tags": [*identity, *appearance],
        "source": "builtin-preset" if kind == "preset" else "builtin-ark-library",
        "source_id": item_id,
    }


def _merge_catalog_target_record(item: Mapping[str, Any], target_reference_id: str) -> dict[str, Any]:
    """Keep custom OC captions whole; named catalog records still use Anima fields."""

    raw = item.get("raw") if isinstance(item.get("raw"), Mapping) else {}
    merged = dict(raw)
    caption = str(
        merged.get("char_caption")
        or item.get("char_caption")
        or item.get("character_caption")
        or ""
    ).strip()
    gender = str(merged.get("gender") or item.get("gender") or "").strip().lower()
    kind = str(merged.get("kind") or item.get("kind") or "").strip().lower()
    source = str(item.get("source") or merged.get("source") or "").strip().lower()
    is_custom = bool(item.get("is_custom") or merged.get("is_custom") or source == "custom")
    if caption and (kind == "oc" or is_custom):
        merged["kind"] = "oc"
        merged["char_caption"] = caption
        merged["is_custom"] = True
    elif caption and "character_caption" not in merged:
        merged["character_caption"] = caption
    merged["reference_id"] = target_reference_id
    if not merged.get("name"):
        merged["name"] = str(item.get("label") or item.get("name") or "")
    if not merged.get("character"):
        merged["character"] = str(item.get("label") or merged.get("name") or "")
    if gender:
        merged["gender"] = gender
    if item.get("trigger") and not merged.get("trigger"):
        merged["trigger"] = item.get("trigger")
    if item.get("identity") and not merged.get("identity"):
        merged["identity"] = list(item.get("identity") or [])
    return merged


@router.get("/status")
def api_aitag_status() -> dict[str, Any]:
    if not _online_enabled():
        return {"ok": False, "enabled": False, "source": "aitag-online", "local_fallback": True, "generation_calls": 0}
    try:
        client = get_aitag_client()
        return {"ok": True, "enabled": True, "source": "aitag-online", "local_fallback": True, "generation_calls": 0, **client.status()}
    except Exception as exc:
        return {"ok": False, "enabled": True, "source": "aitag-online", "local_fallback": True, "generation_calls": 0, "error": str(exc)}


@router.get("/image/{image_type}/{author_id}/{file_name}")
def api_aitag_image(image_type: str, author_id: str, file_name: str) -> Response:
    client = _require_online()
    try:
        content, content_type = client.get_image(image_type, author_id, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AitagClientError as exc:
        raise _remote_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=600", "X-Generation-Calls": "0"},
    )


@router.get("/cover/{work_id}")
def api_aitag_cover(work_id: str) -> Response:
    client = _require_online()
    detail = _load_detail(client, work_id)
    image = detail.images[0] if detail.images else None
    if image is None or not image.image_type or not image.author_id or not image.file_name:
        raise HTTPException(status_code=404, detail="AITag work cover was not found")
    file_name = str(image.file_name)
    if not file_name.casefold().endswith(".webp"):
        file_name += ".webp"
    try:
        content, content_type = client.get_image(image.image_type, image.author_id, file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AitagClientError as exc:
        raise _remote_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=600", "X-Generation-Calls": "0"},
    )


@router.get("/search")
def api_aitag_search(
    q: str = Query("", max_length=2_000),
    prompt: str = Query("", max_length=2_000),
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(60, ge=1, le=120),
    sort: str = Query("recent", max_length=40),
    time_range: str = Query("all", max_length=40),
    nai_only: bool = Query(True),
    safe_only: bool = Query(True),
    creator: str = "",
    tags: str = "",
    model: str = "",
    min_images: int = 0,
    max_images: int = 0,
) -> dict[str, Any]:
    client = _require_online()
    try:
        result = client.search(
            page=page,
            page_size=page_size,
            query=q,
            prompt=prompt,
            sort=sort,
            time_range=time_range,
            nai_only=nai_only,
            safe_only=safe_only,
        )
    except AitagClientError as exc:
        raise _remote_error(exc) from exc
    try:
        config = client.get_config()
    except Exception:
        config = AitagConfig()
    creator_filter = str(creator or "").strip()[:300]
    tag_filters = _filter_tokens(tags)
    model_filter = str(model or "").strip()[:100]
    minimum = max(0, min(int(min_images or 0), 100_000))
    maximum = max(0, min(int(max_images or 0), 100_000))
    if maximum and minimum > maximum:
        raise HTTPException(status_code=400, detail="min_images must not exceed max_images")
    items = []
    for work in result.works:
        if bool(nai_only) and not aitag_work_is_nai(work):
            continue
        if bool(safe_only) and not aitag_work_is_safe(work):
            continue
        if not _matches_advanced_filters(
            work,
            creator=creator_filter,
            tags=tag_filters,
            model=model_filter,
            min_images=minimum,
            max_images=maximum,
        ):
            continue
        item = work.to_dict()
        item["id"] = item["work_id"]
        item["external_url"] = f"https://aitag.win/i/{item['work_id']}"
        item["title"] = strip_aitag_html(item.get("title") or item["work_id"])
        cover = _search_cover(client, work, config)
        if cover is not None:
            item["images"] = [cover]
        items.append(item)
    return {
        "ok": True,
        "source": "aitag-online",
        "query": result.query,
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        "filtered_count": len(items),
        "has_more": result.has_more,
        "items": items,
        "works": items,
        "nai_only": nai_only,
        "safe_only": safe_only,
        "filters": {
            "creator": creator_filter,
            "tags": list(tag_filters),
            "model": model_filter,
            "min_images": minimum,
            "max_images": maximum,
            "time_range": str(time_range or "all"),
        },
        "local_only": False,
        "generation_calls": 0,
    }


@router.get("/favorites")
def api_aitag_favorites() -> dict[str, Any]:
    items = [
        item
        for item in list_favorite_refs()
        if item.get("gallery_id") == _AITAG_GALLERY_ID
    ]
    return {
        "ok": True,
        "source": _AITAG_GALLERY_ID,
        "count": len(items),
        "ids": [str(item["work_id"]) for item in items],
        "refs": items,
        "generation_calls": 0,
    }


@router.post("/favorites/{work_id}/toggle")
def api_aitag_favorite_toggle(
    work_id: str,
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    identifier = str(work_id or "").strip()
    if not identifier.isdecimal() or int(identifier) <= 0:
        raise HTTPException(status_code=400, detail="AITag work id is invalid")
    if has_favorite(identifier, _AITAG_GALLERY_ID):
        result = remove_favorite(identifier, _AITAG_GALLERY_ID)
        return {**result, "favorited": False, "generation_calls": 0}
    result = add_favorite(
        identifier,
        _AITAG_GALLERY_ID,
        **_favorite_snapshot(payload if isinstance(payload, dict) else {}),
    )
    return {**result, "favorited": True, "generation_calls": 0}


@router.get("/favorites/works")
def api_aitag_favorite_works(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=120),
) -> dict[str, Any]:
    query = str(q or "").strip().casefold()
    refs = [
        item
        for item in list_favorite_refs()
        if item.get("gallery_id") == _AITAG_GALLERY_ID
    ]
    if query:
        refs = [
            item
            for item in refs
            if query in " ".join(
                [
                    str(item.get("work_id") or ""),
                    str(item.get("title") or ""),
                    str(item.get("creator") or ""),
                    " ".join(str(tag) for tag in (item.get("tags") or [])),
                ]
            ).casefold()
        ]
    total = len(refs)
    start = (page - 1) * page_size
    selected = refs[start : start + page_size]
    items: list[dict[str, Any]] = []
    for item in selected:
        identifier = str(item.get("work_id") or "")
        cover_url = str(item.get("cover_url") or f"/api/nai/aitag/cover/{identifier}")
        items.append(
            {
                "id": identifier,
                "work_id": identifier,
                "title": str(item.get("title") or f"AITag #{identifier}"),
                "creator": str(item.get("creator") or ""),
                "AI_type": str(item.get("ai_type") or "NAI"),
                "tags": list(item.get("tags") or []),
                "create_date": str(item.get("create_date") or ""),
                "image_count": int(item.get("image_count") or 0),
                "images": [
                    {
                        "id": f"{identifier}_cover",
                        "image_id": f"{identifier}_cover",
                        "url": cover_url,
                        "thumbnail_url": cover_url,
                    }
                ],
                "external_url": f"https://aitag.win/i/{identifier}",
            }
        )
    return {
        "ok": True,
        "source": _AITAG_GALLERY_ID,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": start + len(items) < total,
        "items": items,
        "works": items,
        "generation_calls": 0,
    }


@router.get("/work/{work_id}")
def api_aitag_work(work_id: str) -> dict[str, Any]:
    client = _require_online()
    try:
        detail = _decorate_detail(client, client.get_work(work_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AitagClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="AITag work was not found") from exc
        raise _remote_error(exc) from exc
    return {"ok": True, **_detail_payload(detail)}


@router.get("/work/{work_id}/characters")
def api_aitag_characters(work_id: str) -> dict[str, Any]:
    detail = _load_detail(_require_online(), work_id)
    return {
        "ok": True,
        "source": "aitag-online",
        "work_id": detail.work.work_id,
        "items": [item.to_dict() for item in discover_character_candidates(detail)],
        "generation_calls": 0,
    }


def _load_detail(client: AitagClient, work_id: str) -> AitagWorkDetail:
    try:
        return _decorate_detail(client, client.get_work(work_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AitagClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="AITag work was not found") from exc
        raise _remote_error(exc) from exc


@router.post("/import")
def api_aitag_import(payload: dict = Body(default_factory=dict)) -> dict[str, Any]:
    client = _require_online()
    work_id = str(payload.get("work_id") or "").strip()
    if not work_id:
        raise HTTPException(status_code=400, detail="work_id is required")
    detail = _load_detail(client, work_id)
    try:
        image_index = int(payload.get("image_index") or 0)
        slot_index = int(payload.get("slot_index") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="image_index and slot_index must be integers") from exc
    if slot_index < 0 or slot_index > 5:
        raise HTTPException(status_code=400, detail="slot_index must be between 0 and 5")
    image = _pick_image(detail, image_index)
    candidate = _pick_candidate(
        detail,
        image_index=image_index,
        slot_index=slot_index,
        candidate_id=str(payload.get("candidate_id") or "").strip(),
    )
    record = candidate.to_reference_record() if candidate else to_reference_record(detail.work, image)
    record["source"] = "aitag-online"
    record["name"] = strip_aitag_html(record.get("name") or detail.work.work_id)
    record["character"] = record["name"]
    record["source_id"] = record.get("source_id") or f"{detail.work.work_id}/{image.image_id}/slot-{slot_index}"
    retrieved_at = datetime.now(timezone.utc).isoformat()
    remote_license = str(
        detail.work.metadata.get("license")
        or detail.work.metadata.get("license_name")
        or ""
    ).strip()[:120]
    license_status = "source-provided" if remote_license else "unknown"
    license_note = str(payload.get("license") or payload.get("license_note") or "").strip()[:500]
    source_url = f"https://aitag.win/i/{detail.work.work_id}"
    provenance = dict(record.get("provenance") or {})
    provenance.update(
        {
            "provider": "aitag-online",
            "source_url": source_url,
            "remote_work_id": detail.work.work_id,
            "remote_image_id": image.image_id,
            "remote_candidate_id": candidate.candidate_id if candidate else "",
            "remote_slot_index": slot_index,
            "retrieved_at": retrieved_at,
            "license_status": license_status,
        }
    )
    if remote_license:
        provenance["source_license"] = remote_license
    if license_note:
        provenance["license_note"] = license_note
    record["provenance"] = provenance
    record["license_status"] = license_status
    record["source_url"] = source_url
    record["retrieved_at"] = retrieved_at
    record["remote_work_id"] = detail.work.work_id
    record["remote_image_id"] = image.image_id
    record["remote_candidate_id"] = candidate.candidate_id if candidate else ""
    record["remote_slot_index"] = slot_index
    record["license_name"] = remote_license or "unknown"
    if license_note:
        record["license_note"] = license_note
    import_result = get_reference_catalog().import_records(
        [record], source="aitag-online", source_label="AITag Online",
        version=detail.work.create_date or image.model or "live",
        license_name=remote_license or "unknown",
        model=str(payload.get("model") or image.model or ""),
    )
    found = get_reference_catalog().search(query=str(record.get("source_id") or ""), source="aitag-online", limit=1, offset=0)
    item = (found.get("items") or [None])[0]
    return {
        "ok": True,
        "source": "aitag-online",
        "work_id": detail.work.work_id,
        "image_id": image.image_id,
        "image_index": image_index,
        "slot_index": slot_index,
        "candidate_id": candidate.candidate_id if candidate else "",
        "reference_id": item.get("reference_id") if isinstance(item, dict) else "",
        "item": item,
        "import": import_result,
        "license_status": license_status,
        "license_name": remote_license or "unknown",
        "source_url": source_url,
        "generation_calls": 0,
        "message": "已保存 AITag 角色 caption 与元数据；图片仍使用远程链接，除非另行下载。",
    }


@router.post("/work/{work_id}/apply")
def api_aitag_apply(work_id: str, payload: dict = Body(default_factory=dict)) -> dict[str, Any]:
    client = _require_online()
    comment = payload.get("comment")
    if not isinstance(comment, dict):
        raise HTTPException(status_code=400, detail="comment must be a Studio draft object")
    detail = _load_detail(client, work_id)
    try:
        image_index = int(payload.get("image_index") or 0)
        slot_index = int(payload.get("slot_index") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="image_index and slot_index must be integers") from exc
    image = _pick_image(detail, image_index)
    candidate = _pick_candidate(
        detail,
        image_index=image_index,
        slot_index=slot_index,
        candidate_id=str(payload.get("candidate_id") or "").strip(),
    )
    record = candidate.to_reference_record() if candidate else to_reference_record(detail.work, image)
    record["source"] = "aitag-online"
    try:
        patched, card = apply_anima_character_to_comment(comment, record, slot_index=slot_index, model=str(payload.get("model") or comment.get("model") or image.model or ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "comment": patched, "texts": prompt_snapshot_from_comment(patched), "card": card, "source": "aitag-online", "work_id": detail.work.work_id, "image_id": image.image_id, "candidate_id": candidate.candidate_id if candidate else "", "slot_index": slot_index, "provider": "aitag-online", "generation_calls": 0, "message": "已将在线 AITag 角色放入 NAI 草稿；点击生成后才会调用 NAI。"}


@router.post("/work/{work_id}/draft")
def api_aitag_draft(work_id: str, payload: dict = Body(default_factory=dict)) -> dict[str, Any]:
    """Create a full Remix/Studio Draft without calling a generation provider.

    Supports the same operator intents as local char-swap:
    - single slot / gender-scope multi-slot character replace
    - all_pages multi-image drafts
    - style find→replace or append on the draft comment
    - base_comment / base_comments stacking (multi-step edits)
    """

    detail = _load_detail(_require_online(), work_id)
    target_reference_id = str(payload.get("target_reference_id") or "").strip()
    target_record = None
    if target_reference_id:
        target_record = _builtin_target_record(target_reference_id)
        if target_record is None:
            item = get_reference_catalog().get(target_reference_id)
            if not isinstance(item, dict):
                raise HTTPException(status_code=404, detail="Target character reference was not found")
            target_record = _merge_catalog_target_record(item, target_reference_id)
            if not target_record:
                raise HTTPException(status_code=400, detail="Target character reference is invalid")
    # Only accept explicit gender_scope — do not reuse payload "gender" (target gender).
    gender_scope = str(payload.get("gender_scope") or "").strip().lower()
    if gender_scope in {"all_male", "replace_male"}:
        gender_scope = "male"
    if gender_scope in {"all_female", "replace_female"}:
        gender_scope = "female"
    style_find = str(payload.get("style_find") or payload.get("find") or "")
    style_replace = str(
        payload.get("style_replace")
        if payload.get("style_replace") is not None
        else payload.get("replace")
        if payload.get("replace") is not None
        else ""
    )
    # Prefer style_mode; ignore generic "mode" unless style fields are present.
    if payload.get("style_mode") is not None:
        style_mode = str(payload.get("style_mode") or "replace").strip().lower()
    elif style_find or style_replace:
        style_mode = str(payload.get("mode") or "replace").strip().lower()
    else:
        style_mode = "replace"
    if style_mode not in {"replace", "append"}:
        style_mode = "replace"
    raw_slot_indexes = payload.get("slot_indexes")
    slot_indexes = None
    if isinstance(raw_slot_indexes, (list, tuple)):
        try:
            slot_indexes = [int(v) for v in raw_slot_indexes]
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="slot_indexes must be integers") from exc
    try:
        image_index = int(payload.get("image_index") or 0)
        slot_index = int(payload.get("slot_index") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="image_index and slot_index must be integers") from exc

    all_pages = payload.get("all_pages") is True or str(payload.get("scope") or "").strip().lower() in {
        "all_pages",
        "all",
        "all_images",
    }

    # Resolve candidate_id → (image_index, slot_index) when provided.
    # Skip for all_pages: gender-scope multi-page must not be pinned to one candidate slot.
    candidate_id = str(payload.get("candidate_id") or "").strip()
    if candidate_id and not all_pages:
        from aitag_core.recipe import discover_character_candidates

        matched = False
        for cand in discover_character_candidates(detail):
            if str(cand.candidate_id) == candidate_id:
                image_index = int(cand.image_index)
                slot_index = int(cand.slot_index)
                matched = True
                break
        if not matched:
            raise HTTPException(
                status_code=400,
                detail=f"candidate_id 未找到：{candidate_id}",
            )

    # Stacking: accept previous draft comment(s) so sequential edits accumulate.
    base_comment = payload.get("base_comment")
    if base_comment is not None and not isinstance(base_comment, dict):
        raise HTTPException(status_code=400, detail="base_comment must be an object")
    base_comments_raw = payload.get("base_comments")
    base_comments: dict[int, dict] | None = None
    if isinstance(base_comments_raw, dict):
        base_comments = {}
        for key, value in base_comments_raw.items():
            if not isinstance(value, dict):
                continue
            try:
                base_comments[int(key)] = value
            except (TypeError, ValueError):
                continue
    elif isinstance(base_comments_raw, list):
        base_comments = {}
        for item in base_comments_raw:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("image_index") or item.get("page_index") or 0)
            except (TypeError, ValueError):
                continue
            comment = item.get("comment") if isinstance(item.get("comment"), dict) else item
            if isinstance(comment, dict) and (comment.get("prompt") is not None or comment.get("v4_prompt")):
                base_comments[idx] = comment

    try:
        compile_kwargs = {
            "slot_index": slot_index,
            "gender_scope": gender_scope,
            "target_record": target_record,
            "target_reference_id": target_reference_id,
            "style_find": style_find,
            "style_replace": style_replace,
            "style_mode": style_mode,
            "model": str(payload.get("model") or ""),
            "batch_count": int(payload.get("batch_count") or 1),
        }
        if all_pages:
            if base_comments is None and isinstance(base_comment, dict):
                base_comments = {image_index: base_comment}
            compiled = compile_aitag_studio_drafts(
                detail,
                base_comments=base_comments,
                **compile_kwargs,
            )
        else:
            stacked = base_comment
            if stacked is None and base_comments and image_index in base_comments:
                stacked = base_comments[image_index]
            compiled = compile_aitag_studio_draft(
                detail,
                image_index=image_index,
                slot_indexes=slot_indexes,
                base_comment=stacked if isinstance(stacked, dict) else None,
                **compile_kwargs,
            )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    persisted = True
    persistence_warning = ""
    try:
        # Persist primary draft + multi-page package for Studio/cross-tab recovery.
        stored = save_studio_draft(
            compiled,
            source="aitag-online",
            root=DATA_DIR,
            ttl_seconds=_draft_ttl_seconds(),
        )
        draft_id = str(stored.get("draft_id") or "")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        # Persistence is useful for cross-tab recovery, but it is not part of
        # compilation. Keep the zero-generation draft usable via localStorage.
        persisted = False
        draft_id = ""
        persistence_warning = str(exc)[:300]
    studio_url = (
        f"/studio?aitag=1&remix=1&draft={draft_id}"
        if persisted
        else "/studio?aitag=1&remix=1"
    )
    page_count = int(compiled.get("page_count") or 1)
    requested_pages = int(compiled.get("requested_pages") or page_count)
    style_hits = int(compiled.get("style_replacements") or 0)
    if all_pages:
        style_hits = sum(int(p.get("style_replacements") or 0) for p in (compiled.get("pages") or []))
    partial = bool(compiled.get("partial"))
    failed = list(compiled.get("failed_pages") or compiled.get("errors") or [])
    if partial:
        message_bits = [
            f"部分成功 {page_count}/{requested_pages} 页",
            f"失败：{'; '.join(str(x) for x in failed[:4])}" if failed else "部分页失败",
        ]
    else:
        message_bits = [
            f"草稿已就绪（{page_count} 页）" if all_pages else "草稿已就绪",
        ]
    message_bits.append("已持久化" if persisted else "本地草稿")
    if target_reference_id:
        message_bits.append("含换角")
    if style_find or style_replace:
        if style_hits:
            message_bits.append(f"画风改写 {style_hits} 处")
        else:
            message_bits.append("画风未匹配到可替换片段（0 处）")
    message_bits.append("点击生成前不会调用 NAI")
    return {
        "ok": True,
        **compiled,
        "draft_id": draft_id,
        "persisted": persisted,
        "persistence_warning": persistence_warning,
        "source": "aitag-online",
        "provider": "aitag-online",
        "studio_url": studio_url,
        "generation_calls": 0,
        "all_pages": all_pages,
        "partial": partial,
        "failed_pages": failed,
        "message": "；".join(message_bits) + "。",
    }


@router.post("/drafts/latest/restore")
def api_aitag_draft_latest() -> dict[str, Any]:
    """Return the newest persisted AITag Studio draft without generation side effects."""

    record = get_latest_studio_draft(
        source="aitag-online", root=DATA_DIR, ttl_seconds=_draft_ttl_seconds()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="No persisted AITag studio draft was found")
    return public_draft_response(record)


@router.get("/drafts/{draft_id}")
def api_aitag_draft_get(draft_id: str) -> dict[str, Any]:
    """Load a previously saved zero-generation Studio draft by id."""

    record = get_studio_draft(
        draft_id, root=DATA_DIR, ttl_seconds=_draft_ttl_seconds()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Studio draft was not found")
    return public_draft_response(record)


@router.post("/cache/clear")
def api_aitag_cache_clear() -> dict[str, Any]:
    client = _require_online()
    return {"ok": True, "removed": client.clear_cache(), "source": "aitag-online", "generation_calls": 0}


__all__ = ["router", "get_aitag_client"]
