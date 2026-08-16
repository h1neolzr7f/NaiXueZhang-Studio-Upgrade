from fastapi import APIRouter, Body, HTTPException, Query
from server_shared import CONFIG, DB, GALLERY_SCOPE, GALLERY_LOCAL_ONLY
from api_schemas import CharSwapBatchRunRequest
from nai_char import (
    extract_chars,
    transform,
    sanitize_payload,
    apply_style_payload,
    batch_preview,
    list_char_presets,
    reload_style_index,
    style_index_stats,
    BATCH_TARGET_MAX,
)
from char_tag_db import index_stats, reload_index
from char_swap_config import CONFIG_LOCK as CHAR_SWAP_CONFIG_LOCK
from char_swap_config import load_config as load_char_swap_config, save_config as save_char_swap_config
from nai_prompt_profiles import PROMPT_PROFILE_CHOICES
from ark_char_library import search_library, library_stats, reload_library
from gallery_catalog import normalize_gallery_id, serialize_gallery_payload
from nai_authorization import ACTION_CHAR_SWAP, compile_batch_authorization, issue_http_preview
from nai_batch import (
    start_batch,
    batch_status,
    cancel_batch,
    reorder_batch,
    retry_batch,
)
from nai_anima_adapter import adapt_anima_character

router = APIRouter(prefix="/api/plugin/char-swap")


