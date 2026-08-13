from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from server_shared import CRAWLER_WATCHDOG
from progress import get_progress_snapshot
from api_schemas import CrawlerControlRequest
from crawler_control import (
    multi_crawler_status,
    restart_crawler,
    start_crawler_target,
    stop_crawler_target,
)
from db import Database
from paths import data_dir
from crawler_task import (
    get_task,
)
from pixiv_nai_crawler import (
    get_report as get_pixiv_report,
    load_task as load_pixiv_task,
    save_task as save_pixiv_task,
)

router = APIRouter(prefix="/api")
ROOT = Path(__file__).resolve().parents[1]


def _pixiv_task_payload(payload: dict) -> dict:
    """Accept the Pixiv schema and translate the legacy search form safely."""
    incoming = dict(payload or {})
    current = load_pixiv_task(root=ROOT)
    if "scopes" not in incoming:
        legacy_query = str(incoming.get("search_query") or "").strip()
        if legacy_query:
            terms = [
                term
                for term in legacy_query.split()
                if term.casefold() not in {"nai", "-nai_x"}
            ]
            incoming["scopes"] = [
                {
                    "id": "compat-search",
                    "type": "search",
                    "query": " ".join(terms).strip() or "NovelAI",
                    "sort": "date_desc",
                    "search_target": "partial_match_for_tags",
                    "enabled": True,
                }
            ]
    if "search_max_pages" in incoming:
        incoming["max_pages_per_run"] = max(
            1, int(incoming.get("search_max_pages") or current["max_pages_per_run"])
        )
    allowed = set(current) | {"scopes"}
    return {**current, **{key: value for key, value in incoming.items() if key in allowed}}


def requeue_exhausted_previews(*, limit: int = 1000) -> dict:
    task = get_task()
    from server_shared import CONFIG

    max_attempts = max(1, int(CONFIG.get("preview_max_attempts", 6) or 6))
    with Database(data_dir() / "aitag.db") as db:
        work_ids = db.requeue_exhausted_previews(
            max_attempts=max_attempts,
            limit=limit,
        )
    return {
        "ok": True,
        "requeued": len(work_ids),
        "work_ids": work_ids,
        "task": task,
        "message": f"已重新排队 {len(work_ids)} 个耗尽的封面任务",
    }


@router.get("/crawler/status")
def api_crawler_status() -> dict:
    return {"ok": True, "status": multi_crawler_status()}


@router.post("/crawler/start")
def api_crawler_start(payload: CrawlerControlRequest) -> dict:
    target = str(payload.target or "pixiv").strip().lower()
    try:
        result = start_crawler_target(
            target,
            phase=str(payload.phase or "").strip() or None,
            watch=bool(payload.watch),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "target": target,
        "result": result,
        "status": multi_crawler_status(),
        "message": "已从现有断点启动采集，不会清空数据库",
    }


@router.post("/crawler/stop")
def api_crawler_stop(payload: CrawlerControlRequest) -> dict:
    target = str(payload.target or "pixiv").strip().lower()
    try:
        result = stop_crawler_target(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if target in {"site", "all", "website", "aitag"}:
        CRAWLER_WATCHDOG.set_enabled(False, reason="manual_stop")
    return {
        "ok": True,
        "target": target,
        "result": result,
        "status": multi_crawler_status(),
        "message": "已停止所选采集进程；数据库和断点均已保留",
    }


@router.post("/crawler/autopilot")
def api_crawler_autopilot(payload: CrawlerControlRequest) -> dict:
    target = str(payload.target or "pixiv").strip().lower()
    if target not in {"pixiv", "all"}:
        raise HTTPException(
            status_code=400,
            detail="甩手采集仅支持 Pixiv direct NAI intake",
        )
    task = _pixiv_task_payload(dict(payload.task or {}))
    task["enabled"] = True
    saved = save_pixiv_task(task, root=ROOT)
    try:
        started = start_crawler_target("pixiv", watch=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "task": saved,
        "start": started,
        "report": get_pixiv_report(root=ROOT),
        "status": multi_crawler_status(),
    }


@router.get("/crawler/report")
def api_crawler_report() -> dict:
    return {
        "ok": True,
        "report": get_pixiv_report(root=ROOT),
        "status": multi_crawler_status(),
    }


@router.post("/crawler/retry-exhausted")
def api_crawler_retry_exhausted(payload: dict = Body(default_factory=dict)) -> dict:
    limit = max(1, min(int(payload.get("limit") or 1000), 5000))
    result = requeue_exhausted_previews(limit=limit)
    if bool(payload.get("restart")) and result.get("requeued"):
        result["restart"] = restart_crawler()
    result["status"] = multi_crawler_status()
    return result


@router.get("/progress")
def api_progress() -> dict:
    return get_progress_snapshot()

@router.post("/crawler/restart")
def api_crawler_restart() -> dict:
    try:
        return restart_crawler()
    except Exception as exc:
        return {
            "ok": False,
            "crawler_running": False,
            "message": f"重启失败: {exc}",
        }

@router.get("/crawler/watchdog")
def api_crawler_watchdog() -> dict:
    return CRAWLER_WATCHDOG.status()

@router.get("/crawler/task")
def api_crawler_task_get() -> dict:
    return {"task": load_pixiv_task(root=ROOT), "presets": []}

@router.post("/crawler/task")
def api_crawler_task_set(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        task = save_pixiv_task(_pixiv_task_payload(payload), root=ROOT)
        return {"ok": True, "task": task, "message": "Pixiv NAI task saved"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "message": f"保存任务失败: {exc}"}

@router.post("/crawler/task/apply")
def api_crawler_task_apply(payload: dict = Body(default_factory=dict)) -> dict:
    restart = bool(payload.pop("restart", False))
    payload.pop("reset_search", None)
    try:
        task = save_pixiv_task(_pixiv_task_payload(payload), root=ROOT)
        result = {"ok": True, "task": task}
        if restart:
            result["start"] = start_crawler_target("pixiv", watch=True)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "message": f"应用任务失败: {exc}"}

@router.post("/crawler/arknights/update")
def api_crawler_arknights_update(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        task = load_pixiv_task(root=ROOT)
        task["enabled"] = True
        task["scopes"] = [
            {
                "id": "arknights",
                "type": "search",
                "query": "アークナイツ",
                "sort": "date_desc",
                "search_target": "partial_match_for_tags",
                "enabled": True,
            }
        ]
        saved = save_pixiv_task(task, root=ROOT)
        result = {"ok": True, "task": saved}
        if bool(payload.get("restart", True)):
            result["start"] = start_crawler_target("pixiv", watch=True)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        return {"ok": False, "message": f"Arknights incremental update failed: {exc}"}

@router.post("/crawler/watchdog")
def api_crawler_watchdog_set(
    payload: dict = Body(default_factory=dict),
) -> dict:
    enabled = payload.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="enabled is required")
    reason = "manual" if not bool(enabled) else "manual_on"
    try:
        return CRAWLER_WATCHDOG.set_enabled(bool(enabled), reason=reason)
    except Exception as exc:
        return {
            "enabled": CRAWLER_WATCHDOG.enabled,
            "ok": False,
            "message": f"切换守护失败: {exc}",
        }
