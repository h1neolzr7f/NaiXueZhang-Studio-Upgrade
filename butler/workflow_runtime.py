"""LangGraph runtime owning checkpointer lifetime and Butler task projections."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import time
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from usage_ledger import usage_scope

from .redaction import redact_history, redact_text
from .store import ButlerTaskStore, TERMINAL_STATUSES
from .workflow_executors import ButlerWorkflowExecutors
from .workflow_helpers import (
    AutoExecutor,
    ButlerState,
    ConfirmedExecutor,
    Planner,
    UnknownExternalOutcome,
    WorkflowCancelled,
    _elapsed_seconds,
    _now,
    _operation_identity,
    _planned_progress,
    _secure_local_configuration_plan,
)


class _LegacyProxy:
    def __getattr__(self, name: str) -> Any:
        import butler.workflow as wf

        return getattr(wf.legacy, name)


legacy = _LegacyProxy()


def get_knowledge_catalog(*args: Any, **kwargs: Any) -> Any:
    import butler.workflow as wf

    return wf.get_knowledge_catalog(*args, **kwargs)


def usage_summary(*args: Any, **kwargs: Any) -> Any:
    import butler.workflow as wf

    return wf.usage_summary(*args, **kwargs)


def _local_read_only_plan(*args: Any, **kwargs: Any) -> Any:
    import butler.workflow as wf

    return wf._local_read_only_plan(*args, **kwargs)


class ButlerWorkflowRuntime(ButlerWorkflowExecutors):
    """Owns LangGraph/checkpointer lifetime and durable Butler task projections."""

    def __init__(
        self,
        state_path: Path,
        *,
        planner: Planner | None = None,
        auto_executor: AutoExecutor | None = None,
        confirmed_executor: ConfirmedExecutor | None = None,
        ai_status_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        import butler.workflow as wf

        planner = planner or wf.legacy.request_plan
        auto_executor = auto_executor or wf.legacy._execute_auto
        confirmed_executor = confirmed_executor or wf.legacy._execute_confirmed
        ai_status_fn = ai_status_fn or wf.legacy.ai_status
        self.state_path = Path(state_path)
        self.checkpoint_path = self.state_path.with_name(
            f"{self.state_path.stem}_checkpoints{self.state_path.suffix or '.db'}"
        )
        self.store = ButlerTaskStore(self.state_path)
        self._planner = planner
        self._auto_executor = auto_executor
        self._confirmed_executor = confirmed_executor
        self._ai_status = ai_status_fn
        self._saver_manager: AbstractAsyncContextManager[AsyncSqliteSaver] | None = None
        self._saver: AsyncSqliteSaver | None = None
        self._graph: Any = None
        self._start_lock = asyncio.Lock()
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._background: set[asyncio.Task[Any]] = set()
        self._started = False
        self._recovery: dict[str, int] = {"paused": 0, "unknown": 0}

    @staticmethod
    def _report_from_state(
        state: ButlerState,
        task: dict[str, Any],
        *,
        status: str,
        message: str,
        finished_at: str,
    ) -> dict[str, Any]:
        actions = list(state.get("actions") or [])
        results = [item for item in (state.get("tool_results") or []) if isinstance(item, dict)]
        skipped = list(state.get("skipped_actions") or [])
        rejected = list(state.get("rejected_actions") or [])
        skipped_indexes = {
            int(item.get("action_index"))
            for item in skipped
            if isinstance(item, dict) and item.get("action_index") is not None
        }
        completed = min(len(actions), len(results) + len(skipped))
        progress = _planned_progress(
            actions,
            completed,
            stage="completed" if status not in {"cancelled", "failed", "unknown"} else status,
            skipped_indexes=skipped_indexes,
            cancelled=status == "cancelled",
        )
        steps = progress["steps"]
        if status in {"failed", "unknown"}:
            for step in steps:
                if step["status"] == "running":
                    step["status"] = "failed"
                    break
        item_succeeded = sum(
            int(item.get("succeeded") or item.get("ok_count") or 0) for item in results
        )
        item_failed = sum(
            int(item.get("failed") or item.get("fail_count") or 0) for item in results
        )
        highlights = []
        for item in results:
            text = redact_text(item.get("message") or item.get("summary") or "", limit=240)
            if text and text not in highlights:
                highlights.append(text)
        error = redact_text(task.get("error") or "", limit=500)
        errors = ([error] if error else []) + [
            redact_text(item.get("reason") or "未通过计划校验", limit=300)
            for item in rejected
            if isinstance(item, dict)
        ]
        title = {
            "succeeded": "交付报告 · 已完成",
            "partially_succeeded": "交付报告 · 部分完成",
            "cancelled": "任务报告 · 已取消",
            "failed": "任务报告 · 需要处理",
            "unknown": "任务报告 · 等待核对",
        }.get(status, "任务交付报告")
        if status == "succeeded":
            summary = f"已完成 {len(results)} 个执行步骤，结果和操作记录都已保存。"
        elif status == "partially_succeeded":
            summary = "任务已经尽可能完成，失败项和可重试线索已整理在下面。"
        elif status == "cancelled":
            summary = "任务已按你的要求停止，已完成部分仍保留在记录中。"
        else:
            summary = "这次执行遇到了阻碍，原因和已完成步骤已经保留，可以据此继续处理。"
        links: list[dict[str, str]] = []
        for item in results:
            for key, label in (("gallery_url", "查看图库结果"), ("pixiv_url", "检查投稿草稿")):
                url = str(item.get(key) or "")
                if url and not any(link["url"] == url for link in links):
                    links.append({"label": label, "url": url})
        return {
            "title": title,
            "status": status,
            "summary": summary,
            "message": message,
            "generated_at": finished_at,
            "duration_seconds": _elapsed_seconds(task.get("started_at"), finished_at),
            "counts": {
                "planned": len(actions),
                "completed": len(results),
                "skipped": len(skipped),
                "rejected": len(rejected),
                "item_succeeded": item_succeeded,
                "item_failed": item_failed,
            },
            "steps": steps,
            "highlights": highlights[:8],
            "errors": [item for item in errors if item][:8],
            "links": links[:6],
            "usage": usage_summary(
                workflow_id=str(state.get("workflow_id") or task.get("id") or "")
            ),
        }

    @staticmethod
    def _completion_chat(task: dict[str, Any]) -> str:
        report = ((task.get("result") or {}).get("report") or {})
        counts = report.get("counts") or {}
        status = str(task.get("status") or "")
        if status == "succeeded":
            lead = "完成啦 ✨ 你交给我的任务已经处理好，过程和结果都替你收好了。"
        elif status == "partially_succeeded":
            lead = "我把能完成的部分都认真做完啦。还有少量项目没通过，我已经把原因和重试线索整理好了。"
        elif status == "cancelled":
            lead = "已经按你的要求停下来啦。放心，之前完成的内容和过程记录都还在。"
        else:
            lead = "这次执行中途遇到了一点阻碍，但不用从头猜原因，我已经把现场和下一步线索保留下来了。"
        return (
            f"{lead}\n\n执行报告：{report.get('summary') or task.get('message') or '任务已结束'}"
            f" 共 {counts.get('planned', 0)} 步，完成 {counts.get('completed', 0)}，"
            f"跳过 {counts.get('skipped', 0)}，异常 {counts.get('item_failed', 0) + counts.get('rejected', 0)}。"
            "详细交付报告已放进任务中心，点开这条任务就能逐步查看。"
        )

    def _ensure_task_report(self, workflow_id: str, task: dict[str, Any]) -> dict[str, Any]:
        existing_result = dict(task.get("result") or {})
        if isinstance(existing_result.get("report"), dict):
            return task
        progress = dict(task.get("progress") or {})
        status = str(task.get("status") or "failed")
        steps = list(progress.get("steps") or [])
        if status in {"failed", "unknown"}:
            for step in steps:
                if step.get("status") in {"running", "waiting"}:
                    step["status"] = "failed"
                    break
        error = redact_text(task.get("error") or "", limit=500)
        planned = int(progress.get("workflow_total") or progress.get("total") or len(steps))
        completed = int(progress.get("workflow_completed") or progress.get("current") or 0)
        report = {
            "title": "任务报告 · 等待核对" if status == "unknown" else "任务报告 · 需要处理",
            "status": status,
            "summary": "这次执行遇到了阻碍，现场、错误原因和已完成步骤已经保留。",
            "message": task.get("message") or "任务未完成",
            "generated_at": task.get("finished_at") or _now(),
            "duration_seconds": _elapsed_seconds(task.get("started_at"), task.get("finished_at")),
            "counts": {
                "planned": planned,
                "completed": completed,
                "skipped": 0,
                "rejected": 0,
                "item_succeeded": int(progress.get("succeeded") or 0),
                "item_failed": max(1, int(progress.get("failed") or 0)),
            },
            "steps": steps,
            "highlights": [],
            "errors": [error] if error else [str(task.get("message") or "请打开时间线查看失败位置")],
            "links": [],
            "usage": usage_summary(workflow_id=workflow_id),
        }
        existing_result["report"] = report
        progress.update(
            {
                "steps": steps,
                "stage": "report_ready",
                "current_label": "异常报告已生成",
                "next_label": "检查原因后重试",
                "eta_seconds": 0,
                "eta_text": "已停止",
                "eta_basis": "completed",
            }
        )
        updated = self.store.update_task(workflow_id, result=existing_result, progress=progress)
        return updated or task

    async def start(self) -> None:
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self.store.start()
            self._recovery = self.store.recover_interrupted()
            self.store.prune(retention_days=int(os.environ.get("BUTLER_RETENTION_DAYS", "30")))
            manager = AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path))
            saver = await manager.__aenter__()
            try:
                await saver.setup()
                self._saver_manager = manager
                self._saver = saver
                self._graph = self._build_graph().compile(checkpointer=saver)
                self._started = True
            except Exception:
                await manager.__aexit__(None, None, None)
                self.store.close()
                raise

    async def close(self) -> None:
        if not self._started:
            self.store.close()
            return
        tasks = list(self._background)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        manager = self._saver_manager
        self._saver_manager = None
        self._saver = None
        self._graph = None
        self._started = False
        if manager is not None:
            await manager.__aexit__(None, None, None)
        self.store.close()

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ButlerState)
        builder.add_node("plan", self._plan_node)
        builder.add_node("execute_auto", self._execute_auto_node)
        builder.add_node("approval", self._approval_node)
        builder.add_node("execute_confirmed", self._execute_confirmed_node)
        builder.add_node("skip_action", self._skip_action_node)
        builder.add_node("advance", self._advance_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_current,
            {
                "auto": "execute_auto",
                "approval": "approval",
                "finalize": "finalize",
            },
        )
        builder.add_edge("execute_auto", "advance")
        builder.add_conditional_edges(
            "approval",
            self._route_approval,
            {
                "execute": "execute_confirmed",
                "skip": "skip_action",
                "finalize": "finalize",
            },
        )
        builder.add_edge("execute_confirmed", "advance")
        builder.add_edge("skip_action", "advance")
        builder.add_conditional_edges(
            "advance",
            self._route_current,
            {
                "auto": "execute_auto",
                "approval": "approval",
                "finalize": "finalize",
            },
        )
        builder.add_edge("finalize", END)
        return builder

    async def _plan_node(self, state: ButlerState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        task = self.store.get_task(workflow_id, include_events=False) or {}
        if task.get("cancel_requested"):
            return {"cancelled": True, "actions": [], "action_index": 0}
        plan = state.get("preplanned")
        ai = {"model": "local"}
        if not isinstance(plan, dict):
            ai = self._ai_status()
            if not ai.get("has_api_key") or not ai.get("model"):
                raise RuntimeError("请先在设置或发布台配置 AI API Key 和模型")
        self.store.update_task(
            workflow_id,
            status="running",
            phase="planning",
            message="正在制定可执行计划…",
            started_at=task.get("started_at") or _now(),
        )
        if not isinstance(plan, dict):
            plan = await asyncio.to_thread(self._planner, state["message"], state.get("history"))
        reply = legacy._clean_text(plan.get("reply"), limit=2000) or "我已经分析了这条指令。"
        raw_actions = plan.get("actions") or []
        if not isinstance(raw_actions, list):
            raise ValueError("AI 计划中的 actions 不是数组")
        actions: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        from butler.agents import reject_foreign_tool

        for raw in raw_actions[: legacy.MAX_ACTIONS]:
            try:
                action = legacy.normalize_action(raw)
                foreign = reject_foreign_tool(action["tool"])
                if foreign:
                    rejected.append({"tool": action["tool"], "reason": foreign})
                    continue
                actions.append(action)
            except Exception as exc:
                rejected.append(
                    {
                        "tool": legacy._clean_text(
                            raw.get("tool") if isinstance(raw, dict) else "", limit=80
                        ),
                        "reason": legacy._clean_text(exc, limit=300),
                    }
                )
        self.store.update_task(
            workflow_id,
            phase="executing" if actions else "finishing",
            message=f"计划包含 {len(actions)} 个白名单操作",
            progress={
                "current": 0,
                "total": len(actions),
                "succeeded": 0,
                "failed": 0,
                **_planned_progress(
                    actions,
                    0,
                    stage="executing" if actions else "finishing",
                ),
            },
        )
        self.store.add_event(
            workflow_id,
            "planned",
            status="running",
            phase="planning",
            message=f"已生成 {len(actions)} 个白名单操作",
            detail={"tools": [item["tool"] for item in actions], "rejected": len(rejected)},
            event_key="workflow:planned",
        )
        return {
            "model": str(ai.get("model") or ""),
            "reply": reply,
            "actions": actions,
            "action_index": 0,
            "tool_results": [],
            "rejected_actions": rejected,
            "skipped_actions": [],
            "status": "running",
            "phase": "executing",
        }

    def _route_current(self, state: ButlerState) -> str:
        if state.get("cancelled"):
            return "finalize"
        actions = state.get("actions") or []
        index = int(state.get("action_index") or 0)
        if index >= len(actions):
            return "finalize"
        return "auto" if actions[index]["tool"] in legacy._AUTO_TOOLS else (
            "auto"
            if actions[index]["tool"] in legacy._REPAIR_TOOLS and legacy._auto_repair_enabled()
            else "approval"
        )

    def _route_approval(self, state: ButlerState) -> str:
        approval = state.get("approval")
        if isinstance(approval, dict):
            if approval.get("cancel_workflow"):
                return "finalize"
            return "execute" if approval.get("approve") else "skip"
        return "execute" if bool(approval) else "skip"

    async def _execute_auto_node(self, state: ButlerState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        index = int(state.get("action_index") or 0)
        action = (state.get("actions") or [])[index]
        if (self.store.get_task(workflow_id, include_events=False) or {}).get("cancel_requested"):
            return {"cancelled": True}
        self.store.update_task(
            workflow_id,
            status="running",
            phase=f"tool:{action['tool']}",
            message=f"正在执行：{action['label']}",
            progress={
                **((self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}),
                **_planned_progress(
                    list(state.get("actions") or []),
                    index,
                    stage=f"tool:{action['tool']}",
                    skipped_indexes={
                        int(item.get("action_index"))
                        for item in (state.get("skipped_actions") or [])
                        if isinstance(item, dict) and item.get("action_index") is not None
                    },
                ),
            },
        )
        if action["tool"] == "rebuild_knowledge_catalog":
            try:
                result = await self._execute_knowledge_refresh(workflow_id, index, action)
            except WorkflowCancelled:
                return {"cancelled": True}
        else:
            result = await asyncio.to_thread(self._auto_executor, action)
        results = list(state.get("tool_results") or [])
        results.append(result)
        self.store.add_event(
            workflow_id,
            "tool_completed",
            status="running",
            phase=f"tool:{action['tool']}",
            message=f"已完成：{action['label']}",
            detail={"tool": action["tool"], "risk": action["risk"]},
            event_key=f"action:{index}:completed",
        )
        return {"tool_results": results}

    def _approval_node(self, state: ButlerState) -> dict[str, Any]:
        index = int(state.get("action_index") or 0)
        action = (state.get("actions") or [])[index]
        operation_id, _arguments_hash = _operation_identity(state["workflow_id"], index, action)
        preview = legacy._preview_remix_action(action)
        work_order = legacy._production_work_order(action)
        decision = interrupt(
            {
                "workflow_id": state["workflow_id"],
                "action_index": index,
                "operation_id": operation_id,
                "tool": action["tool"],
                "label": action["label"],
                "risk": action["risk"],
                "summary": legacy._confirmation_summary(action),
                "arguments_summary": legacy._audit_summary(action["tool"], action["arguments"]),
                "preview": preview,
                "lane": (
                    "production"
                    if action["tool"] in legacy._PRODUCTION_TOOLS
                    else "repair"
                    if action["tool"] in legacy._REPAIR_TOOLS
                    else "confirm"
                ),
                **({"work_order": work_order} if work_order else {}),
            }
        )
        if isinstance(decision, dict) and decision.get("cancel_workflow"):
            return {"approval": decision, "cancelled": True}
        return {"approval": decision}

    async def _execute_confirmed_node(self, state: ButlerState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        index = int(state.get("action_index") or 0)
        action = (state.get("actions") or [])[index]
        operation_id, arguments_hash = _operation_identity(workflow_id, index, action)
        receipt = self.store.get_receipt(operation_id)
        if receipt and receipt.get("status") == "succeeded":
            result = receipt.get("result") or {}
        elif receipt and receipt.get("status") in {"started", "unknown"}:
            raise UnknownExternalOutcome(
                f"操作 {operation_id} 的外部结果未知，已停止自动重放"
            )
        else:
            self.store.update_task(
                workflow_id,
                status="running",
                phase=f"tool:{action['tool']}",
                message=f"正在执行已确认操作：{action['label']}",
                confirmation_id="",
                pending=None,
                progress={
                    **((self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}),
                    **_planned_progress(
                        list(state.get("actions") or []),
                        index,
                        stage=f"tool:{action['tool']}",
                        skipped_indexes={
                            int(item.get("action_index"))
                            for item in (state.get("skipped_actions") or [])
                            if isinstance(item, dict) and item.get("action_index") is not None
                        },
                    ),
                },
            )
            self.store.put_receipt(
                operation_id,
                task_id=workflow_id,
                action_index=index,
                tool=action["tool"],
                arguments_hash=arguments_hash,
                status="started",
            )
            legacy._write_audit(action["tool"], "accepted", action["arguments"])
            try:
                result = await self._execute_action(workflow_id, action, operation_id)
            except WorkflowCancelled:
                self.store.put_receipt(
                    operation_id,
                    task_id=workflow_id,
                    action_index=index,
                    tool=action["tool"],
                    arguments_hash=arguments_hash,
                    status="failed",
                    error="cancelled",
                )
                legacy._write_audit(action["tool"], "cancelled", action["arguments"])
                return {"cancelled": True}
            except Exception as exc:
                uncertain = action["tool"] in {
                    "generate_image",
                    "batch_generate",
                    "batch_generate_and_prepare_pixiv",
                    "prepare_pixiv_submission",
                    "delete_generated_item",
                    "delete_generated_group",
                    "run_pipeline",
                    "review_generated",
                    "start_crawler",
                    "stop_crawler",
                    "configure_crawler",
                    "retry_exhausted_previews",
                    "cancel_generation",
                }
                self.store.put_receipt(
                    operation_id,
                    task_id=workflow_id,
                    action_index=index,
                    tool=action["tool"],
                    arguments_hash=arguments_hash,
                    status="unknown" if uncertain else "failed",
                    error=legacy.public_error(exc),
                )
                legacy._write_audit(
                    action["tool"], "unknown" if uncertain else "failed", action["arguments"], detail=str(exc)
                )
                if uncertain:
                    raise UnknownExternalOutcome(
                        f"{action['label']} 的外部结果无法确认：{legacy.public_error(exc)}"
                    ) from exc
                raise
            self.store.put_receipt(
                operation_id,
                task_id=workflow_id,
                action_index=index,
                tool=action["tool"],
                arguments_hash=arguments_hash,
                status="succeeded",
                result=result,
            )
            legacy._write_audit(action["tool"], "executed", action["arguments"])
        results = list(state.get("tool_results") or [])
        results.append(result)
        self.store.add_event(
            workflow_id,
            "tool_completed",
            status="running",
            phase=f"tool:{action['tool']}",
            message=f"已完成：{action['label']}",
            detail={"tool": action["tool"], "operation_id": operation_id},
            event_key=f"action:{index}:completed",
        )
        return {"tool_results": results, "approval": None}

    async def _execute_action(
        self, workflow_id: str, action: dict[str, Any], operation_id: str
    ) -> dict[str, Any]:
        tool = action["tool"]
        args = action["arguments"]
        if tool in {"batch_generate", "batch_generate_and_prepare_pixiv"}:
            return await self._execute_batch(
                workflow_id,
                args,
                operation_id,
                prepare_pixiv=tool == "batch_generate_and_prepare_pixiv",
            )
        if tool == "batch_director":
            return await self._execute_director(workflow_id, args, operation_id)
        if tool == "prepare_pixiv_submission":
            from pixiv_launch import prepare_submission_package

            payload = {**args, "package_id": workflow_id}
            self.store.update_task(
                workflow_id,
                phase="preparing_pixiv",
                message="正在补齐后处理并生成投稿草稿…",
            )
            prepared = await asyncio.to_thread(prepare_submission_package, payload)
            return {
                "ok": True,
                "tool": tool,
                "message": "投稿草稿已准备完成，等待人工发布",
                "prepared": prepared.get("prepared") or prepared,
            }
        if tool == "run_pipeline":
            return await self._execute_pipeline(workflow_id, action, operation_id)
        return await self._confirmed_executor(action)


    def _skip_action_node(self, state: ButlerState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        index = int(state.get("action_index") or 0)
        action = (state.get("actions") or [])[index]
        skipped = list(state.get("skipped_actions") or [])
        skipped.append(
            {"tool": action["tool"], "action_index": index, "reason": "user_rejected"}
        )
        legacy._write_audit(action["tool"], "cancelled", action["arguments"])
        self.store.add_event(
            workflow_id,
            "tool_skipped",
            status="running",
            phase=f"tool:{action['tool']}",
            message=f"已跳过：{action['label']}",
            detail={"tool": action["tool"]},
            event_key=f"action:{index}:skipped",
        )
        return {"skipped_actions": skipped, "approval": None}

    def _advance_node(self, state: ButlerState) -> dict[str, Any]:
        next_index = int(state.get("action_index") or 0) + 1
        actions = list(state.get("actions") or [])
        total = len(actions)
        skipped_indexes = {
            int(item.get("action_index"))
            for item in (state.get("skipped_actions") or [])
            if isinstance(item, dict) and item.get("action_index") is not None
        }
        current_progress = dict(
            (self.store.get_task(state["workflow_id"], include_events=False) or {}).get("progress")
            or {}
        )
        self.store.update_task(
            state["workflow_id"],
            phase="executing",
            message=f"已处理 {next_index}/{total} 个操作",
            progress={
                **current_progress,
                "current": next_index,
                "total": total,
                "succeeded": len(state.get("tool_results") or []),
                "failed": len(state.get("rejected_actions") or []),
                **_planned_progress(
                    actions,
                    next_index,
                    stage="finishing" if next_index >= total else "executing",
                    skipped_indexes=skipped_indexes,
                ),
            },
        )
        return {"action_index": next_index}

    def _finalize_node(self, state: ButlerState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        cancelled = bool(state.get("cancelled")) or bool(
            (self.store.get_task(workflow_id, include_events=False) or {}).get("cancel_requested")
        )
        results = list(state.get("tool_results") or [])
        prepared = next(
            (
                item.get("prepared")
                for item in reversed(results)
                if isinstance(item, dict) and isinstance(item.get("prepared"), dict)
            ),
            None,
        )
        rejected = list(state.get("rejected_actions") or [])
        partial = any(
            isinstance(item, dict) and int(item.get("failed") or 0) > 0
            for item in results
        )
        rejected_only = bool(rejected) and not results
        status = (
            "cancelled"
            if cancelled
            else "failed"
            if rejected_only
            else "partially_succeeded"
            if partial or rejected
            else "succeeded"
        )
        phase = (
            "cancelled"
            if cancelled
            else "failed"
            if status == "failed"
            else "ready_for_upload"
            if prepared
            else "completed"
        )
        message = (
            "工作流已取消"
            if cancelled
            else (
                "计划校验未通过；没有执行任何操作"
                if status == "failed"
                else "任务部分成功；可检查失败项并重试"
                if status == "partially_succeeded"
                else "全部投稿草稿已就绪，等待人工发布"
                if prepared
                else "管家工作流已完成"
            )
        )
        finished_at = _now()
        task = self.store.get_task(workflow_id, include_events=False) or {}
        report = self._report_from_state(
            state,
            task,
            status=status,
            message=message,
            finished_at=finished_at,
        )
        result = {
            "reply": state.get("reply") or "",
            "tool_results": results,
            "rejected_actions": list(state.get("rejected_actions") or []),
            "skipped_actions": list(state.get("skipped_actions") or []),
            "prepared": prepared,
            "report": report,
        }
        report_progress = dict(task.get("progress") or {})
        completed_actions = len(results) + len(state.get("skipped_actions") or [])
        terminal_current = completed_actions if cancelled else len(state.get("actions") or [])
        report_progress.update(
            {
                "current": terminal_current,
                "total": len(state.get("actions") or []),
                "succeeded": len(results),
                "failed": len(state.get("rejected_actions") or []),
                "workflow_current": terminal_current,
                "workflow_completed": completed_actions,
                "workflow_total": len(state.get("actions") or []),
                "steps": report["steps"],
                "stage": "report_ready",
                "current_label": "交付报告已生成",
                "next_label": "无，任务已结束",
                "eta_seconds": 0,
                "eta_text": "已完成",
                "eta_basis": "completed",
                "estimate_updated_at": finished_at,
            }
        )
        self.store.update_task(
            workflow_id,
            status=status,
            phase=phase,
            message=message,
            result=result,
            progress=report_progress,
            pending=None,
            confirmation_id="",
            finished_at=finished_at,
        )
        self.store.add_event(
            workflow_id,
            "finished",
            status=status,
            phase=phase,
            message=message,
            event_key="workflow:finished",
        )
        return {"status": status, "phase": phase, "result": result}

    async def submit(
        self,
        message: str,
        history: Any = None,
        *,
        image: Any = None,
        preplanned: dict[str, Any] | None = None,
        retry_of: str = "",
        run_in_background: bool = False,
    ) -> dict[str, Any]:
        await self.start()
        secure_plan = None
        if preplanned is None and image in (None, "", {}):
            secure_plan = await asyncio.to_thread(_secure_local_configuration_plan, message)
        clean_message = redact_text(message, limit=legacy.MAX_MESSAGE_CHARS)
        if not clean_message:
            raise ValueError("请输入要交给管家的任务")
        clean_history = redact_history(history, maximum=legacy.MAX_HISTORY_ITEMS)
        safe_plan = copy.deepcopy(preplanned) if isinstance(preplanned, dict) else secure_plan
        workflow_id = secrets.token_hex(12)
        image_name = ""
        if image not in (None, "", {}):
            if not isinstance(image, dict):
                raise ValueError("图片附件格式不正确")
            if safe_plan is None:
                with usage_scope(workflow_id):
                    safe_plan = await asyncio.to_thread(
                        self._planner,
                        clean_message,
                        clean_history,
                        image,
                    )
            raw_name = str(image.get("name") or "图片").replace("\\", "/").rsplit("/", 1)[-1]
            image_name = redact_text(raw_name, limit=120) or "图片"
        stored_message = (
            f"🖼 已附图片：{image_name}\n{clean_message}" if image_name else clean_message
        )
        self.store.add_message("user", stored_message, workflow_id=workflow_id)
        input_data: dict[str, Any] = {"message": clean_message, "history": clean_history}
        if safe_plan is not None:
            input_data["preplanned"] = safe_plan
        if image_name:
            input_data["attachment"] = {"kind": "image", "name": image_name}
        self.store.create_task(
            workflow_id,
            thread_id=workflow_id,
            kind="butler_workflow",
            title=clean_message[:80],
            input_data=input_data,
            retry_of=retry_of,
        )
        self.store.update_task(
            workflow_id,
            progress={
                "current": 0,
                "total": 1,
                "succeeded": 0,
                "failed": 0,
                "stage": "planning",
                "current_label": "正在制定执行计划",
                "next_label": "按计划逐步执行",
                "eta_text": "正在估算",
                "eta_basis": "planning",
                "workflow_current": 1,
                "workflow_completed": 0,
                "workflow_total": 1,
                "steps": [
                    {
                        "index": 1,
                        "tool": "planner",
                        "label": "理解任务并制定执行计划",
                        "status": "running",
                    }
                ],
            },
        )
        graph_input = {
            "workflow_id": workflow_id,
            "message": clean_message,
            "history": clean_history,
            **({"preplanned": safe_plan} if safe_plan is not None else {}),
        }
        if run_in_background:
            background = asyncio.create_task(self._drive_with_report(workflow_id, graph_input))
            self._background.add(background)
            background.add_done_callback(self._background_done)
            task = self.store.get_task(workflow_id) or {}
            response = self._response(
                safe_plan
                or {
                    "reply": (
                        "收到啦，这件事交给我。我正在把它拆成可执行步骤，"
                        "进度会实时更新；完成后我会把交付报告送到这里。"
                    )
                },
                task,
            )
            reply = redact_text(response.get("reply") or "", limit=legacy.MAX_MESSAGE_CHARS)
            if reply:
                self.store.add_message("assistant", reply, workflow_id=workflow_id)
            return response

        response = await self._drive(workflow_id, graph_input)
        reply = redact_text(response.get("reply") or "", limit=legacy.MAX_MESSAGE_CHARS)
        if reply:
            self.store.add_message("assistant", reply, workflow_id=workflow_id)
        return response

    async def record_answer(
        self,
        message: str,
        reply: str,
        *,
        answer_id: str,
        image: Any = None,
        model: str = "local",
    ) -> dict[str, Any]:
        """Persist a chat answer without creating or executing a task."""

        await self.start()
        clean_message = redact_text(message, limit=legacy.MAX_MESSAGE_CHARS)
        clean_reply = redact_text(reply, limit=legacy.MAX_MESSAGE_CHARS)
        if not clean_message or not clean_reply:
            raise ValueError("问题或回答不能为空")
        image_name = ""
        if image not in (None, "", {}):
            if not isinstance(image, dict):
                raise ValueError("图片附件格式不正确")
            raw_name = str(image.get("name") or "图片").replace("\\", "/").rsplit("/", 1)[-1]
            image_name = redact_text(raw_name, limit=120) or "图片"
        stored_message = f"🖼 已附图片：{image_name}\n{clean_message}" if image_name else clean_message
        self.store.add_message("user", stored_message, workflow_id=answer_id)
        self.store.add_message("assistant", clean_reply, workflow_id=answer_id)
        return {
            "ok": True,
            "engine": "answer",
            "answer_only": True,
            "answer_id": answer_id,
            "workflow_id": "",
            "reply": clean_reply,
            "model": model,
            "tool_results": [],
            "pending_actions": [],
            "rejected_actions": [],
            "task": None,
            "usage": usage_summary(workflow_id=answer_id),
        }

    async def _drive_with_report(self, workflow_id: str, graph_input: Any) -> dict[str, Any]:
        try:
            response = await self._drive(workflow_id, graph_input)
        except Exception:
            task = self.store.get_task(workflow_id, include_events=False) or {}
            task = self._ensure_task_report(workflow_id, task)
            self.store.add_assistant_message_once(workflow_id, self._completion_chat(task))
            return {"ok": False, "workflow_id": workflow_id, "task": task}
        task = self.store.get_task(workflow_id, include_events=False) or response.get("task") or {}
        if task.get("terminal"):
            task = self._ensure_task_report(workflow_id, task)
            self.store.add_assistant_message_once(workflow_id, self._completion_chat(task))
        return response

    async def confirm(self, confirmation_id: str, *, approve: bool) -> dict[str, Any]:
        await self.start()
        task = self.store.get_by_confirmation(redact_text(confirmation_id, limit=200))
        if not task or task.get("status") != "awaiting_confirmation":
            raise ValueError("确认已失效或不存在，请重新下达指令")
        workflow_id = str(task["id"])
        self.store.update_task(
            workflow_id,
            status="accepted" if approve else "running",
            phase="accepted" if approve else "skipping",
            message="已确认，准备执行" if approve else "已拒绝这个操作",
            confirmation_id="",
            pending=None,
        )
        self.store.add_event(
            workflow_id,
            "confirmation",
            status="accepted" if approve else "running",
            phase="accepted" if approve else "skipping",
            message="用户确认执行" if approve else "用户拒绝执行",
            detail={"approved": bool(approve)},
            event_key=f"confirmation:{task.get('pending_action', {}).get('action_index', 0)}",
        )
        pending = task.get("pending_action") or {}
        if approve and pending.get("tool") in {
            "generate_image",
            "batch_generate",
            "batch_generate_and_prepare_pixiv",
            "prepare_pixiv_submission",
        }:
            background = asyncio.create_task(
                self._drive_with_report(workflow_id, Command(resume={"approve": True}))
            )
            self._background.add(background)
            background.add_done_callback(self._background_done)
            accepted = self.store.get_task(workflow_id) or {}
            return {
                "ok": True,
                "engine": "langgraph",
                "workflow_id": workflow_id,
                "reply": "收到确认啦，我现在就开始执行。你可以继续做别的，我会实时更新进度，完成后把报告交给你。",
                "tool_results": [],
                "pending_actions": [],
                "rejected_actions": [],
                "cancelled": False,
                "result": None,
                "task": accepted,
            }
        response = await self._drive(workflow_id, Command(resume={"approve": bool(approve)}))
        completed = self.store.get_task(workflow_id, include_events=False) or response.get("task") or {}
        if completed.get("terminal"):
            completed = self._ensure_task_report(workflow_id, completed)
            self.store.add_assistant_message_once(workflow_id, self._completion_chat(completed))
        return response

    def _background_done(self, task: asyncio.Task[Any]) -> None:
        self._background.discard(task)
        if task.cancelled():
            return
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    async def cancel(self, workflow_id: str) -> dict[str, Any]:
        await self.start()
        task = self.store.get_task(workflow_id)
        if not task:
            raise ValueError("管家任务不存在")
        if task["status"] in TERMINAL_STATUSES:
            return {"ok": True, "task": task, "message": "任务已经结束"}
        self.store.update_task(
            workflow_id,
            cancel_requested=True,
            message="正在取消任务…",
        )
        self.store.add_event(
            workflow_id,
            "cancel_requested",
            status=task["status"],
            phase=task["phase"],
            message="用户请求取消工作流",
            event_key="workflow:cancel_requested",
        )
        if task["status"] == "awaiting_confirmation":
            return await self._drive(
                workflow_id,
                Command(resume={"approve": False, "cancel_workflow": True}),
            )
        progress = task.get("progress") or {}
        generation_task_id = str(progress.get("generation_task_id") or "")
        if generation_task_id:
            try:
                from nai_batch import cancel_batch

                cancel_batch(generation_task_id)
            except Exception:
                pass
        return {"ok": True, "task": self.store.get_task(workflow_id), "message": "取消请求已提交"}

    async def resume(self, workflow_id: str) -> dict[str, Any]:
        await self.start()
        task = self.store.get_task(workflow_id)
        if not task:
            raise ValueError("管家任务不存在")
        if task["status"] != "paused":
            raise ValueError("只有安全暂停的任务可以继续；结果未知的任务必须核对后重试")
        self.store.update_task(
            workflow_id,
            status="running",
            phase="resuming",
            message="正在从最近检查点继续…",
        )
        return await self._drive(workflow_id, None)

    async def retry(self, workflow_id: str) -> dict[str, Any]:
        await self.start()
        task = self.store.get_task(workflow_id)
        if not task:
            raise ValueError("管家任务不存在")
        if task["status"] not in {"failed", "partially_succeeded", "unknown", "cancelled"}:
            raise ValueError("只有失败、部分成功、结果未知或已取消的任务可以重试")
        input_data = task.get("input") or {}
        message = str(input_data.get("message") or "")
        preplanned = input_data.get("preplanned")
        if not isinstance(preplanned, dict):
            preplanned = _local_read_only_plan(message)
        return await self.submit(
            message,
            input_data.get("history"),
            preplanned=preplanned,
            retry_of=workflow_id,
        )

    async def _drive(self, workflow_id: str, graph_input: Any) -> dict[str, Any]:
        await self.start()
        lock = self._run_locks.setdefault(workflow_id, asyncio.Lock())
        async with lock:
            try:
                config = {"configurable": {"thread_id": workflow_id}}
                with usage_scope(workflow_id):
                    result = await self._graph.ainvoke(graph_input, config=config)
                interrupts = result.get("__interrupt__") or []
                if interrupts:
                    interruption = interrupts[0]
                    payload = copy.deepcopy(interruption.value)
                    progress = dict(
                        (self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}
                    )
                    step_index = int(payload.get("action_index") or 0)
                    steps = [dict(item) for item in (progress.get("steps") or [])]
                    if 0 <= step_index < len(steps):
                        steps[step_index]["status"] = "waiting"
                    progress.update(
                        {
                            "steps": steps,
                            "stage": "awaiting_confirmation",
                            "current_label": str(payload.get("label") or payload.get("summary") or "等待你的确认"),
                            "eta_text": "确认后继续估算",
                            "eta_basis": "waiting_for_user",
                            "estimate_updated_at": _now(),
                        }
                    )
                    pending = {
                        **payload,
                        "confirmation_id": str(interruption.id),
                        "expires_in": 0,
                    }
                    self.store.update_task(
                        workflow_id,
                        status="awaiting_confirmation",
                        phase="awaiting_confirmation",
                        message=str(payload.get("summary") or "等待确认"),
                        pending=pending,
                        confirmation_id=str(interruption.id),
                        progress=progress,
                    )
                    self.store.add_event(
                        workflow_id,
                        "awaiting_confirmation",
                        status="awaiting_confirmation",
                        phase="awaiting_confirmation",
                        message=str(payload.get("summary") or "等待确认"),
                        detail={"tool": payload.get("tool"), "operation_id": payload.get("operation_id")},
                        event_key=f"action:{payload.get('action_index', 0)}:awaiting_confirmation",
                    )
                task = self.store.get_task(workflow_id) or {}
                return self._response(result, task)
            except UnknownExternalOutcome as exc:
                task = self.store.update_task(
                    workflow_id,
                    status="unknown",
                    phase="needs_review",
                    message="外部操作结果未知，已停止自动重放",
                    error=redact_text(exc, limit=500),
                    finished_at=_now(),
                )
                self.store.add_event(
                    workflow_id,
                    "unknown",
                    status="unknown",
                    phase="needs_review",
                    message=str(exc),
                    event_key="workflow:unknown",
                )
                return self._response({}, task)
            except Exception as exc:
                task = self.store.update_task(
                    workflow_id,
                    status="failed",
                    phase="failed",
                    message="管家工作流失败",
                    error=redact_text(legacy.public_error(exc), limit=500),
                    finished_at=_now(),
                )
                self.store.add_event(
                    workflow_id,
                    "failed",
                    status="failed",
                    phase="failed",
                    message=redact_text(legacy.public_error(exc), limit=500),
                    event_key="workflow:failed",
                )
                raise

    @staticmethod
    def _response(state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        pending = task.get("pending_action")
        tool_results = state.get("tool_results") or (task.get("result") or {}).get("tool_results") or []
        return {
            "ok": True,
            "engine": "langgraph",
            "workflow_id": task.get("id") or state.get("workflow_id") or "",
            "reply": state.get("reply")
            or (task.get("result") or {}).get("reply")
            or task.get("message")
            or "",
            "model": state.get("model") or "",
            "tool_results": tool_results,
            "pending_actions": [pending] if pending else [],
            "rejected_actions": state.get("rejected_actions")
            or (task.get("result") or {}).get("rejected_actions")
            or [],
            "cancelled": task.get("status") == "cancelled",
            "result": tool_results[-1] if tool_results else None,
            "task": task,
        }

    def status(self) -> dict[str, Any]:
        tasks = self.store.list_tasks(limit=20)
        return {
            "engine": "langgraph",
            "started": self._started,
            "state_path": self.state_path.name,
            "checkpoint_path": self.checkpoint_path.name,
            "checkpoint_encrypted": False,
            "secrets_in_checkpoint": False,
            "retention_days": int(os.environ.get("BUTLER_RETENTION_DAYS", "30")),
            "recovery": dict(self._recovery),
            "active": sum(1 for task in tasks if not task.get("terminal")),
        }
