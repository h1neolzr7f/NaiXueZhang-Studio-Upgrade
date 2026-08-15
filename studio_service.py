"""NAI Studio business logic — import, sanitize, optimize, vibe helpers."""

from __future__ import annotations

import base64
import copy
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from nai_char import extract_chars, sanitize_payload
from nai_prompt_optimizer import _prompt_snapshot, ai_status, optimize_nai_prompt
from gallery_cache import cached
from server_shared import DB, DATA_DIR

SOURCE_IMAGE_MAX_BYTES = 12 * 1024 * 1024


def _gallery_db(gallery_id: str = "site"):
    gid = str(gallery_id or "site").strip() or "site"
    if gid == "site":
        return DB
    from gallery_catalog import get_db, normalize_gallery_id

    return get_db(normalize_gallery_id(gid))


def _work_thumb(work_id: int, gallery_id: str = "site") -> str:
    try:
        detail = _gallery_db(gallery_id).get_work_detail(int(work_id))
        images = (detail or {}).get("images") or []
        if images:
            image = images[0]
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
    except Exception:
        pass
    return ""


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


def preview_work_prompt(work_id: int, page_index: int = 0) -> dict[str, Any]:
    wid = int(work_id)
    page = int(page_index)
    cache_key = f"studio_preview:{wid}:{page}"

    def _load() -> dict[str, Any]:
        row = DB.get_work_prompt_snippet(wid, page)
        snippet = str(row.get("snippet") or "").strip()
        return {
            "ok": True,
            "work_id": wid,
            "page_index": int(row.get("page_index") or page),
            "snippet": snippet,
            "has_prompt": bool(snippet),
            "source": row.get("source") or "none",
        }

    return cached(cache_key, 600.0, _load)


def _import_from_work_uncached(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    data = extract_chars(int(work_id), int(page_index), gallery_id=gallery_id)
    comment = copy.deepcopy(data.get("comment") or {})
    return {
        "ok": True,
        "work_id": int(work_id),
        "page_index": int(page_index),
        "gallery_id": gallery_id,
        "title": _work_title(work_id, gallery_id),
        "thumb": _work_thumb(work_id, gallery_id),
        "comment": comment,
        "params": data.get("params") or {},
        "chars": data.get("chars") or [],
        "base_caption": data.get("base_caption") or "",
        "texts": _prompt_snapshot(comment),
    }


def resolve_work_image_path(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> Path | None:
    """Resolve a downloaded work image without leaving the gallery root."""

    db = _gallery_db(gallery_id)
    row = db.conn.execute(
        """
        SELECT local_path FROM work_images
        WHERE work_id = ? AND page_index = ? AND downloaded = 1
        """,
        (int(work_id), int(page_index)),
    ).fetchone()
    if row is None:
        return None
    relative = str(row["local_path"] or "").strip()
    if not relative:
        return None
    path = Path(relative)
    if path.is_absolute() and path.exists():
        return path
    from gallery_catalog import get_spec
    from paths import canonical_path, path_is_within

    spec = get_spec(gallery_id)
    candidates = [
        spec.images_dir / relative,
        DATA_DIR / relative,
        DATA_DIR / "images" / relative,
    ]
    for candidate in candidates:
        resolved = canonical_path(candidate)
        if not resolved.exists() or not resolved.is_file():
            continue
        if path_is_within(resolved, spec.images_dir) or path_is_within(resolved, DATA_DIR):
            return resolved
    return None


def encode_local_source_image(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > SOURCE_IMAGE_MAX_BYTES:
        raise ValueError("source image too large")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("source image could not be decoded") from exc
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "ok": True,
        "image": encoded,
        "mime": "image/png",
        "width": int(image.width),
        "height": int(image.height),
        "bytes": len(buf.getvalue()),
    }


def source_image_for_work(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    path = resolve_work_image_path(work_id, page_index, gallery_id)
    if path is None:
        raise ValueError("local source image is missing")
    payload = encode_local_source_image(path)
    payload.update(
        {
            "work_id": int(work_id),
            "page_index": int(page_index),
            "gallery_id": str(gallery_id or "site"),
            "thumb": _work_thumb(int(work_id), str(gallery_id or "site")),
            "title": _work_title(int(work_id), str(gallery_id or "site")),
        }
    )
    return payload


def import_from_work(
    work_id: int, page_index: int = 0, gallery_id: str = "site"
) -> dict[str, Any]:
    wid = int(work_id)
    page = int(page_index)
    gid = str(gallery_id or "site").strip() or "site"
    cache_key = f"studio_import:{gid}:{wid}:{page}"
    return cached(cache_key, 300.0, lambda: _import_from_work_uncached(wid, page, gid))


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
        path = Path(image_path)
        if not path.is_absolute():
            path = (DATA_DIR / path).resolve()
        if path.exists():
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
    }


def list_queue_for_studio(limit: int = 40) -> dict[str, Any]:
    """Production queue items for Studio asset picker."""
    try:
        from production_queue import list_ids
    except Exception:
        return {"ok": True, "items": [], "count": 0}
    ids = list_ids()[: max(1, min(int(limit), 120))]
    items: list[dict[str, Any]] = []
    for wid in ids:
        items.append(
            {
                "work_id": wid,
                "title": _work_title(wid),
                "thumb": _work_thumb(wid),
            }
        )
    return {"ok": True, "items": items, "count": len(ids)}


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
