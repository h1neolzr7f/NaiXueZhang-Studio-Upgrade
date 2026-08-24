"""Control plane for direct Pixiv discovery and verified NAI intake."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

from crawler_control import multi_crawler_status
from pixiv_nai_crawler import (
    get_report,
    list_presets,
    list_quarantined,
    load_state,
    load_task,
    reset_search_progress,
    retry_quarantined,
    save_task,
)
from pixiv_nai_preflight import run_preflight


ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix="/api/crawler/pixiv", tags=["pixiv-nai-intake"])


@router.get("/task")
def api_pixiv_intake_task() -> dict:
    return {
        "ok": True,
        "task": load_task(root=ROOT),
        "presets": list_presets(),
        "state": {
            "updated_at": str(load_state(root=ROOT).get("updated_at") or ""),
        },
    }


@router.post("/task")
def api_pixiv_intake_task_save(
    payload: dict = Body(default_factory=dict),
) -> dict:
    reset_search = bool(payload.pop("reset_search", False))
    try:
        task = save_task(payload, root=ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = {
        "ok": True,
        "task": task,
        "reset_search": False,
        "message": "Pixiv NAI intake settings saved; start the Pixiv crawler to apply.",
    }
    if reset_search:
        reset_search_progress(root=ROOT)
        result["reset_search"] = True
        result["message"] = "Pixiv NAI intake settings saved; discovery cursor reset."
    return result


@router.get("/report")
def api_pixiv_intake_report() -> dict:
    return {
        "ok": True,
        "report": get_report(root=ROOT),
        "process": multi_crawler_status().get("pixiv") or {},
    }


@router.get("/quarantine")
def api_pixiv_intake_quarantine() -> dict:
    """List works currently quarantined by repeated retryable failures."""
    return {"ok": True, "items": list_quarantined(root=ROOT)}


@router.post("/quarantine/retry")
def api_pixiv_intake_quarantine_retry() -> dict:
    """Clear the quarantine; the next crawl cycle retries those works."""
    result = retry_quarantined(root=ROOT)
    return {
        "ok": True,
        "cleared": result["cleared"],
        "message": "隔离已清空，下一轮采集会重试这些作品。",
    }


@router.post("/preflight")
def api_pixiv_intake_preflight(
    payload: dict = Body(default_factory=dict),
    max_pages: int = Query(default=1, ge=1, le=10),
    max_works: int = Query(default=25, ge=1, le=200),
) -> dict:
    """Measure the unsaved task against Pixiv without mutating gallery state."""

    try:
        report = run_preflight(
            task=payload,
            root=ROOT,
            max_pages=max_pages,
            max_works=max_works,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": report["status"] in {"completed", "source_loop"},
        "report": report,
        "message": "Read-only Pixiv NAI preflight completed; gallery data was not changed.",
    }
