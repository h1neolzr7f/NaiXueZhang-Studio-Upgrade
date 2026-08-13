"""Durable, ordered batch character/style replacement and NAI generation."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

from generation_jobs import (
    TERMINAL_STATUSES,
    GenerationJob,
    GenerationJobManager,
    JobPersistenceError,
    partition_retry_targets,
)
from generated_gallery import _group_key
from nai_api import generate_image, generation_concurrency, queue_status
from nai_char import BATCH_TARGET_MAX, prepare_work_draft
from paths import data_dir


def _work_group_url(
    work_id: int | None,
    *,
    source_gallery_id: str = "site",
    generation_series_id: str = "",
) -> str:
    # Work-scoped view (includes all run: series for that work after _matches_group fix).
    key = _group_key(
        work_id,
        source_gallery_id=source_gallery_id,
        generation_series_id="",  # bare work group aggregates series
    )
    return f"/generated?g={key}"

try:
    from nai_api import generation_concurrency_for_batch as _pool_concurrency
except ImportError:
    _pool_concurrency = None


_JOB_MANAGER = GenerationJobManager(
    state_path=Path(data_dir()) / "generation_jobs.json",
)
_RETRYABLE_ERRORS = frozenset({"busy", "cooldown", "rate_limited", "connect_failed"})
_RETRYABLE_TEXT = (
    "429",
    "too frequent",
    "retry later",
    "tls/connect failed before request",
)
# 批处理重试退避按 provider 分离：
# - NAI 官方 API 冷却短（_COOLDOWN_SEC=3s），重试等待给少量余量即可
# - 闲云(xianyun) 中转慢且冷却长（_XIANYUN_COOLDOWN_SEC=20s），保持慢速重试
_NAI_DEFER_RETRY_SEC = 8.0
_XIANYUN_DEFER_RETRY_SEC = 45.0
_MIN_TRANSIENT_RETRY_BUDGET_SEC = 5 * 60.0
_TRANSIENT_RETRY_BUDGET_PER_TARGET_SEC = 30.0
_MAX_TRANSIENT_RETRY_BUDGET_SEC = 2 * 60 * 60.0


def _defer_retry_sec(provider: str) -> float:
    """Return defer wait for a provider; xianyun keeps the slow path."""
    from nai_api import PROVIDER_XIANYUN, _provider_key
    return _XIANYUN_DEFER_RETRY_SEC if _provider_key(provider) == PROVIDER_XIANYUN else _NAI_DEFER_RETRY_SEC


def _transient_retry_budget_sec(target_count: int) -> float:
    """Bound transient retries by elapsed time, scaled for long serial batches."""
    return min(
        _MAX_TRANSIENT_RETRY_BUDGET_SEC,
        max(
            _MIN_TRANSIENT_RETRY_BUDGET_SEC,
            max(1, int(target_count or 0)) * _TRANSIENT_RETRY_BUDGET_PER_TARGET_SEC,
        ),
    )


def _max_transient_retry_cycles(target_count: int) -> int:
    """Safety fuse for mocked clocks and providers returning zero retry delays."""
    return max(4, max(1, int(target_count or 0)) * 3)


def generation_concurrency_for_batch(
    targets: list[dict[str, Any]] | None = None,
    *,
    force_free: bool = True,
) -> int:
    """Return provider-pool concurrency without enabling per-account concurrency."""
    legacy_slots = max(0, int(generation_concurrency() or 0))
    target_count = len(targets or [])
    if target_count:
        legacy_slots = min(legacy_slots, target_count)
    # nai_api.generation_concurrency_for_batch 是对同一 token 池的重复计算
    # （min(count, generation_concurrency())），不携带 legacy 之外的可用性
    # 信息；legacy 计数可被调用方 patch，是兼容权威。模块级导入的
    # _pool_concurrency 仅为向后兼容保留，此处不再执行其死代码计算。
    return legacy_slots


def batch_status(task_id: str | None = None) -> dict[str, Any] | None:
    return _JOB_MANAGER.status(task_id)


def _reset_running(*, total: int, generate: bool, preview_only: bool) -> dict[str, Any]:
    """Compatibility hook for legacy in-process batch callers and tests.

    The durable manager remains the sole source of truth; this helper merely
    starts an isolated active job instead of resurrecting the former global
    ``_BATCH`` dictionary.
    """

    global _JOB_MANAGER
    _JOB_MANAGER = GenerationJobManager(
        state_path=Path(data_dir()) / "generation_jobs.json",
    )
    job = _JOB_MANAGER.start_job(
        total=total,
        generate=generate,
        preview_only=preview_only,
    )
    return _JOB_MANAGER.status(job.task_id) or {}


def _is_retryable_failure(item: dict[str, Any]) -> bool:
    if item.get("ok") or item.get("skipped"):
        return False
    if item.get("billing_uncertain") or item.get("retry_safe") is False:
        return False
    error = str(item.get("error") or "").lower()
    if error in _RETRYABLE_ERRORS:
        return True
    if item.get("retry_safe") and item.get("request_attempted") is False:
        return True
    message = str(item.get("message") or "").lower()
    if any(marker in message for marker in (" 500", " 502", " 503", " 504", "error 500", "error 502", "error 503", "error 504")):
        return False
    return any(part in message for part in _RETRYABLE_TEXT)


def _is_quota_exhausted(item: dict[str, Any]) -> bool:
    reason = str(item.get("failure_reason") or item.get("error") or "").lower()
    message = str(item.get("message") or "").lower()
    return reason == "quota_exhausted" or (
        "402" in message
        and ("not enough anlas" in message or "out of trial" in message)
    )


async def _generate_for_target(
    patched_comment: dict[str, Any],
    work_id: int | None,
    *,
    force_free: bool,
    prompt_profile: str = "native",
    source_gallery_id: str = "site",
    generation_series_id: str = "",
    source_title: str = "",
    source_thumb: str = "",
    remote_work_id: str = "",
    token_id: str = "",
    job: GenerationJob | None = None,
) -> dict[str, Any]:
    """Generate once per round; outer rounds provide visible, cancellable retry."""
    if job is not None and job.cancel_requested:
        return {
            "ok": False,
            "error": "cancelled",
            "message": "cancelled before provider request",
            "request_attempted": False,
        }
    label = f"#{work_id}" if work_id else "studio"
    if job is not None:
        current = queue_status()
        _JOB_MANAGER.update_progress(
            job,
            current_phase="generate",
            message=str(
                current.get("message")
                or f"{label} waiting for generation provider slot"
            ),
            active=current.get("active") or [],
        )
    result = await generate_image(
        patched_comment,
        work_id=work_id if work_id else None,
        source_gallery_id=source_gallery_id,
        force_free=force_free,
        prompt_profile=prompt_profile,
        token_id=token_id,
        generation_series_id=generation_series_id,
        source_title=source_title,
        source_thumb=source_thumb,
        remote_work_id=remote_work_id,
        wait_for_slot=True,
    )
    result.setdefault(
        "request_attempted",
        str(result.get("error") or "").lower()
        not in {"busy", "cooldown", "rate_limited", "missing_token", "connect_failed"},
    )
    return result


def _base_item(raw: dict[str, Any], retry_round: int) -> dict[str, Any]:
    try:
        work_id = int(raw.get("work_id") or 0)
    except (TypeError, ValueError):
        work_id = 0
    return {
        "target_index": int(raw.get("_target_index", 0)),
        "gallery_id": str(raw.get("gallery_id") or "site"),
        "work_id": work_id or None,
        "page_index": int(raw.get("page_index") or 0),
        "retry_round": int(retry_round),
        "ok": False,
    }


async def _process_target(
    raw: dict[str, Any],
    recipe: dict[str, Any],
    *,
    force_free: bool,
    generate: bool,
    preview_only: bool,
    retry_round: int,
    job: GenerationJob,
) -> dict[str, Any]:
    item = _base_item(raw, retry_round)
    work_id = item["work_id"]
    page_index = item["page_index"]
    _JOB_MANAGER.update_progress(
        job,
        current_work_id=work_id,
        current_page_index=page_index,
        current_phase="prepare",
        message=f"#{work_id or 'studio'} p{page_index} preparing recipe",
    )
    try:
        if raw.get("frozen_comment") and isinstance(raw.get("patched_comment"), dict):
            prepared = {
                "ok": True,
                "patched_comment": copy.deepcopy(raw["patched_comment"]),
                "summary": "click-time snapshot",
                "style_replacements": 0,
                "message": "using frozen generation snapshot",
            }
        else:
            prepare_kwargs: dict[str, Any] = {
                "recipe": recipe,
                "patched_comment": raw.get("patched_comment"),
            }
            source_gallery_id = str(raw.get("gallery_id") or "site")
            if source_gallery_id != "site":
                prepare_kwargs["gallery_id"] = source_gallery_id
            prepared = prepare_work_draft(int(work_id or 0), page_index, **prepare_kwargs)
    except Exception as exc:
        item.update(error="prepare_failed", message=str(exc))
        return item

    if not prepared.get("ok"):
        item.update(
            skipped=bool(prepared.get("skipped")),
            error="skipped" if prepared.get("skipped") else "prepare_failed",
            message=str(prepared.get("message") or "draft preparation failed"),
            summary=prepared.get("summary"),
        )
        return item

    item.update(
        summary=prepared.get("summary"),
        style_replacements=int(prepared.get("style_replacements") or 0),
    )
    if preview_only or not generate:
        item.update(
            ok=True,
            preview_only=True,
            message=str(prepared.get("message") or "draft ready"),
            source_gallery_id=str(raw.get("gallery_id") or "site"),
            gallery_url=_work_group_url(
                work_id, source_gallery_id=str(raw.get("gallery_id") or "site")
            ),
            request_attempted=False,
        )
        return item

    source_gallery_id = str(raw.get("gallery_id") or "site")
    generate_kwargs = {
        "force_free": force_free,
        "prompt_profile": str(recipe.get("prompt_profile") or "native"),
        "source_gallery_id": source_gallery_id,
        "generation_series_id": job.task_id,
        "source_title": str(raw.get("source_title") or ""),
        "source_thumb": str(raw.get("source_thumb") or ""),
        "remote_work_id": str(raw.get("remote_work_id") or ""),
        "token_id": str(recipe.get("token_id") or ""),
        "job": job,
    }
    generated = await _generate_for_target(
        prepared["patched_comment"],
        work_id,
        **generate_kwargs,
    )
    # 短冷却 / 429 Retry-After：请求尚未扣费时，在 worker 内等完再打一次。
    retry_wait = float(generated.get("wait") or 0.0)
    retry_error = str(generated.get("error") or "").lower()
    if (
        not generated.get("ok")
        and retry_error in {"cooldown", "rate_limited"}
        and 0 < retry_wait <= 30.0
        and not generated.get("billing_uncertain")
        and not job.cancel_requested
    ):
        if await _JOB_MANAGER.wait_or_cancel(job, retry_wait):
            item.update(generated)
            item["work_id"] = work_id
            item["page_index"] = page_index
            item["target_index"] = int(raw.get("_target_index", 0))
            return item
        generated = await _generate_for_target(
            prepared["patched_comment"],
            work_id,
            **generate_kwargs,
        )
    item.update(generated)
    item["work_id"] = work_id
    item["page_index"] = page_index
    item["target_index"] = int(raw.get("_target_index", 0))
    if generated.get("ok") and not item.get("gallery_url"):
        item["gallery_url"] = (
            generated.get("gallery_url")
            or _work_group_url(
                work_id,
                source_gallery_id=source_gallery_id,
                generation_series_id=job.task_id,
            )
        )
    return item


def _count_item(job: GenerationJob, item: dict[str, Any]) -> None:
    if item.get("ok"):
        _JOB_MANAGER.increment_progress(job, "ok_count")
    elif item.get("skipped"):
        _JOB_MANAGER.increment_progress(job, "skip_count")
    else:
        _JOB_MANAGER.increment_progress(job, "fail_count")
    try:
        _JOB_MANAGER.append_item(job, item, count_done=True)
    except JobPersistenceError:
        item["billing_uncertain"] = True
        item["retry_safe"] = False
        raise


async def _run_round(
    pending: list[dict[str, Any]],
    recipe: dict[str, Any],
    *,
    force_free: bool,
    generate: bool,
    preview_only: bool,
    retry_round: int,
    concurrency: int,
    job: GenerationJob,
) -> tuple[list[dict[str, Any]], set[str], float, bool]:
    retry_later: list[dict[str, Any]] = []
    retry_providers: set[str] = set()
    retry_wait_sec = 0.0
    quota_exhausted = False
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for raw in pending:
        queue.put_nowait(raw)
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal quota_exhausted, retry_wait_sec
        while not job.cancel_requested and not quota_exhausted:
            try:
                raw = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                item = await _process_target(
                    raw,
                    recipe,
                    force_free=force_free,
                    generate=generate,
                    preview_only=preview_only,
                    retry_round=retry_round,
                    job=job,
                )
                if _is_quota_exhausted(item):
                    async with lock:
                        quota_exhausted = True
                if (
                    _is_retryable_failure(item)
                    and not _is_quota_exhausted(item)
                ):
                    provider = str(item.get("provider") or "novelai")
                    try:
                        item_wait = max(0.0, float(item.get("wait") or 0.0))
                    except (TypeError, ValueError):
                        item_wait = 0.0
                    async with lock:
                        deferred = dict(raw)
                        deferred["_last_transient_failure"] = dict(item)
                        retry_later.append(deferred)
                        retry_providers.add(provider)
                        retry_wait_sec = max(retry_wait_sec, item_wait)
                else:
                    _count_item(job, item)
            finally:
                queue.task_done()

    workers = [
        asyncio.create_task(worker())
        for _ in range(max(1, min(int(concurrency or 1), len(pending))))
    ]
    await asyncio.gather(*workers, return_exceptions=False)

    if quota_exhausted:
        while True:
            try:
                raw = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _count_item(
                job,
                {
                    **_base_item(raw, retry_round),
                    "error": "quota_exhausted",
                    "failure_reason": "quota_exhausted",
                    "message": "quota exhausted; upstream request was not attempted",
                    "request_attempted": False,
                },
            )
            queue.task_done()
    return retry_later, retry_providers, retry_wait_sec, quota_exhausted


def _finish_deferred_as_failed(
    job: GenerationJob,
    pending: list[dict[str, Any]],
    *,
    retry_round: int,
    reason: str,
) -> None:
    for raw in pending:
        last = raw.get("_last_transient_failure")
        last = last if isinstance(last, dict) else {}
        last_message = str(last.get("message") or "temporary provider failure")
        item = _base_item(raw, retry_round)
        item.update(
            error="retry_budget_exhausted",
            failure_reason="retry_budget_exhausted",
            message=f"{reason}; last provider status: {last_message}",
            provider=str(last.get("provider") or ""),
            request_attempted=bool(last.get("request_attempted")),
        )
        _count_item(job, item)


async def _run_batch(
    targets: list[dict[str, Any]],
    recipe: dict[str, Any],
    *,
    force_free: bool = True,
    generate: bool = True,
    preview_only: bool = False,
    job: GenerationJob | None = None,
) -> None:
    job = job or _JOB_MANAGER.get_job()
    if job is None:
        return
    concurrency = 1
    if generate and not preview_only:
        concurrency = max(
            1,
            generation_concurrency_for_batch(
                targets,
                force_free=force_free,
            ),
        )
    _JOB_MANAGER.update_progress(job, concurrency=concurrency)
    pending = list(targets)
    retry_round = 0
    loop = asyncio.get_running_loop()
    retry_budget_sec = _transient_retry_budget_sec(len(targets))
    retry_deadline = loop.time() + retry_budget_sec
    max_retry_cycles = _max_transient_retry_cycles(len(targets))
    try:
        while pending and not job.cancel_requested:
            retry_later, retry_providers, retry_wait_sec, quota_exhausted = await _run_round(
                pending,
                recipe,
                force_free=force_free,
                generate=generate,
                preview_only=preview_only,
                retry_round=retry_round,
                concurrency=concurrency,
                job=job,
            )
            if quota_exhausted or not retry_later or job.cancel_requested:
                break
            retry_round += 1
            remaining_budget = max(0.0, retry_deadline - loop.time())
            if remaining_budget <= 0 or retry_round >= max_retry_cycles:
                reason = (
                    "temporary provider retry time budget exhausted"
                    if remaining_budget <= 0
                    else "temporary provider retry cycle safety limit reached"
                )
                _finish_deferred_as_failed(
                    job,
                    retry_later,
                    retry_round=retry_round,
                    reason=reason,
                )
                break
            # 按被 defer 目标所属 provider 取最大所需等待（NAI 快、闲云慢）
            defer_sec = max(
                (_defer_retry_sec(p) for p in retry_providers),
                default=_NAI_DEFER_RETRY_SEC,
            )
            defer_sec = min(max(defer_sec, retry_wait_sec), remaining_budget)
            _JOB_MANAGER.update_progress(
                job,
                current_phase="defer_retry",
                active=[],
                message=(
                    f"{len(retry_later)} retryable failure(s); retrying in "
                    f"{defer_sec:.1f}s "
                    f"(cycle {retry_round}, budget {int(remaining_budget)}s left)"
                ),
            )
            if await _JOB_MANAGER.wait_or_cancel(job, defer_sec):
                break
            pending = retry_later

        status = _JOB_MANAGER.status(job.task_id) or {}
        if job.cancel_requested:
            _JOB_MANAGER.finish(job, status="cancelled", message="cancelled")
        else:
            fail_count = int(status.get("fail_count") or 0)
            _JOB_MANAGER.finish(
                job,
                status="done",
                message=(
                    f"done: ok {int(status.get('ok_count') or 0)} · "
                    f"failed {fail_count} · "
                    f"skipped {int(status.get('skip_count') or 0)}"
                ),
            )
    except JobPersistenceError as exc:
        status = _JOB_MANAGER.status(job.task_id)
        if status and status.get("status") == "running":
            _JOB_MANAGER.finish(
                job,
                status="unknown",
                message=f"这次可能已扣费，状态未能落盘：{exc}",
            )
            job.state["recovered_after_restart"] = True
    except Exception as exc:
        status = _JOB_MANAGER.status(job.task_id)
        if status and status.get("status") == "running":
            _JOB_MANAGER.finish(job, status="error", message=str(exc))
    finally:
        resume_batch_queue()


def _launch_job(job: GenerationJob) -> None:
    request = job.state.get("_request") or {}
    coroutine = _run_batch(
        list(request.get("targets") or []),
        dict(request.get("recipe") or {}),
        force_free=bool(request.get("force_free", True)),
        generate=bool(request.get("generate", True)),
        preview_only=bool(request.get("preview_only", False)),
        job=job,
    )
    try:
        task = asyncio.create_task(coroutine)
    except Exception:
        coroutine.close()
        raise
    _JOB_MANAGER.attach_task(job, task)


def start_batch(
    targets: list[dict[str, Any]],
    recipe: dict[str, Any],
    *,
    force_free: bool = True,
    generate: bool = True,
    preview_only: bool = False,
    _retry_of: str = "",
) -> dict[str, Any]:
    if not targets:
        return {"ok": False, "error": "empty", "message": "target list is empty"}
    if len(targets) > BATCH_TARGET_MAX:
        return {
            "ok": False,
            "error": "too_many_targets",
            "message": f"single batch limit is {BATCH_TARGET_MAX} works",
        }
    if (
        generate
        and not preview_only
        and generation_concurrency_for_batch(targets, force_free=force_free) <= 0
    ):
        return {
            "ok": False,
            "error": "missing_token",
            "message": "NovelAI token is not configured",
            "batch": batch_status(),
        }

    normalized: list[dict[str, Any]] = []
    paid = bool(generate and not preview_only)
    for index, raw in enumerate(targets):
        item = dict(raw)
        item.setdefault("_target_index", index)
        comment = item.get("patched_comment")
        if paid and isinstance(comment, dict) and comment:
            item["patched_comment"] = copy.deepcopy(comment)
            item["frozen_comment"] = True
        normalized.append(item)
    try:
        job, starts_now = _JOB_MANAGER.enqueue_job(
            total=len(normalized),
            generate=generate,
            preview_only=preview_only,
        )
        _JOB_MANAGER.update(
            job,
            _request={
                "targets": normalized,
                "recipe": dict(recipe or {}),
                "force_free": bool(force_free),
                "generate": bool(generate),
                "preview_only": bool(preview_only),
                "retry_of": str(_retry_of or ""),
            },
            required_persistence=bool(generate and not preview_only),
        )
    except JobPersistenceError as exc:
        return {
            "ok": False,
            "error": "persistence_failed",
            "message": str(exc),
            "batch": batch_status(),
        }

    if starts_now:
        try:
            _launch_job(job)
        except Exception as exc:
            _JOB_MANAGER.finish(job, status="error", message=str(exc))
            return {
                "ok": False,
                "error": "start_failed",
                "message": str(exc),
                "task_id": job.task_id,
                "batch": batch_status(job.task_id),
            }
    return {
        "ok": True,
        "task_id": job.task_id,
        "queued": not starts_now,
        "message": "batch queued" if not starts_now else "batch started",
        "batch": batch_status(job.task_id),
    }


def resume_batch_queue() -> dict[str, Any]:
    try:
        job = _JOB_MANAGER.activate_next()
    except JobPersistenceError as exc:
        return {
            "ok": False,
            "resumed": False,
            "error": "persistence_failed",
            "message": str(exc),
        }
    if job is None:
        return {"ok": True, "resumed": False}
    try:
        _launch_job(job)
    except Exception as exc:
        _JOB_MANAGER.finish(job, status="error", message=str(exc))
        return {
            "ok": False,
            "resumed": False,
            "error": "start_failed",
            "message": str(exc),
        }
    return {"ok": True, "resumed": True, "task_id": job.task_id}


def cancel_batch(task_id: str | None = None) -> dict[str, Any]:
    job = _JOB_MANAGER.request_cancel(task_id)
    if job is None:
        return {
            "ok": False,
            "error": "not_found",
            "message": "generation task not found",
            "batch": batch_status(),
        }
    return {
        "ok": True,
        "message": (
            "cancelling"
            if job.state.get("status") == "running"
            else "cancelled"
        ),
        "batch": batch_status(job.task_id),
    }


def reorder_batch(task_id: str, position: int) -> dict[str, Any]:
    moved = _JOB_MANAGER.reorder_queued(task_id, position)
    if moved is None:
        return {
            "ok": False,
            "error": "not_found",
            "message": "queued task not found",
        }
    return {"ok": True, "batch": moved, **moved}


def retry_batch(task_id: str) -> dict[str, Any]:
    job = _JOB_MANAGER.get_job(task_id)
    if job is None:
        return {
            "ok": False,
            "error": "not_found",
            "message": "generation task not found",
        }
    if str(job.state.get("status") or "") not in TERMINAL_STATUSES:
        return {
            "ok": False,
            "error": "not_retryable",
            "message": "job is still running",
        }
    request = job.state.get("_request")
    if not isinstance(request, dict):
        return {
            "ok": False,
            "error": "not_retryable",
            "message": "generation request is unavailable",
        }
    retryable, blocked = partition_retry_targets(
        list(request.get("targets") or []),
        list(job.state.get("items") or []),
        status=str(job.state.get("status") or ""),
        recovered_after_restart=bool(job.state.get("recovered_after_restart")),
    )
    targets = [
        dict(target)
        for index, target in enumerate(request.get("targets") or [])
        if index in set(retryable)
    ]
    if not targets:
        if blocked:
            return {
                "ok": False,
                "error": "needs_review",
                "message": (
                    "provider outcome may already be billable; review the remote "
                    "gallery before retrying"
                ),
                "blocked_retry_count": len(blocked),
            }
        return {
            "ok": False,
            "error": "nothing_to_retry",
            "message": "no failed or unfinished targets",
        }
    return start_batch(
        targets,
        dict(request.get("recipe") or {}),
        force_free=bool(request.get("force_free", True)),
        generate=bool(request.get("generate", True)),
        preview_only=bool(request.get("preview_only", False)),
        _retry_of=task_id,
    )


STUDIO_COPY_MAX = 8


def start_studio_generate(
    patched_comment: dict[str, Any],
    *,
    work_id: int | None = None,
    page_index: int = 0,
    copies: int = 1,
    source_gallery_id: str = "site",
    seed_policy: str = "",
    force_free: bool = True,
    prompt_profile: str = "native",
    source_title: str = "",
    source_thumb: str = "",
    remote_work_id: str = "",
    token_id: str = "",
) -> dict[str, Any]:
    """Enqueue a click-time snapshot as one durable job (1 copy still a job)."""

    copies = max(1, min(STUDIO_COPY_MAX, int(copies or 1)))
    snapshot = copy.deepcopy(patched_comment if isinstance(patched_comment, dict) else {})
    raw_seed = snapshot.get("seed")
    seed_num: int | None
    try:
        if raw_seed in (None, "", -1, "-1"):
            seed_num = None
        else:
            seed_num = int(raw_seed)
            if seed_num < 0:
                seed_num = None
    except (TypeError, ValueError):
        seed_num = None
    policy = str(seed_policy or "").strip().lower()
    if policy not in {"random", "increment", "fixed"}:
        policy = "random" if seed_num is None else "increment"
    gallery_id = str(source_gallery_id or "site").strip() or "site"
    if gallery_id not in {"site", "aitag-online", "codex", "qqgroup"}:
        gallery_id = "site"
    targets: list[dict[str, Any]] = []
    for index in range(copies):
        comment = copy.deepcopy(snapshot)
        if policy == "random":
            comment["seed"] = -1
        elif policy == "increment" and seed_num is not None:
            comment["seed"] = seed_num + index
        elif policy == "fixed" and seed_num is not None:
            comment["seed"] = seed_num
        comment["_studio_snapshot"] = True
        targets.append(
            {
                "work_id": int(work_id or 0),
                "page_index": int(page_index or 0),
                "gallery_id": gallery_id,
                "patched_comment": comment,
                "frozen_comment": True,
                "source_title": str(source_title or ""),
                "source_thumb": str(source_thumb or ""),
                "remote_work_id": str(remote_work_id or ""),
                "_target_index": index,
            }
        )
    recipe = {
        "prompt_profile": str(prompt_profile or "native"),
        "token_id": str(token_id or ""),
        "kind": "studio_snapshot",
        "seed_policy": policy,
        "copies": copies,
        "retry_policy": "no-5xx-retry",
        "source_gallery_id": gallery_id,
        "page_index": int(page_index or 0),
    }
    started = start_batch(
        targets,
        recipe,
        force_free=force_free,
        generate=True,
        preview_only=False,
    )
    if started.get("ok"):
        started["message"] = (
            "generation queued" if started.get("queued") else "generation started"
        )
    return started