@router.post("/nai-reference/preview")
def api_nai_reference_preview(payload: dict = Body(default_factory=dict)) -> dict:
    record = payload.get("record")
    if not isinstance(record, dict):
        raise HTTPException(status_code=400, detail="record must be an object")
    try:
        card = adapt_anima_character(
            record,
            model=str(payload.get("model") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "card": card,
        "provider": "local",
        "generation_calls": 0,
    }

@router.get("/ark-library")
def api_ark_char_library(
    gender: str = Query(""),
    q: str = "",
    limit: int = Query(80, ge=1, le=200),
) -> dict:
    g = gender.strip().lower()
    if g not in {"", "male", "female", "all"}:
        raise HTTPException(status_code=400, detail="invalid gender")
    return search_library(
        gender=None if g in {"", "all"} else g,
        q=q,
        limit=limit,
    )

@router.get("/ark-library/stats")
def api_ark_char_library_stats() -> dict:
    return library_stats()

@router.post("/ark-library/reload")
def api_ark_char_library_reload() -> dict:
    data = reload_library()
    return {
        "ok": True,
        "built_at": data.get("built_at"),
        "female_count": data.get("female_count"),
        "male_count": data.get("male_count"),
    }

@router.get("/tag-index")
def api_char_tag_index_stats() -> dict:
    return {"ok": True, "stats": index_stats(), "style_stats": style_index_stats()}

@router.post("/tag-index/reload")
def api_char_tag_index_reload() -> dict:
    reload_index()
    return {
        "ok": True,
        "stats": index_stats(),
        "style_stats": reload_style_index(),
        "message": "Character/style tag index reloaded",
    }

@router.get("/extract")
def api_char_swap_extract(
    work_id: int = Query(..., ge=1),
    page_index: int = Query(0, ge=0),
    gallery_id: str = Query("site"),
) -> dict:
    try:
        gid = normalize_gallery_id(gallery_id)
        return serialize_gallery_payload(
            {
                "ok": True,
                "data": extract_chars(work_id, page_index, gid),
            },
            gid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/transform")
def api_char_swap_transform(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return transform(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"变换失败: {exc}") from exc

@router.post("/sanitize")
def api_char_swap_sanitize(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return sanitize_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/style")
def api_char_swap_style(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return apply_style_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/batch/preview")
def api_char_swap_batch_preview(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return batch_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/batch/authorize")
def api_char_swap_batch_authorize(payload: CharSwapBatchRunRequest) -> dict:
    preview = compile_batch_authorization(
        list(payload.targets or []),
        dict(payload.recipe or {}),
        force_free=bool(payload.force_free),
        action=ACTION_CHAR_SWAP,
    )
    issued = issue_http_preview(preview, confirmed=bool(payload.confirmed))
    if issued.get("error") == "quantity_limit":
        raise HTTPException(status_code=400, detail=str(issued.get("message") or "copies exceed cap"))
    return {
        "ok": True,
        "requires_ticket": bool(issued.get("requires_ticket")),
        "free_eligible": bool(issued.get("free_eligible")),
        "needs_confirmation": bool(issued.get("needs_confirmation")),
        "local_trust": True,
        "max_copies": issued.get("max_copies"),
        "ticket": issued.get("ticket") or "",
        "copies": issued.get("copies"),
        "action": issued.get("action"),
        "compiled": issued.get("compiled") or [],
        "payload_hash": issued.get("payload_hash"),
        "manifest_hash": issued.get("manifest_hash"),
        "message": (
            "需要确认后才能签发付费授权票据"
            if issued.get("requires_ticket")
            else "免费标准路径，无需授权票据"
        ),
    }


@router.post("/batch/run")
async def api_char_swap_batch_run(payload: CharSwapBatchRunRequest) -> dict:
    try:
        result = start_batch(
            list(payload.targets or []),
            dict(payload.recipe or {}),
            force_free=bool(payload.force_free),
            generate=bool(payload.generate),
            preview_only=bool(payload.preview_only),
            authorization_ticket=str(payload.authorization_ticket or ""),
            authorization_action="char_swap_batch",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("ok"):
        error = str(result.get("error") or "")
        if error in {
            "authorization_required",
            "ticket_invalid",
            "ticket_expired",
            "ticket_replay",
            "ticket_hash_mismatch",
        }:
            raise HTTPException(status_code=403, detail=str(result.get("message") or "authorization required"))
        if error == "missing_token":
            raise HTTPException(status_code=400, detail=str(result.get("message") or "NovelAI token is not configured"))
        if error == "persistence_failed":
            raise HTTPException(status_code=503, detail=str(result.get("message") or "generation job could not be persisted"))
    return result

@router.get("/batch/status")
def api_char_swap_batch_status(task_id: str = Query("")) -> dict:
    batch = batch_status(task_id or None)
    if task_id and (
        batch is None
        or batch.get("status") == "not_found"
        or batch.get("error") == "not_found"
    ):
        raise HTTPException(status_code=404, detail="generation task not found")
    return {"ok": True, "batch": batch}

@router.post("/batch/cancel")
def api_char_swap_batch_cancel(task_id: str = Query("")) -> dict:
    result = cancel_batch(task_id or None)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.post("/batch/retry")
async def api_char_swap_batch_retry(task_id: str = Query(...)) -> dict:
    result = retry_batch(task_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message"))
    return result


@router.post("/batch/reorder")
def api_char_swap_batch_reorder(
    payload: dict = Body(default_factory=dict),
) -> dict:
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    try:
        position = int(payload.get("position") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="position must be an integer") from exc
    result = reorder_batch(task_id, position)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result

@router.get("/presets")
def api_char_swap_presets(gender: str = Query("")) -> dict:
    g = gender if gender in {"male", "female"} else None
    return {"ok": True, "presets": list_char_presets(g)}

@router.get("/config")
def api_char_swap_config_get() -> dict:
    cfg = dict(load_char_swap_config())
    cfg["batch_target_max"] = BATCH_TARGET_MAX
    cfg["prompt_profile_choices"] = PROMPT_PROFILE_CHOICES
    return {"ok": True, "config": cfg}

@router.post("/config")
def api_char_swap_config_set(payload: dict = Body(default_factory=dict)) -> dict:
    cfg = save_char_swap_config(payload)
    return {"ok": True, "config": cfg, "message": "Plugin config saved"}

@router.post("/presets")
def api_char_swap_preset_add(payload: dict = Body(default_factory=dict)) -> dict:
    gender = str(payload.get("gender") or "female")
    if gender not in {"male", "female"}:
        raise HTTPException(status_code=400, detail="gender 须为 male 或 female")
    char_caption = str(payload.get("char_caption") or "").strip()
    kind = str(payload.get("kind") or "").strip().lower()
    if char_caption and kind != "oc":
        kind = "oc"
    label = str(payload.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不能为空")
    if len(label) > 80:
        raise HTTPException(status_code=400, detail="label 最多 80 个字符")
    if len(char_caption) > 8000:
        raise HTTPException(status_code=400, detail="char_caption 最多 8000 个字符")

    def tag_list(field: str) -> list[str]:
        raw = payload.get(field)
        if raw is None:
            return []
        if not isinstance(raw, (list, tuple)):
            raise HTTPException(status_code=400, detail=f"{field} 须为字符串数组")
        if len(raw) > 256:
            raise HTTPException(status_code=400, detail=f"{field} 最多 256 项")
        values = [str(item).strip() for item in raw if str(item).strip()]
        if any(len(item) > 256 for item in values):
            raise HTTPException(status_code=400, detail=f"{field} 单项最多 256 个字符")
        return values

    preset = {
        "id": str(payload.get("id") or f"custom_{gender}_{__import__('time').time_ns()}"),
        "label": label,
        "gender": gender,
        "is_custom": True,
        "source": "custom",
        "identity": tag_list("identity"),
        "body": tag_list("body"),
        "appearance": tag_list("appearance"),
        "clothing": str(payload.get("clothing") or "").strip(),
        "extra": str(payload.get("extra") or "").strip(),
        "remove": tag_list("remove"),
    }
    if kind == "oc" or char_caption:
        preset["kind"] = "oc"
        if char_caption:
            preset["char_caption"] = char_caption
    for k in ("clothing", "extra"):
        if not preset.get(k):
            preset.pop(k, None)
    if not preset.get("remove"):
        preset.pop("remove", None)
    if preset.get("kind") == "oc" and not char_caption:
        if not (preset.get("identity") or preset.get("body") or preset.get("appearance")):
            raise HTTPException(
                status_code=400,
                detail="OC preset requires char_caption or identity/body/appearance",
            )
    with CHAR_SWAP_CONFIG_LOCK:
        cfg = load_char_swap_config()
        custom = cfg.get("custom_presets") or {"male": [], "female": []}
        pool = list(custom.get(gender) or [])
        if any(str(item.get("label") or "").strip().casefold() == label.casefold() for item in pool):
            raise HTTPException(status_code=409, detail="同名自定义 OC 已存在，请直接选择")
        pool.append(preset)
        custom[gender] = pool
        save_char_swap_config({"custom_presets": custom})
    return {"ok": True, "preset": preset, "message": "Preset added"}

def _normalize_style_preset(payload: dict, *, fallback_id: str) -> dict:
    label = str(payload.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label 不能为空")
    style = payload.get("style")
    if style is None:
        style = payload.get("replace", "")
    return {
        "id": str(payload.get("id") or fallback_id).strip() or fallback_id,
        "label": label,
        "style": str(style or ""),
    }

@router.get("/style-presets")
def api_char_swap_style_presets_list() -> dict:
    cfg = load_char_swap_config()
    return {"ok": True, "presets": list(cfg.get("style_presets") or [])}

@router.post("/style-presets")
def api_char_swap_style_preset_add(payload: dict = Body(default_factory=dict)) -> dict:
    preset = _normalize_style_preset(
        payload,
        fallback_id=f"style_{int(__import__('time').time())}",
    )
    cfg = load_char_swap_config()
    presets = list(cfg.get("style_presets") or [])
    if any(str(p.get("id") or "") == preset["id"] for p in presets):
        raise HTTPException(status_code=400, detail="preset id already exists")
    presets.append(preset)
    save_char_swap_config({"style_presets": presets})
    return {"ok": True, "preset": preset, "presets": presets, "message": "Style preset added"}

@router.put("/style-presets")
def api_char_swap_style_preset_update(payload: dict = Body(default_factory=dict)) -> dict:
    preset_id = str(payload.get("id") or "").strip()
    if not preset_id:
        raise HTTPException(status_code=400, detail="id 不能为空")
    preset = _normalize_style_preset(payload, fallback_id=preset_id)
    preset["id"] = preset_id
    cfg = load_char_swap_config()
    presets = list(cfg.get("style_presets") or [])
    idx = next((i for i, p in enumerate(presets) if str(p.get("id") or "") == preset_id), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="style preset not found")
    presets[idx] = preset
    save_char_swap_config({"style_presets": presets})
    return {"ok": True, "preset": preset, "presets": presets, "message": "Style preset updated"}

@router.delete("/style-presets")
def api_char_swap_style_preset_delete(id: str = Query("")) -> dict:
    preset_id = str(id or "").strip()
    if not preset_id:
        raise HTTPException(status_code=400, detail="id 不能为空")
    cfg = load_char_swap_config()
    presets = list(cfg.get("style_presets") or [])
    next_presets = [p for p in presets if str(p.get("id") or "") != preset_id]
    if len(next_presets) == len(presets):
        raise HTTPException(status_code=404, detail="style preset not found")
    save_char_swap_config({"style_presets": next_presets})
    return {"ok": True, "presets": next_presets, "message": "Style preset deleted"}
