"""NAI Studio business logic — import, sanitize, optimize, vibe helpers."""

from __future__ import annotations

import base64
import copy
from pathlib import Path
from typing import Any

from nai_batch import STUDIO_COPY_MAX
from nai_char import extract_chars, sanitize_payload
from nai_prompt_optimizer import _prompt_snapshot, ai_status, optimize_nai_prompt
from gallery_cache import cached
from paths import canonical_path, path_is_within
from server_shared import DB, DATA_DIR

STUDIO_IMPORT_PAGE_MAX = 64


def _gallery_db(gallery_id: str = "site"):
    gid = str(gallery_id or "site").strip() or "site"
    if gid == "site":
        return DB
    from gallery_catalog import get_db, normalize_gallery_id

    return get_db(normalize_gallery_id(gid))


def _image_public_url(image: dict[str, Any] | None) -> str:
    if not isinstance(image, dict):
        return ""
    local_path = str(image.get("local_path") or "").strip().replace("\\", "/")
    if local_path:
        local_path = local_path.lstrip("/")
        if local_path.startswith("data/images/"):
            local_path = local_path.removeprefix("data/images/")
        elif local_path.startswith("images/"):
            local_path = local_path.removeprefix("images/")
        return f"/data/images/{local_path}"

    image_type = str(image.get("image_type") or "").strip()
    author_id = str(image.get("author_id") or "").strip()
    file_name = str(image.get("file_name") or "").strip()
    if image_type and author_id and file_name:
        suffix = "" if file_name.lower().endswith(".webp") else ".webp"
        return f"/data/images/{image_type}/{author_id}/{file_name}{suffix}"
    return ""


def _work_thumb(work_id: int, gallery_id: str = "site", page_index: int = 0) -> str:
    try:
        detail = _gallery_db(gallery_id).get_work_detail(int(work_id))
        images = (detail or {}).get("images") or []
        wanted = int(page_index or 0)
        chosen = None
        for image in images:
            if not isinstance(image, dict):
                continue
            raw = image.get("page_index")
            if raw is None:
                raw = image.get("source_page_index")
            try:
                idx = int(raw if raw is not None else 0)
            except (TypeError, ValueError):
                idx = 0
            if idx == wanted:
                chosen = image
                break
        if chosen is None and images:
            chosen = images[0]
        return _image_public_url(chosen)
    except Exception:
        return ""


def _work_page_indexes(
    work_id: int, gallery_id: str = "site", fallback: int = 0
) -> list[int]:
    try:
        detail = _gallery_db(gallery_id).get_work_detail(int(work_id))
    except Exception:
        return [int(fallback or 0)]
    images = (detail or {}).get("images") or []
    indexes: list[int] = []
    seen: set[int] = set()
    for i, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        raw = image.get("page_index")
        if raw is None:
            raw = image.get("source_page_index")
        if raw is None:
            raw = image.get("display_page_index")
        try:
            idx = int(raw if raw is not None else i)
        except (TypeError, ValueError):
            idx = i
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        indexes.append(idx)
        if len(indexes) >= STUDIO_IMPORT_PAGE_MAX:
            break
    return indexes or [int(fallback or 0)]


def _work_title(work_id: int, gallery_id: str = "site") -> str:
    try:
        detail = _gallery_db(gallery_id).get_work_detail(int(work_id))
        work = (detail or {}).get("work") or {}
        title = str(work.get("title") or work.get("caption") or "").strip()
        if title:
            return title
    except Exception:
        pass
    return f"作品 {work_id}"


