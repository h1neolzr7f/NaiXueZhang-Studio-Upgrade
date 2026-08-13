"""Confirmed and paid tool loops mixed into ButlerWorkflowRuntime."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from knowledge_catalog import KnowledgeRefreshCancelled

from .redaction import redact_text
from .workflow_helpers import (
    UnknownExternalOutcome,
    WorkflowCancelled,
    _format_eta,
    _now,
    _operation_identity,
    _status_poll_delay,
)


class _LegacyProxy:
    def __getattr__(self, name: str) -> Any:
        import butler.workflow as wf

        return getattr(wf.legacy, name)


legacy = _LegacyProxy()


def get_knowledge_catalog(*args: Any, **kwargs: Any) -> Any:
    import butler.workflow as wf

    return wf.get_knowledge_catalog(*args, **kwargs)


class ButlerWorkflowExecutors:
    """Project long-running local/paid tools onto the durable Butler task store."""

    async def _execute_knowledge_refresh(
        self,
        workflow_id: str,
        action_index: int,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the trusted local rebuild behind the existing task/report Interface."""

        operation_id, arguments_hash = _operation_identity(workflow_id, action_index, action)
        previous = self.store.get_receipt(operation_id)
        if previous and previous.get("status") == "succeeded":
            return dict(previous.get("result") or {})
        self.store.put_receipt(
            operation_id,
            task_id=workflow_id,
            action_index=action_index,
            tool=action["tool"],
            arguments_hash=arguments_hash,
            status="started",
        )
        catalog = get_knowledge_catalog(ensure_ready=False)
        started = time.monotonic()
        last_emit = 0.0

        def cancelled() -> bool:
            task = self.store.get_task(workflow_id, include_events=False) or {}
            return bool(task.get("cancel_requested"))

        def publish(event: dict[str, Any]) -> None:
            nonlocal last_emit
            now = time.monotonic()
            current = max(0, int(event.get("processed") or 0))
            total = max(current, int(event.get("total") or 0))
            terminal = total == 0 or current >= total
            if not terminal and current > 0 and now - last_emit < 0.1:
                return
            last_emit = now
            elapsed = max(0.001, now - started)
            eta = 0.0
            if current > 0 and total > current:
                eta = (elapsed / current) * (total - current)
            source = redact_text(event.get("current_source") or "", limit=140)
            current_label = (
                f"正在索引：{source}（{current}/{total}）"
                if source and total
                else f"正在检查知识源（{current}/{total}）"
                if total
                else "正在检查内置知识源"
            )
            task = self.store.get_task(workflow_id, include_events=False) or {}
            progress = dict(task.get("progress") or {})
            progress.update(
                {
                    "item_current": current,
                    "item_total": total,
                    "item_succeeded": int(event.get("inserted") or 0)
                    + int(event.get("updated") or 0)
                    + int(event.get("unchanged") or 0),
                    "item_failed": 0,
                    "current_source": source,
                    "current_label": current_label,
                    "next_label": "生成版本与交付报告" if terminal else "继续增量检查其余知识源",
                    "eta_seconds": int(round(eta)),
                    "eta_text": "即将完成" if terminal else _format_eta(eta),
                    "eta_basis": "observed_source_rate" if current else "initial_estimate",
                    "estimate_updated_at": _now(),
                }
            )
            self.store.update_task(
                workflow_id,
                phase="tool:rebuild_knowledge_catalog",
                message=current_label,
                progress=progress,
            )

        try:
            receipt = await asyncio.to_thread(
                catalog.refresh_builtin_sources,
                on_progress=publish,
                should_cancel=cancelled,
            )
        except KnowledgeRefreshCancelled as exc:
            self.store.put_receipt(
                operation_id,
                task_id=workflow_id,
                action_index=action_index,
                tool=action["tool"],
                arguments_hash=arguments_hash,
                status="failed",
                error="cancelled",
            )
            raise WorkflowCancelled(str(exc)) from exc
        except Exception as exc:
            self.store.put_receipt(
                operation_id,
                task_id=workflow_id,
                action_index=action_index,
                tool=action["tool"],
                arguments_hash=arguments_hash,
                status="failed",
                error=legacy.public_error(exc),
            )
            raise
        result = {
            **receipt,
            "ok": True,
            "tool": action["tool"],
            "provider": "local",
            "model_calls": 0,
            "settings_url": "/settings#knowledgeCatalog",
            "message": (
                f"知识库增量更新完成：{int(receipt.get('documents') or 0)} 个来源、"
                f"{int(receipt.get('chunks') or 0)} 个知识块"
            ),
        }
        self.store.put_receipt(
            operation_id,
            task_id=workflow_id,
            action_index=action_index,
            tool=action["tool"],
            arguments_hash=arguments_hash,
            status="succeeded",
            result=result,
        )
        return result

    async def _execute_director(
        self,
        workflow_id: str,
        args: dict[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        """Run a confirmed Director batch while mirroring truthful progress."""

        from nai_director import (
            cancel_director_batch,
            director_batch_status,
            preview_director_batch,
            start_director_batch,
        )

        sources = list(args.get("sources") or [])
        recipe = dict(args.get("recipe") or {})
        preview = preview_director_batch(sources, recipe)
        if not preview.get("ready") or not preview.get("preview_id"):
            failures = list(preview.get("failures") or []) + list(preview.get("blocking_issues") or [])
            detail = "; ".join(str(item.get("message") or "") for item in failures if isinstance(item, dict))
            raise RuntimeError(detail or "批量导演零费用预检未通过")
        started = start_director_batch(
            sources,
            recipe,
            confirmed=True,
            preview_id=str(preview["preview_id"]),
        )
        if not started.get("ok"):
            raise RuntimeError(str(started.get("message") or "批量导演启动失败"))
        director_task_id = str(started.get("task_id") or "")
        observed_started = time.monotonic()
        base_progress = dict(
            (self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}
        )
        self.store.update_task(
            workflow_id,
            status="running",
            phase="directing",
            message="批量导演已接单，正在准备第一张来源图",
            progress={
                **base_progress,
                "current": 0,
                "total": len(sources),
                "succeeded": 0,
                "failed": 0,
                "director_task_id": director_task_id,
                "operation_id": operation_id,
                "item_current": 0,
                "item_total": len(sources),
                "eta_text": "等待首张完成后按实际速度计算",
                "eta_basis": "warming_up",
            },
        )
        state: dict[str, Any] = {}
        while True:
            state = director_batch_status(director_task_id)
            status = str(state.get("status") or "")
            done = int(state.get("done") or 0)
            total = int(state.get("total") or len(sources))
            progress = {
                **base_progress,
                "current": done,
                "total": total,
                "succeeded": int(state.get("ok_count") or 0),
                "failed": int(state.get("fail_count") or 0),
                "director_task_id": director_task_id,
                "operation_id": operation_id,
                "item_current": done,
                "item_total": total,
            }
            if done > 0 and total > done:
                eta_seconds = (time.monotonic() - observed_started) / done * (total - done)
                progress.update(
                    {
                        "eta_seconds": int(round(eta_seconds)),
                        "eta_text": _format_eta(eta_seconds),
                        "eta_basis": "observed_rate",
                        "estimate_updated_at": _now(),
                    }
                )
            elif total and done >= total:
                progress.update(
                    {"eta_seconds": 0, "eta_text": "马上完成", "eta_basis": "observed_rate"}
                )
            else:
                progress.update(
                    {"eta_text": "等待首张完成后按实际速度计算", "eta_basis": "warming_up"}
                )
            self.store.update_task(
                workflow_id,
                status="running",
                phase="directing",
                message=str(state.get("message") or "NAI 批量导演执行中…"),
                progress=progress,
            )
            task = self.store.get_task(workflow_id, include_events=False) or {}
            if task.get("cancel_requested"):
                cancel_director_batch(director_task_id)
            if state.get("terminal") or status not in {"running", "cancelling", ""}:
                break
            await asyncio.sleep(_status_poll_delay(observed_started))

        status = str(state.get("status") or "")
        if status == "cancelled":
            raise WorkflowCancelled("批量导演已在当前请求安全返回后停止")
        if status == "unknown" or state.get("needs_review"):
            raise UnknownExternalOutcome(
                str(state.get("message") or "批量导演结果无法自动确认，请先核对生成结果")
            )
        if status == "error":
            raise RuntimeError(str(state.get("message") or "批量导演执行失败，请检查失败原因"))
        report = dict(state.get("report") or {})
        success = int(report.get("success_sources") or state.get("ok_count") or 0)
        failed = int(report.get("failed_sources") or state.get("fail_count") or 0)
        output_count = int(report.get("output_count") or 0)
        if success <= 0:
            raise RuntimeError(str(state.get("message") or "批量导演没有成功结果"))
        return {
            "ok": failed == 0,
            "partial": failed > 0,
            "completed": True,
            "tool": "batch_director",
            "director_task_id": director_task_id,
            "processed": int(state.get("done") or 0),
            "succeeded": success,
            "failed": failed,
            "generated": output_count,
            "items": list(state.get("items") or []),
            "report": report,
            "director_url": "/director",
            "gallery_url": "/generated",
            "message": str(state.get("message") or f"批量导演完成：交付 {output_count} 张结果"),
        }

    async def _execute_pipeline(
        self,
        workflow_id: str,
        action: dict[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        """Start post-processing and keep the Butler progress/report truthful."""
        from post_pipeline import pipeline_status

        started = await self._confirmed_executor(action)
        total = int(started.get("total") or 0)
        if total <= 0:
            return started
        observed_started = time.monotonic()
        base_progress = dict(
            (self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}
        )
        self.store.update_task(
            workflow_id,
            status="running",
            phase="post_processing",
            message=str(started.get("message") or "后处理已启动"),
            progress={
                **base_progress,
                "current": 0,
                "total": total,
                "succeeded": 0,
                "failed": 0,
                "operation_id": operation_id,
                "item_current": 0,
                "item_total": total,
                "eta_text": "正在按实际处理速度计算",
                "eta_basis": "warming_up",
            },
        )
        while True:
            state = pipeline_status()
            status = str(state.get("status") or "")
            progress = {
                **base_progress,
                "current": int(state.get("done") or 0),
                "total": int(state.get("total") or total),
                "succeeded": int(state.get("ok") or 0),
                "failed": int(state.get("fail") or 0),
                "operation_id": operation_id,
            }
            done = progress["current"]
            item_total = progress["total"]
            progress.update({"item_current": done, "item_total": item_total})
            if done > 0 and item_total > done:
                eta_seconds = (time.monotonic() - observed_started) / done * (item_total - done)
                progress.update(
                    {
                        "eta_seconds": int(round(eta_seconds)),
                        "eta_text": _format_eta(eta_seconds),
                        "eta_basis": "observed_rate",
                        "estimate_updated_at": _now(),
                    }
                )
            elif item_total and done >= item_total:
                progress.update({"eta_seconds": 0, "eta_text": "马上完成", "eta_basis": "observed_rate"})
            self.store.update_task(
                workflow_id,
                status="running",
                phase="post_processing",
                message=str(state.get("message") or "后处理中…"),
                progress=progress,
            )
            if status != "running":
                break
            await asyncio.sleep(_status_poll_delay(observed_started))
        failed = int(state.get("fail") or 0)
        succeeded = int(state.get("ok") or 0)
        return {
            **started,
            "ok": failed == 0 and succeeded > 0,
            "partial": failed > 0 and succeeded > 0,
            "completed": True,
            "succeeded": succeeded,
            "failed": failed,
            "items": list(state.get("items") or []),
            "message": str(state.get("message") or f"后处理完成：成功 {succeeded}，失败 {failed}"),
        }

    async def _execute_batch(
        self,
        workflow_id: str,
        args: dict[str, Any],
        operation_id: str,
        *,
        prepare_pixiv: bool,
    ) -> dict[str, Any]:
        from nai_batch import batch_status, cancel_batch, start_batch

        refs = args.get("work_refs") or [
            {"gallery_id": args.get("gallery_id") or "site", "work_id": work_id}
            for work_id in args["work_ids"]
        ]
        for ref in refs:
            legacy._require_work(int(ref["work_id"]), ref.get("gallery_id") or "site")
        targets = legacy._batch_targets(args)
        recipe = dict(args.get("remix_recipe") or {})
        if not recipe:
            recipe = {
                "transform": {"enabled": False},
                "sanitize": {"enabled": True},
                "prompt_profile": "native",
            }
        from char_swap_config import load_config as load_char_swap_config

        started = start_batch(
            targets,
            recipe,
            force_free=bool(load_char_swap_config().get("force_free", True)),
            generate=True,
            preview_only=False,
        )
        if not started.get("ok"):
            raise RuntimeError(str(started.get("message") or "批量生成启动失败"))
        generation_task_id = str((started.get("batch") or {}).get("id") or "")
        observed_started = time.monotonic()
        base_progress = dict(
            (self.store.get_task(workflow_id, include_events=False) or {}).get("progress") or {}
        )
        self.store.update_task(
            workflow_id,
            phase="generating",
            message="批量生成已启动",
            progress={
                **base_progress,
                "current": 0,
                "total": len(targets),
                "succeeded": 0,
                "failed": 0,
                "generation_task_id": generation_task_id,
                "operation_id": operation_id,
                "item_current": 0,
                "item_total": len(targets),
                "eta_text": "等待首张完成后按实际速度计算",
                "eta_basis": "warming_up",
            },
        )
        while True:
            state = batch_status(generation_task_id) if generation_task_id else batch_status()
            status = str(state.get("status") or "")
            progress = {
                **base_progress,
                "current": int(state.get("done") or 0),
                "total": int(state.get("total") or len(targets)),
                "succeeded": int(state.get("ok_count") or 0),
                "failed": int(state.get("fail_count") or 0),
                "generation_task_id": generation_task_id,
                "operation_id": operation_id,
            }
            done = progress["current"]
            item_total = progress["total"]
            progress.update({"item_current": done, "item_total": item_total})
            if done > 0 and item_total > done:
                eta_seconds = (time.monotonic() - observed_started) / done * (item_total - done)
                progress.update(
                    {
                        "eta_seconds": int(round(eta_seconds)),
                        "eta_text": _format_eta(eta_seconds),
                        "eta_basis": "observed_rate",
                        "estimate_updated_at": _now(),
                    }
                )
            elif item_total and done >= item_total:
                progress.update({"eta_seconds": 0, "eta_text": "马上完成", "eta_basis": "observed_rate"})
            self.store.update_task(
                workflow_id,
                status="running",
                phase="generating",
                message=str(state.get("message") or "批量生成中…"),
                progress=progress,
            )
            task = self.store.get_task(workflow_id, include_events=False) or {}
            if task.get("cancel_requested"):
                cancel_batch(generation_task_id) if generation_task_id else cancel_batch()
            if status not in {"running", "cancelling", ""}:
                break
            await asyncio.sleep(_status_poll_delay(observed_started))
        if status == "cancelled":
            raise WorkflowCancelled("批量生成已取消")
        ok_count = int(state.get("ok_count") or 0)
        fail_count = int(state.get("fail_count") or 0)
        if ok_count <= 0:
            raise RuntimeError(str(state.get("message") or "批量生成没有成功结果"))
        image_ids: list[str] = []
        by_work: dict[str, list[str]] = {}
        raw_items = list(state.get("items") or [])
        report_items: list[dict[str, Any]] = []
        for item in raw_items:
            report_items.append(
                {
                    key: item.get(key)
                    for key in (
                        "gallery_id", "work_id", "page_index", "ok", "skipped",
                        "image_url", "filename", "message", "summary",
                        "transform_applied", "style_replacements", "sanitize_removed", "remix",
                        "style_applied",
                    )
                    if item.get(key) not in (None, "")
                }
            )
            if not item.get("ok"):
                continue
            filename = str(item.get("filename") or "").strip()
            if not filename:
                image_url = str(item.get("image_url") or "").split("?", 1)[0]
                filename = image_url.rsplit("/", 1)[-1]
            image_id = filename.rsplit(".", 1)[0] if filename else ""
            if not image_id or image_id in image_ids:
                continue
            image_ids.append(image_id)
            gallery_id = str(item.get("gallery_id") or "site")
            work_id = str(item.get("work_id") or "standalone")
            work_key = work_id if gallery_id == "site" else f"{gallery_id}:{work_id}"
            by_work.setdefault(work_key, []).append(image_id)
        transform = recipe.get("transform") or {}
        style = recipe.get("style") or {}
        style_reference = style.get("reference") or {}
        applied_count = sum(1 for item in raw_items if item.get("ok") and item.get("transform_applied"))
        style_applied_count = sum(1 for item in raw_items if item.get("ok") and item.get("style_applied"))
        result: dict[str, Any] = {
            "ok": True,
            "tool": "batch_generate_and_prepare_pixiv" if prepare_pixiv else "batch_generate",
            "generation_task_id": generation_task_id,
            "generated": ok_count,
            "failed": fail_count,
            "image_ids": image_ids,
            "items": report_items,
            "gallery_url": "/generated",
            "quality": {
                "replacement_requested": bool(transform.get("enabled")),
                "replacement_applied": applied_count,
                "preset_id": str(transform.get("preset_id") or ""),
                "preset_label": str(transform.get("preset_label") or ""),
                "mode": str(transform.get("mode") or ""),
                "target": transform.get("target_char_index", "auto"),
                "verified_items": len(raw_items),
                "style_requested": bool(style),
                "style_applied": style_applied_count,
                "style_preset_id": str(style.get("preset_id") or ""),
                "style_preset_label": str(style.get("preset_label") or ""),
                "style_reference_id": str(style_reference.get("style_id") or ""),
                "style_reference_label": str(style_reference.get("label") or ""),
                "style_reference_source": str(style_reference.get("source") or ""),
                "style_mode": str(style.get("mode") or ""),
            },
        }
        if not prepare_pixiv:
            if transform.get("enabled") and style:
                result["message"] = (
                    f"换角、换画风并生成完成：成功 {ok_count}，失败 {fail_count}；"
                    f"已验证换角 {applied_count} 张、换画风 {style_applied_count} 张"
                )
            elif transform.get("enabled"):
                result["message"] = (
                    f"换角并生成完成：成功 {ok_count}，失败 {fail_count}；"
                    f"已验证 {applied_count} 张实际应用角色替换"
                )
            elif style:
                result["message"] = (
                    f"换画风并生成完成：成功 {ok_count}，失败 {fail_count}；"
                    f"已验证 {style_applied_count} 张实际应用画风"
                )
            else:
                result["message"] = f"批量生成完成：成功 {ok_count}，失败 {fail_count}"
            return result
        if not image_ids:
            raise RuntimeError("批量生成完成，但没有找到可交接投稿的图片")
        self.store.update_task(
            workflow_id,
            phase="preparing_pixiv",
            message=f"正在为 {len(by_work)} 个系列准备投稿草稿…",
        )
        from pixiv_launch import prepare_submission_package

        prepared_result = await asyncio.to_thread(
            prepare_submission_package,
            {
                "series": [
                    {"group_id": group_id, "image_ids": ids}
                    for group_id, ids in by_work.items()
                    if ids
                ],
                "extra": str(args.get("extra") or ""),
                "package_id": workflow_id,
            },
        )
        prepared = prepared_result.get("prepared") or prepared_result
        result.update(
            {
                "prepared": prepared,
                "submission_drafts": list(prepared.get("items") or []),
                "pixiv_url": prepared.get("pixiv_url") or f"/pixiv?prepared=1&package={workflow_id}",
                "message": "批量生成、后处理和多系列投稿草稿已完成，等待人工发布",
            }
        )
        return result
