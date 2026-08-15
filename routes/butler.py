from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from butler import (
    butler_task_revision,
    cancel_butler_task,
    clear_butler_messages,
    confirm_butler_action,
    get_butler_task,
    list_butler_tasks,
    list_butler_messages,
    resume_butler_task,
    retry_butler_task,
    submit_butler_chat,
    wait_for_butler_task_change,
    workflow_runtime_status,
)
from butler_service import butler_status, public_error
from butler_templates import TEMPLATES
from software_help import answer_software_question
from server_shared import WEB_DIR


router = APIRouter()


def _task_list_summary(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    report = result.get("report") if isinstance(result, dict) else None
    prepared = result.get("prepared") if isinstance(result.get("prepared"), dict) else {}
    result_summary = {
        key: value
        for key, value in {
            "total_images": prepared.get("total_images", result.get("total_images")),
            "pixiv_url": prepared.get("pixiv_url", result.get("pixiv_url")),
            "gallery_url": prepared.get("gallery_url", result.get("gallery_url")),
        }.items()
        if value not in (None, "")
    }
    return {
        key: value
        for key, value in {
            "id": task.get("id"),
            "workflow_id": task.get("workflow_id") or task.get("id"),
            "kind": task.get("kind"),
            "title": task.get("title"),
            "status": task.get("status"),
            "phase": task.get("phase"),
            "message": task.get("message"),
            "progress": task.get("progress") or {},
            "error": task.get("error") or "",
            "cancel_requested": bool(task.get("cancel_requested")),
            "retry_of": task.get("retry_of") or "",
            "created_at": task.get("created_at") or "",
            "updated_at": task.get("updated_at") or "",
            "started_at": task.get("started_at") or "",
            "finished_at": task.get("finished_at") or "",
            "terminal": bool(task.get("terminal")),
            "capabilities": task.get("capabilities") or {},
            "has_report": isinstance(report, dict),
            "result_summary": result_summary,
        }.items()
        if value is not None
    }


def _compact_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    compact["tasks"] = [
        _task_list_summary(task)
        for task in list(payload.get("tasks") or [])
        if isinstance(task, dict)
    ]
    return compact


@router.get("/butler")
def butler_page() -> FileResponse:
    page = WEB_DIR / "butler.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="butler page missing")
    return FileResponse(
        page,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/api/butler/status")
def api_butler_status() -> dict:
    payload = butler_status()
    tasks = list_butler_tasks(limit=20).get("tasks") or []
    latest = tasks[0] if tasks else None
    if latest:
        legacy_status = {
            "awaiting_confirmation": "running",
            "succeeded": "ready" if latest.get("phase") == "ready_for_upload" else "done",
            "partially_succeeded": "ready" if latest.get("phase") == "ready_for_upload" else "done",
            "failed": "error",
            "cancelled": "cancelled",
            "paused": "running",
            "unknown": "error",
        }.get(str(latest.get("status") or ""), str(latest.get("status") or "idle"))
        latest_result = latest.get("result") or {}
        workflow_result = _task_list_summary(latest).get("result_summary") or None
        payload["workflow"] = {
            "id": latest.get("id") or "",
            "status": legacy_status,
            "phase": latest.get("phase") or "",
            "message": latest.get("message") or "",
            "started_at": latest.get("started_at") or "",
            "finished_at": latest.get("finished_at") or "",
            "progress": latest.get("progress") or {},
            "result": workflow_result,
            "has_report": bool(
                isinstance(latest_result, dict)
                and isinstance(latest_result.get("report"), dict)
            ),
        }
    payload["tasks"] = [_task_list_summary(task) for task in tasks]
    payload["runtime"] = workflow_runtime_status()
    return payload


@router.post("/api/butler/help")
def api_butler_help(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return answer_software_question(payload.get("question"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/butler/chat")
async def api_butler_chat(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        args = (
            str(payload.get("message") or ""),
            payload.get("history"),
            payload.get("image"),
            str(payload.get("intent") or ""),
        )
        comparison = payload.get("comparison")
        agent = str(payload.get("agent") or "").strip()
        kwargs: dict[str, Any] = {}
        if comparison is not None:
            kwargs["comparison"] = comparison
        if agent:
            kwargs["agent"] = agent
        if kwargs:
            return await submit_butler_chat(*args, **kwargs)
        return await submit_butler_chat(*args)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"管家规划失败：{public_error(exc)}") from exc


@router.get("/api/butler/history")
def api_butler_history(
    limit: int = Query(60, ge=1, le=100),
    before_id: int | None = Query(None, ge=1),
) -> dict:
    return list_butler_messages(limit=limit, before_id=before_id)


@router.delete("/api/butler/history")
def api_butler_history_clear() -> dict:
    return clear_butler_messages()


@router.get("/api/butler/templates")
def api_butler_templates() -> dict:
    templates = TEMPLATES.list_all()
    return {"ok": True, "total": len(templates), "templates": templates}


@router.post("/api/butler/templates")
def api_butler_template_save(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        template = TEMPLATES.save(
            label=str(payload.get("label") or ""),
            prompt=str(payload.get("prompt") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "template": template}


@router.delete("/api/butler/templates/{template_id}")
def api_butler_template_delete(template_id: str) -> dict:
    if not TEMPLATES.delete(template_id):
        raise HTTPException(status_code=404, detail="常用任务不存在或不可删除")
    return {"ok": True, "deleted": template_id}


@router.post("/api/butler/confirm")
async def api_butler_confirm(payload: dict = Body(default_factory=dict)) -> dict:
    confirmation_id = str(payload.get("confirmation_id") or "").strip()
    if not confirmation_id:
        raise HTTPException(status_code=400, detail="confirmation_id is required")
    try:
        return await confirm_butler_action(
            confirmation_id,
            approve=bool(payload.get("approve")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"管家执行失败：{public_error(exc)}") from exc


@router.get("/api/butler/tasks")
def api_butler_tasks(
    limit: int = Query(30, ge=1, le=100),
    status: str = Query("", max_length=40),
    selected_id: str = Query("", max_length=128),
) -> dict:
    payload = _compact_task_payload(list_butler_tasks(limit=limit, status=status))
    selected = str(selected_id or "").strip()
    if selected:
        try:
            payload["selected_task"] = get_butler_task(selected).get("task")
        except ValueError:
            payload["selected_task"] = None
    return payload


def _task_stream_payload(selected_id: str = "") -> dict:
    revision = butler_task_revision()
    payload = _compact_task_payload(list_butler_tasks(limit=20, status=""))
    selected = str(selected_id or "").strip()
    if selected:
        try:
            payload["selected_task"] = get_butler_task(selected).get("task")
        except ValueError:
            payload["selected_task"] = None
    payload["revision"] = revision
    return payload


def _task_stream_event(payload: dict) -> str:
    revision = max(0, int(payload.get("revision") or 0))
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"id: {revision}\nevent: tasks\ndata: {data}\n\n"


@router.get("/api/butler/tasks/stream")
async def api_butler_task_stream(
    request: Request,
    selected_id: str = Query("", max_length=128),
) -> StreamingResponse:
    async def events():
        payload = await asyncio.to_thread(_task_stream_payload, selected_id)
        last_revision = int(payload.get("revision") or 0)
        yield _task_stream_event(payload)
        while not await request.is_disconnected():
            revision = await asyncio.to_thread(
                wait_for_butler_task_change,
                last_revision,
                timeout=15.0,
            )
            if revision <= last_revision:
                yield ": keepalive\n\n"
                continue
            # A workflow update and its timeline event are usually committed back-to-back.
            # Briefly coalesce them into one payload instead of serializing SQLite twice.
            await asyncio.sleep(0.025)
            payload = await asyncio.to_thread(_task_stream_payload, selected_id)
            last_revision = int(payload.get("revision") or revision)
            yield _task_stream_event(payload)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/butler/tasks/{workflow_id}")
def api_butler_task(workflow_id: str) -> dict:
    try:
        return get_butler_task(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/butler/tasks/{workflow_id}/cancel")
async def api_butler_task_cancel(workflow_id: str) -> dict:
    try:
        return await cancel_butler_task(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/butler/tasks/{workflow_id}/retry")
async def api_butler_task_retry(workflow_id: str) -> dict:
    try:
        return await retry_butler_task(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/butler/tasks/{workflow_id}/resume")
async def api_butler_task_resume(workflow_id: str) -> dict:
    try:
        return await resume_butler_task(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _companion_signals() -> dict[str, Any]:
    token_ok = False
    queue_count = 0
    dirty = 0
    try:
        from nai_api import token_status

        token_ok = bool(token_status().get("has_token"))
    except Exception:
        token_ok = False
    try:
        from production_queue import list_ids

        queue_count = len(list_ids() or [])
    except Exception:
        queue_count = 0
    try:
        from gallery_index import index_status
        from server_shared import DB

        dirty = int(index_status(DB.conn, "site").get("text_dirty") or 0)
    except Exception:
        dirty = 0
    return {"token_ok": token_ok, "queue_count": queue_count, "dirty": dirty}


@router.get("/api/companion/state")
def api_companion_state() -> dict:
    from butler.companion_state import public_state

    return public_state()


@router.post("/api/companion/memory/propose")
def api_companion_memory_propose(payload: dict = Body(default_factory=dict)) -> dict:
    from butler.companion_state import propose_memory

    try:
        item = propose_memory(
            str(payload.get("text") or ""),
            agent=str(payload.get("agent") or ""),
            source=str(payload.get("source") or "user"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "memory": item}


@router.post("/api/companion/memory/confirm")
def api_companion_memory_confirm(payload: dict = Body(default_factory=dict)) -> dict:
    from butler.companion_state import confirm_memory

    try:
        item = confirm_memory(str(payload.get("id") or ""), confirm=bool(payload.get("confirm", True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "memory": item}


@router.post("/api/companion/memory/forget")
def api_companion_memory_forget(payload: dict = Body(default_factory=dict)) -> dict:
    from butler.companion_state import forget_memory

    try:
        item = forget_memory(str(payload.get("id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "memory": item}


@router.post("/api/companion/handoff")
def api_companion_handoff(payload: dict = Body(default_factory=dict)) -> dict:
    from butler.companion_state import record_handoff

    try:
        item = record_handoff(
            from_agent=str(payload.get("from_agent") or ""),
            to_agent=str(payload.get("to_agent") or ""),
            note=str(payload.get("note") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "handoff": item}


@router.post("/api/companion/quiet")
def api_companion_quiet(payload: dict = Body(default_factory=dict)) -> dict:
    from butler.companion_state import update_quiet

    return {"ok": True, "quiet": update_quiet(payload)}


@router.get("/api/companion/events")
def api_companion_events(agent: str = Query(""), deliver: bool = Query(False)) -> dict:
    from butler.companion_state import collect_local_events, delivery_allowed, mark_delivered

    signals = _companion_signals()
    events = collect_local_events(**signals)
    if agent:
        events = [item for item in events if not item.get("agent") or item.get("agent") == agent]
    allowed = delivery_allowed()
    chosen = events[0] if events and allowed.get("ok") else None
    if chosen and deliver:
        mark_delivered(str(chosen.get("id") or ""))
    return {
        "ok": True,
        "tts": {"enabled": False, "core": False},
        "delivery": allowed,
        "events": events,
        "event": chosen,
    }
