"""Thread-safe ownership and lifecycle primitives for background generation jobs."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = frozenset({"done", "cancelled", "error", "unknown"})
_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCKS: dict[str, threading.RLock] = {}


def partition_retry_targets(
    targets: list[Any],
    items: list[Any],
    *,
    status: str,
    recovered_after_restart: bool = False,
    require_retry_safe: bool = False,
) -> tuple[list[int], list[int]]:
    """Split target indexes into retryable vs blocked-for-review.

    Crash-recovered ``unknown`` jobs and in-flight targets with no item row
    must not be treated as "never attempted". Director jobs also require an
    explicit ``retry_safe`` flag before a failed item can be retried.
    """

    retryable: list[int] = []
    blocked: list[int] = []
    terminal = str(status or "")
    recovered = bool(recovered_after_restart) or terminal == "unknown"
    items_by_index: dict[int, dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict) or item.get("target_index") is None:
            continue
        items_by_index[int(item["target_index"])] = item
    for index, _target in enumerate(targets or []):
        item = items_by_index.get(index)
        if item and (item.get("ok") or item.get("skipped")):
            continue
        if recovered:
            blocked.append(index)
            continue
        if item is None:
            if terminal == "cancelled" or (
                terminal == "done" and not require_retry_safe
            ):
                retryable.append(index)
            else:
                blocked.append(index)
            continue
        uncertain = bool(item.get("billing_uncertain")) and item.get("retry_safe") is not True
        if uncertain or (require_retry_safe and item.get("retry_safe") is not True):
            blocked.append(index)
        else:
            retryable.append(index)
    return retryable, blocked


def _state_lock(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False)).casefold()
    with _STATE_LOCKS_GUARD:
        return _STATE_LOCKS.setdefault(key, threading.RLock())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _idle_status() -> dict[str, Any]:
    return {
        "id": "",
        "task_id": "",
        "status": "idle",
        "terminal": False,
        "cancel_requested": False,
        "message": "idle",
        "total": 0,
        "done": 0,
        "ok_count": 0,
        "fail_count": 0,
        "skip_count": 0,
        "current_work_id": None,
        "current_page_index": None,
        "current_phase": "",
        "active": [],
        "concurrency": 1,
        "generate": True,
        "preview_only": False,
        "started_at": "",
        "finished_at": "",
        "items": [],
        "progress": {"done": 0, "total": 0, "percent": 0.0},
    }


@dataclass(slots=True)
class GenerationJob:
    """A single job's state, cancellation signal, and owning asyncio task."""

    task_id: str
    state: dict[str, Any]
    cancel_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[None] | None = None

    @property
    def cancel_requested(self) -> bool:
        return self.cancel_event.is_set()


class JobAlreadyRunning(RuntimeError):
    """Raised when the manager's single active-job slot is already owned."""

    def __init__(self, status: dict[str, Any]) -> None:
        super().__init__("generation job already running")
        self.status = status


class JobPersistenceError(RuntimeError):
    """Raised before a paid job when durable state cannot be guaranteed."""

    def __init__(self, message: str = "generation job state could not be persisted") -> None:
        super().__init__(message)