def preview_work_prompt(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    wid = int(work_id)
    page = int(page_index)
    gid = str(gallery_id or "site").strip() or "site"
    cache_key = f"studio_preview:{gid}:{wid}:{page}"

    def _load() -> dict[str, Any]:
        row = _gallery_db(gid).get_work_prompt_snippet(wid, page)
        snippet = str(row.get("snippet") or "").strip()
        return {
            "ok": True,
            "work_id": wid,
            "page_index": int(row.get("page_index") or page),
            "snippet": snippet,
            "has_prompt": bool(snippet),
            "source": row.get("source") or "none",
            "gallery_id": gid,
        }

    return cached(cache_key, 600.0, _load)


def _page_pack(
    work_id: int,
    page_index: int,
    gallery_id: str,
    data: dict[str, Any],
    *,
    title: str,
    thumb: str,
) -> dict[str, Any]:
    comment = copy.deepcopy(data.get("comment") or {})
    return {
        "image_index": int(page_index),
        "draft": {
            "texts": _prompt_snapshot(comment),
            "comment": comment,
            "params": data.get("params") or {},
            "pageIndex": int(page_index),
            "source": {
                "provider": gallery_id,
                "workId": int(work_id),
                "imageIndex": int(page_index),
                "title": title,
                "thumb": thumb,
            },
        },
    }


def _select_import_page(payload: dict[str, Any], page_index: int) -> dict[str, Any]:
    pages = payload.get("pages") or []
    wanted = int(page_index or 0)
    hit = next(
        (page for page in pages if int(page.get("image_index") or 0) == wanted),
        None,
    )
    if not isinstance(hit, dict):
        return payload
    draft = hit.get("draft") if isinstance(hit.get("draft"), dict) else {}
    source = draft.get("source") if isinstance(draft.get("source"), dict) else {}
    selected = dict(payload)
    selected["page_index"] = wanted
    selected["comment"] = draft.get("comment") or payload.get("comment")
    selected["texts"] = draft.get("texts") or payload.get("texts")
    selected["params"] = draft.get("params") or payload.get("params")
    selected["thumb"] = source.get("thumb") or payload.get("thumb")
    return selected


def _import_from_work_uncached(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    requested = int(page_index or 0)
    data = extract_chars(int(work_id), requested, gallery_id=gallery_id)
    title = _work_title(work_id, gallery_id)
    pages: list[dict[str, Any]] = []
    extracted = {requested: data}
    for idx in _work_page_indexes(work_id, gallery_id, fallback=requested):
        page_data = extracted.get(idx)
        if page_data is None:
            try:
                page_data = extract_chars(int(work_id), int(idx), gallery_id=gallery_id)
            except Exception:
                continue
            extracted[idx] = page_data
        pages.append(
            _page_pack(
                work_id,
                idx,
                gallery_id,
                page_data,
                title=title,
                thumb=_work_thumb(work_id, gallery_id, idx),
            )
        )
    if not pages:
        pages.append(
            _page_pack(
                work_id,
                requested,
                gallery_id,
                data,
                title=title,
                thumb=_work_thumb(work_id, gallery_id, requested),
            )
        )
    comment = copy.deepcopy(data.get("comment") or {})
    payload = {
        "ok": True,
        "work_id": int(work_id),
        "page_index": requested,
        "gallery_id": gallery_id,
        "title": title,
        "thumb": _work_thumb(work_id, gallery_id, requested),
        "comment": comment,
        "params": data.get("params") or {},
        "chars": data.get("chars") or [],
        "base_caption": data.get("base_caption") or "",
        "texts": _prompt_snapshot(comment),
        "page_count": len(pages),
        "pages": pages,
    }
    return _select_import_page(payload, requested)


def import_from_work(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    wid = int(work_id)
    page = int(page_index)
    gid = str(gallery_id or "site").strip() or "site"
    cache_key = f"studio_import:{gid}:{wid}"
    payload = cached(cache_key, 300.0, lambda: _import_from_work_uncached(wid, page, gid))
    return _select_import_page(payload, page)


def sanitize_comment(comment: dict[str, Any], **flags: Any) -> dict[str, Any]:
    result = sanitize_payload(
        {
            "patched_comment": comment,
            "filter_racial": flags.get("filter_racial", True),
            "filter_gore": flags.get("filter_gore", True),
            "filter_creature": flags.get("filter_creature", False),
        }
    )
    patched = result.get("patched_comment") or comment
    return {
        "ok": True,
        "comment": patched,
        "texts": _prompt_snapshot(patched),
        "removed": result.get("removed") or [],
        "message": result.get("message") or "",
    }


def optimize_comment(comment: dict[str, Any], *, mode: str = "smart", profile: str = "") -> dict[str, Any]:
    try:
        return optimize_nai_prompt(comment, mode=mode, profile=profile)
    except Exception as exc:
        if mode == "smart":
            before = _prompt_snapshot(comment)
            local = optimize_nai_prompt(comment, mode="sanitize")
            local["fallback"] = True
            local["fallback_reason"] = str(exc)
            local["before"] = before
            local["message"] = f"智能优化失败，已降级为本地净化：{exc}"
            return local
        raise


def attach_image_reference(
    comment: dict[str, Any],
    *,
    image_url: str = "",
    work_id: int | None = None,
    page_index: int = 0,
    kind: str = "vibe",
    strength: float = 0.6,
) -> dict[str, Any]:
    url = str(image_url or "").strip()
    if not url and work_id:
        detail = import_from_work(int(work_id), int(page_index))
        url = str(detail.get("thumb") or "").strip()
        if url and not url.startswith("http"):
            url = url if url.startswith("/") else f"/data/images/{url}"
    if not url:
        raise ValueError("需要参考图 URL 或有效作品 ID")
    if kind == "char":
        patched = copy.deepcopy(comment or {})
        patched["reference_image_multiple"] = [url]
        patched["reference_strength_multiple"] = [max(0.01, min(float(strength), 1.0))]
        return {"ok": True, "comment": patched, "image_url": url, "kind": "char"}
    vibe = apply_vibe_to_comment(
        comment,
        image_url=url,
        strength=strength,
    )
    vibe["image_url"] = url
    vibe["kind"] = "vibe"
    return vibe


def _resolve_vibe_image_path(image_path: str) -> Path:
    raw = str(image_path or "").strip()
    if not raw:
        raise ValueError("需要 vibe 参考图 URL 或本地路径")
    path = Path(raw)
    if not path.is_absolute():
        path = DATA_DIR / path
    resolved = canonical_path(path)
    data_root = canonical_path(DATA_DIR)
    if resolved == data_root or not path_is_within(resolved, data_root):
        raise ValueError("vibe 参考图必须位于本地数据目录内")
    if not resolved.is_file():
        raise ValueError("vibe 参考图不存在")
    return resolved


def apply_vibe_to_comment(
    comment: dict[str, Any],
    *,
    image_url: str = "",
    image_path: str = "",
    strength: float = 0.6,
    information_extracted: float = 1.0,
) -> dict[str, Any]:
    patched = copy.deepcopy(comment or {})
    refs: list[str] = []
    if image_url:
        refs.append(str(image_url).strip())
    elif image_path:
        path = _resolve_vibe_image_path(image_path)
        raw = path.read_bytes()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        refs.append(f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}")
    if not refs:
        raise ValueError("需要 vibe 参考图 URL 或本地路径")
    strengths = [max(0.01, min(float(strength), 1.0))]
    info = [max(0.0, min(float(information_extracted), 1.0))]
    patched["xianyun_vibe"] = {
        "reference_images": refs,
        "reference_strength_multiple": strengths,
        "reference_information_extracted_multiple": info,
    }
    return {
        "ok": True,
        "comment": patched,
        "image_url": refs[0] if refs else "",
        "kind": "vibe",
    }


def studio_config() -> dict[str, Any]:
    return {
        "ok": True,
        "ai": ai_status(),
        "optimize_modes": [
            {"id": "smart", "label": "智能优化", "description": "LLM 改写为更适合 NAI 出图的咒语"},
            {"id": "sanitize", "label": "仅净化", "description": "本地去敏感/无效 tag"},
            {"id": "anima_faithful", "label": "Anima V1（本地）", "description": "可选本地风格预设"},
            {"id": "anima_epic", "label": "Anima V2（本地）", "description": "可选本地风格预设"},
            {"id": "native", "label": "保持原样", "description": "不改动咒语"},
        ],
        # Inspired by NovelAI / common WebUI size presets
        "size_presets": [
            {"id": "portrait", "label": "竖图 832×1216", "width": 832, "height": 1216},
            {"id": "landscape", "label": "横图 1216×832", "width": 1216, "height": 832},
            {"id": "square", "label": "方图 1024×1024", "width": 1024, "height": 1024},
            {"id": "portrait_sm", "label": "竖图 640×960", "width": 640, "height": 960},
            {"id": "wide", "label": "超宽 1472×832", "width": 1472, "height": 832},
        ],
        "samplers": [
            "k_euler_ancestral",
            "k_euler",
            "k_dpmpp_2s_ancestral",
            "k_dpmpp_2m",
            "k_dpmpp_sde",
            "ddim_v3",
        ],
        "defaults": {
            "width": 832,
            "height": 1216,
            "steps": 28,
            "scale": 5.0,
            "sampler": "k_euler_ancestral",
            "batch_count": 1,
        },
        "copy_max": STUDIO_COPY_MAX,
    }


def list_queue_for_studio(limit: int = 40) -> dict[str, Any]:
    """Production queue items for Studio asset picker."""
    try:
        from production_queue import list_refs
    except Exception:
        return {"ok": True, "items": [], "count": 0}
    refs = list_refs()[: max(1, min(int(limit), 120))]
    items: list[dict[str, Any]] = []
    for item in refs:
        try:
            wid = int(item.get("work_id") or 0)
        except (TypeError, ValueError):
            continue
        if wid <= 0:
            continue
        gid = str(item.get("gallery_id") or "site").strip() or "site"
        items.append(
            {
                "work_id": wid,
                "gallery_id": gid,
                "title": _work_title(wid, gid),
                "thumb": _work_thumb(wid, gid),
            }
        )
    return {"ok": True, "items": items, "count": len(items)}


def build_studio_draft(
    comment: dict[str, Any] | None = None,
    *,
    work_id: int = 0,
    page_index: int = 0,
    title: str = "",
    thumb: str = "",
    batch_count: int = 1,
) -> dict[str, Any]:
    """Build the stable local Studio Draft shared by manual and Butler flows."""
    patched = copy.deepcopy(comment or {})
    defaults = studio_config().get("defaults") or {}
    params = {
        key: patched.get(key, defaults.get(key))
        for key in ("width", "height", "steps", "scale", "sampler", "seed")
    }
    params["batch"] = max(1, min(int(batch_count or 1), 64))
    return {
        "galleryId": "site",
        "workId": int(work_id or 0),
        "pageIndex": max(0, int(page_index or 0)),
        "title": str(title or (f"Work {work_id}" if work_id else "Studio Draft")),
        "thumb": str(thumb or ""),
        "comment": patched,
        "texts": _prompt_snapshot(patched),
        "params": params,
        "refs": {"vibe": "", "char": "", "strength": "0.6"},
    }
