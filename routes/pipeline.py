from fastapi import APIRouter, Body, HTTPException, Query
from post_pipeline import (
    load_config,
    save_config,
    pipeline_status,
    count_items_needing_pipeline,
    process_image,
    start_pipeline,
    cancel_pipeline,
    manual_review_image,
    mosaic_runtime_status,
)
from pixiv_launch import resume_last_job_after_review

router = APIRouter(prefix="/api/pipeline")

@router.get("/config")
def api_pipeline_config_get() -> dict:
    cfg = load_config()
    mosaic_runtime = mosaic_runtime_status(cfg)
    return {
        "ok": True,
        "config": cfg,
        "anr_available": bool(
            __import__("post_pipeline", fromlist=["_resolve_anr_cwd"])._resolve_anr_cwd(cfg)
        ),
        "mosaic_runtime": mosaic_runtime,
    }

@router.post("/config")
def api_pipeline_config_set(payload: dict = Body(default_factory=dict)) -> dict:
    cfg = save_config(payload)
    return {"ok": True, "config": cfg, "message": "Pipeline config saved"}

@router.get("/status")
def api_pipeline_status() -> dict:
    return {
        "ok": True,
        "job": pipeline_status(),
        "backlog": count_items_needing_pipeline(),
    }

@router.get("/backlog")
def api_pipeline_backlog(refresh: bool = Query(False)) -> dict:
    return {
        "ok": True,
        **count_items_needing_pipeline(force=refresh),
    }

@router.post("/run")
def api_pipeline_run(payload: dict = Body(default_factory=dict)) -> dict:
    if payload.get("image_id") and not payload.get("image_ids") and not payload.get("group_id"):
        options = payload.get("options") if isinstance(payload.get("options"), dict) else None
        only_missing = bool(
            payload.get("only_missing")
            or (isinstance(options, dict) and options.get("only_missing"))
        )
        try:
            return process_image(
                str(payload["image_id"]),
                overrides=options,
                only_missing=only_missing,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return start_pipeline(payload)


@router.post("/cancel")
def api_pipeline_cancel() -> dict:
    return cancel_pipeline()

@router.post("/review/{image_id}")
def api_pipeline_review(image_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    try:
        review = manual_review_image(
            image_id,
            str(payload.get("action") or ""),
            note=str(payload.get("note") or ""),
        )
        review["resume"] = resume_last_job_after_review()
        return review
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