class GenerationJobManager:
    """Own generation jobs and atomically arbitrate the single active slot.

    The manager is deliberately framework-neutral: a LangGraph node can retain a
    ``task_id`` in graph state and call ``status``/``request_cancel`` without
    relying on module-global mutable dictionaries.
    """

    def __init__(
        self,
        *,
        max_history: int = 32,
        cancel_poll_interval: float = 0.05,
        state_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, GenerationJob] = {}
        self._order: list[str] = []
        self._active_task_id: str | None = None
        self._max_history = max(1, int(max_history))
        self._cancel_poll_interval = max(0.005, float(cancel_poll_interval))
        self._state_path = Path(state_path) if state_path else None
        self._condition = threading.Condition(self._lock)
        self._revision = 0
        self._persistence_error = ""
        self._restore_blocked = False
        with self._lock:
            self._restore_locked()

    def start_job(
        self,
        *,
        total: int,
        generate: bool,
        preview_only: bool,
    ) -> GenerationJob:
        """Atomically claim the active slot and create a stable job identity."""

        with self._lock:
            if bool(generate and not preview_only) and self._restore_blocked:
                raise JobPersistenceError(
                    "generation job history is corrupt; restart after resolving the quarantined state file"
                )
            active = self._active_job_locked()
            if active is not None and active.state.get("status") == "running":
                raise JobAlreadyRunning(self._snapshot_locked(active))

            task_id = uuid.uuid4().hex
            state = _idle_status()
            state.update(
                {
                    "id": task_id,
                    "task_id": task_id,
                    "status": "running",
                    "message": "preparing",
                    "total": max(0, int(total)),
                    "generate": bool(generate and not preview_only),
                    "preview_only": bool(preview_only),
                    "current_phase": "init",
                    "started_at": _now(),
                }
            )
            job = GenerationJob(task_id=task_id, state=state)
            self._jobs[task_id] = job
            self._order.append(task_id)
            self._active_task_id = task_id
            self._prune_locked()
            try:
                self._persist_locked(required=bool(generate and not preview_only))
            except JobPersistenceError:
                self._jobs.pop(task_id, None)
                self._order = [item for item in self._order if item != task_id]
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._notify_locked()
                raise
            self._notify_locked()
            return job

    def enqueue_job(
        self,
        *,
        total: int,
        generate: bool,
        preview_only: bool,
    ) -> tuple[GenerationJob, bool]:
        """Create a job, running immediately only when the active slot is free."""

        with self._lock:
            paid = bool(generate and not preview_only)
            if paid and self._restore_blocked:
                raise JobPersistenceError(
                    "generation job history is corrupt; restart after resolving the quarantined state file"
                )
            active = self._active_job_locked()
            has_queued = any(
                self._jobs[task_id].state.get("status") == "queued"
                for task_id in self._order
                if task_id in self._jobs
            )
            starts_now = (
                (active is None or active.state.get("status") != "running")
                and not has_queued
            )
            task_id = uuid.uuid4().hex
            state = _idle_status()
            state.update(
                {
                    "id": task_id,
                    "task_id": task_id,
                    "status": "running" if starts_now else "queued",
                    "message": "preparing" if starts_now else "waiting in batch queue",
                    "total": max(0, int(total)),
                    "generate": paid,
                    "preview_only": bool(preview_only),
                    "current_phase": "init" if starts_now else "queued",
                    "started_at": _now() if starts_now else "",
                    "queued_at": _now(),
                }
            )
            job = GenerationJob(task_id=task_id, state=state)
            self._jobs[task_id] = job
            self._order.append(task_id)
            if starts_now:
                self._active_task_id = task_id
            self._prune_locked()
            try:
                self._persist_locked(required=paid)
            except JobPersistenceError:
                self._jobs.pop(task_id, None)
                self._order = [item for item in self._order if item != task_id]
                if self._active_task_id == task_id:
                    self._active_task_id = None
                self._notify_locked()
                raise
            self._notify_locked()
            return job, starts_now

    def activate_next(self) -> GenerationJob | None:
        """Atomically promote the first queued job into the active slot."""

        with self._lock:
            active = self._active_job_locked()
            if active is not None and active.state.get("status") == "running":
                return None
            self._active_task_id = None
            for task_id in self._order:
                job = self._jobs.get(task_id)
                if job is None or job.state.get("status") != "queued":
                    continue
                job.state.update(
                    {
                        "status": "running",
                        "message": "preparing",
                        "current_phase": "init",
                        "started_at": _now(),
                    }
                )
                self._active_task_id = task_id
                try:
                    self._persist_locked(required=bool(job.state.get("generate")))
                except JobPersistenceError:
                    job.state.update(
                        {
                            "status": "queued",
                            "message": "waiting in batch queue",
                            "current_phase": "queued",
                            "started_at": "",
                        }
                    )
                    self._active_task_id = None
                    raise
                self._notify_locked()
                return job
            return None

    def queue_status(self) -> dict[str, Any]:
        with self._lock:
            active = self._active_job_locked()
            pending = [
                self._snapshot_locked(self._jobs[task_id])
                for task_id in self._order
                if task_id in self._jobs
                and self._jobs[task_id].state.get("status") == "queued"
            ]
            return {
                "active": self._snapshot_locked(active) if active is not None else None,
                "pending": pending,
                "pending_count": len(pending),
            }

    def reorder_queued(self, task_id: str, position: int) -> dict[str, Any] | None:
        """Move one queued job to a zero-based position among queued jobs."""

        with self._lock:
            job = self._jobs.get(str(task_id or ""))
            if job is None or job.state.get("status") != "queued":
                return None
            queued_slots = [
                index
                for index, item_id in enumerate(self._order)
                if item_id in self._jobs
                and self._jobs[item_id].state.get("status") == "queued"
            ]
            queued_ids = [self._order[index] for index in queued_slots]
            queued_ids.remove(job.task_id)
            target = max(0, min(int(position), len(queued_ids)))
            queued_ids.insert(target, job.task_id)
            for index, queued_id in zip(queued_slots, queued_ids):
                self._order[index] = queued_id
            self._persist_locked()
            self._notify_locked()
            return self._snapshot_locked(job)

    def attach_task(self, job: GenerationJob, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._require_owned_locked(job)
            job.task = task

    def get_job(self, task_id: str | None = None) -> GenerationJob | None:
        with self._lock:
            if task_id:
                return self._jobs.get(task_id)
            active = self._active_job_locked()
            if active is not None:
                return active
            if not self._order:
                return None
            return self._jobs.get(self._order[-1])

    def status(self, task_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(task_id) if task_id else self.get_job()
            if job is None:
                if task_id:
                    return None
                snapshot = _idle_status()
                snapshot.update(self._persistence_status_locked())
                return snapshot
            return self._snapshot_locked(job)

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def wait_for_change(self, revision: int, timeout: float | None = None) -> int:
        with self._condition:
            if self._revision <= int(revision):
                self._condition.wait(timeout=timeout)
            return self._revision

    def update(
        self,
        job: GenerationJob,
        *,
        required_persistence: bool = False,
        **changes: Any,
    ) -> None:
        with self._lock:
            self._require_owned_locked(job)
            job.state.update(changes)
            self._persist_locked(required=required_persistence)
            self._notify_locked()

    def update_progress(self, job: GenerationJob, **changes: Any) -> None:
        """Publish transient progress without serializing the full job history.

        Durable boundaries (start, accepted request, appended result and finish)
        still use ``update``/``append_item``/``finish``.  Progress polling can be
        much more frequent and must not block provider workers on disk I/O.
        """
        with self._lock:
            self._require_owned_locked(job)
            job.state.update(changes)
            self._notify_locked()

    def increment(self, job: GenerationJob, key: str, amount: int = 1) -> None:
        with self._lock:
            self._require_owned_locked(job)
            job.state[key] = int(job.state.get(key) or 0) + amount
            self._persist_locked()
            self._notify_locked()

    def increment_progress(self, job: GenerationJob, key: str, amount: int = 1) -> None:
        with self._lock:
            self._require_owned_locked(job)
            job.state[key] = int(job.state.get(key) or 0) + amount
            self._notify_locked()

    def append_item(
        self,
        job: GenerationJob,
        item: dict[str, Any],
        *,
        count_done: bool,
    ) -> None:
        with self._lock:
            self._require_owned_locked(job)
            job.state["items"].append(copy.deepcopy(item))
            if count_done:
                job.state["done"] = int(job.state.get("done") or 0) + 1
            paid = bool(job.state.get("generate")) and not bool(
                job.state.get("preview_only")
            )
            self._persist_locked(required=paid)
            self._notify_locked()

    def request_cancel(self, task_id: str | None = None) -> GenerationJob | None:
        """Signal only the addressed job; never spill cancellation to its successor."""

        with self._lock:
            if task_id:
                job = self._jobs.get(task_id)
            else:
                job = self._active_job_locked()
            if job is None:
                return None
            if job.state.get("status") == "running":
                job.cancel_event.set()
                job.state["message"] = "cancelling"
                self._persist_locked()
                self._notify_locked()
            elif job.state.get("status") == "queued":
                job.state.update(
                    {
                        "status": "cancelled",
                        "message": "cancelled before starting",
                        "current_phase": "",
                        "finished_at": _now(),
                    }
                )
                self._persist_locked()
                self._notify_locked()
            return job

    async def wait_or_cancel(self, job: GenerationJob, delay: float) -> bool:
        """Wait for a delay, returning early when this job is cancelled."""

        if job.cancel_requested:
            return True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(delay))
        while not job.cancel_requested:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(self._cancel_poll_interval, remaining))
        return True

    def finish(
        self,
        job: GenerationJob,
        *,
        status: str,
        message: str,
        **changes: Any,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        with self._lock:
            self._require_owned_locked(job)
            job.state.update(changes)
            job.state.update(
                {
                    "status": status,
                    "message": message,
                    "current_work_id": None,
                    "current_page_index": None,
                    "current_phase": "",
                    "active": [],
                    "finished_at": _now(),
                }
            )
            if status == "done":
                job.state["done"] = int(job.state.get("total") or job.state.get("done") or 0)
            if self._active_task_id == job.task_id:
                self._active_task_id = None
            paid = bool(job.state.get("generate")) and not bool(
                job.state.get("preview_only")
            )
            self._persist_locked(required=paid)
            self._notify_locked()

    def _active_job_locked(self) -> GenerationJob | None:
        if self._active_task_id is None:
            return None
        return self._jobs.get(self._active_task_id)

    def _require_owned_locked(self, job: GenerationJob) -> None:
        if self._jobs.get(job.task_id) is not job:
            raise KeyError(f"job is not owned by this manager: {job.task_id}")

    def _snapshot_locked(self, job: GenerationJob) -> dict[str, Any]:
        snapshot = copy.deepcopy(job.state)
        request = snapshot.pop("_request", None)
        items = list(snapshot.get("items") or [])
        snapshot["items"] = sorted(
            items,
            key=lambda item: (
                item.get("target_index") is None if isinstance(item, dict) else True,
                int(item.get("target_index") or 0) if isinstance(item, dict) else 0,
            ),
        )
        done = int(snapshot.get("done") or 0)
        total = int(snapshot.get("total") or 0)
        percent = round((done / total) * 100.0, 1) if total else 0.0
        retryable_count = 0
        blocked_retry_count = 0
        deferred_unattempted_count = sum(
            1
            for item in items
            if isinstance(item, dict)
            and str(item.get("error") or "").lower() in {"busy", "cooldown"}
        )
        effective_fail_count = max(
            0,
            int(snapshot.get("fail_count") or 0) - deferred_unattempted_count,
        )
        if isinstance(request, dict) and snapshot.get("status") in TERMINAL_STATUSES:
            retryable_indexes, blocked_indexes = partition_retry_targets(
                list(request.get("targets") or []),
                list(snapshot.get("items") or []),
                status=str(snapshot.get("status") or ""),
                recovered_after_restart=bool(snapshot.get("recovered_after_restart")),
            )
            retryable_count = len(retryable_indexes)
            blocked_retry_count = len(blocked_indexes)
        snapshot.update(
            {
                "id": job.task_id,
                "task_id": job.task_id,
                "cancel_requested": job.cancel_requested,
                "terminal": snapshot.get("status") in TERMINAL_STATUSES,
                "progress": {"done": done, "total": total, "percent": percent},
                "retryable_count": retryable_count,
                "can_retry": retryable_count > 0,
                "blocked_retry_count": blocked_retry_count,
                "needs_review": blocked_retry_count > 0,
                "deferred_unattempted_count": deferred_unattempted_count,
                "effective_fail_count": effective_fail_count,
                "queue_position": self._queue_position_locked(job.task_id),
                **self._persistence_status_locked(),
            }
        )
        return snapshot

    def _queue_position_locked(self, task_id: str) -> int:
        position = 0
        for item_id in self._order:
            item = self._jobs.get(item_id)
            if item is None or item.state.get("status") != "queued":
                continue
            position += 1
            if item_id == task_id:
                return position
        return 0

    def _persistence_status_locked(self) -> dict[str, Any]:
        return {
            "revision": self._revision,
            "persistence_degraded": bool(self._persistence_error),
            "persistence_error": self._persistence_error,
            "restore_blocked": self._restore_blocked,
        }

    def _notify_locked(self) -> None:
        self._revision += 1
        self._condition.notify_all()

    def _prune_locked(self) -> None:
        while len(self._order) > self._max_history:
            removable_index = next(
                (
                    index
                    for index, task_id in enumerate(self._order)
                    if task_id != self._active_task_id
                    and self._jobs.get(task_id) is not None
                    and self._jobs[task_id].state.get("status") in TERMINAL_STATUSES
                ),
                None,
            )
            if removable_index is None:
                return
            task_id = self._order.pop(removable_index)
            self._jobs.pop(task_id, None)

    def _restore_locked(self) -> None:
        if self._state_path is None or not self._state_path.is_file():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._persistence_error = f"state restore failed: {type(exc).__name__}"
            self._restore_blocked = True
            try:
                quarantine = self._state_path.with_suffix(
                    self._state_path.suffix + f".corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
                self._state_path.replace(quarantine)
            except OSError:
                pass
            return
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            self._persistence_error = "state restore failed: invalid jobs payload"
            self._restore_blocked = True
            return
        recovered_running = False
        for state in rows[-self._max_history :]:
            if not isinstance(state, dict):
                continue
            task_id = str(state.get("task_id") or state.get("id") or "").strip()
            if not task_id or task_id in self._jobs:
                continue
            restored_state = copy.deepcopy(state)
            restored_state["id"] = task_id
            restored_state["task_id"] = task_id
            if restored_state.get("status") == "running":
                restored_state.update(
                    {
                        "status": "unknown",
                        "message": "这次可能已扣费，不要自动重试；要重出请再确认。",
                        "recovered_after_restart": True,
                        "current_work_id": None,
                        "current_page_index": None,
                        "current_phase": "",
                        "active": [],
                        "finished_at": _now(),
                    }
                )
                recovered_running = True
            elif restored_state.get("status") == "queued":
                # Never sent to the provider. Keep them from blocking the
                # post-restart queue forever — nothing calls activate_next()
                # until an in-process job finishes.
                restored_state.update(
                    {
                        "status": "cancelled",
                        "message": "进程重启，未发出的排队任务已取消。",
                        "current_work_id": None,
                        "current_page_index": None,
                        "current_phase": "",
                        "active": [],
                        "finished_at": _now(),
                    }
                )
                recovered_running = True
            job = GenerationJob(task_id=task_id, state=restored_state)
            self._jobs[task_id] = job
            self._order.append(task_id)
        if recovered_running:
            self._persist_locked()
        self._notify_locked()

    def _persist_locked(self, *, required: bool = False) -> bool:
        if self._state_path is None:
            return True
        local_jobs = [
            copy.deepcopy(self._jobs[task_id].state)
            for task_id in self._order
            if task_id in self._jobs
        ]
        try:
            with _state_lock(self._state_path):
                merged: dict[str, dict[str, Any]] = {}
                if self._state_path.is_file():
                    try:
                        existing = json.loads(
                            self._state_path.read_text(encoding="utf-8")
                        )
                        rows = existing.get("jobs") if isinstance(existing, dict) else []
                        for state in rows if isinstance(rows, list) else []:
                            if not isinstance(state, dict):
                                continue
                            task_id = str(
                                state.get("task_id") or state.get("id") or ""
                            ).strip()
                            if task_id:
                                merged[task_id] = state
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
                for state in local_jobs:
                    task_id = str(
                        state.get("task_id") or state.get("id") or ""
                    ).strip()
                    if task_id:
                        merged[task_id] = state
                payload = {
                    "version": 1,
                    "saved_at": _now(),
                    "jobs": list(merged.values())[-self._max_history :],
                }
                self._state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self._state_path.with_suffix(
                    self._state_path.suffix + f".{uuid.uuid4().hex}.tmp"
                )
                try:
                    temp_path.write_text(
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    temp_path.replace(self._state_path)
                finally:
                    temp_path.unlink(missing_ok=True)
            self._persistence_error = ""
            return True
        except (OSError, TypeError, ValueError) as exc:
            self._persistence_error = f"state save failed: {type(exc).__name__}"
            if required:
                raise JobPersistenceError(self._persistence_error) from exc
            return False
