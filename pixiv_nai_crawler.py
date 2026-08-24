"""Checkpointed, rate-limited Pixiv discovery runner for verified NAI assets."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from atomic_io import atomic_write_text
from db import Database
from pixiv_nai_intake import PixivNAIIntake
from pixiv_nai_source import PixivAPIError, PixivNAISource, PixivSourcePage
from pixiv_browser_source import PixivBrowserSource
from pixiv_public_source import PixivPublicWebSource


ROOT = Path(__file__).resolve().parent
TASK_FILE = "pixiv_nai_task.local.json"
STATE_FILE = "pixiv_nai_state.local.json"
REPORT_FILE = "pixiv_nai_report.local.json"
HEARTBEAT_FILE = "pixiv-nai-intake-heartbeat.json"
REPORT_HISTORY_LIMIT = 20
_SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _data_path(root: Path) -> Path:
    config_path = root / "config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            configured = Path(str(config.get("data_dir") or "data"))
            return configured if configured.is_absolute() else (root / configured).resolve()
        except (OSError, ValueError, TypeError):
            pass
    return (root / "data").resolve()


def _json_path(root: Path, filename: str) -> Path:
    return _data_path(root) / filename


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else dict(default)
    except (OSError, ValueError, TypeError):
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def default_task() -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": False,
        "source_mode": "auto",
        "account_id": "",
        "scopes": [
            {
                "id": "novelai",
                "type": "search",
                "query": "NovelAI",
                "sort": "date_desc",
                "search_target": "partial_match_for_tags",
                "enabled": True,
            }
        ],
        "require_pixiv_ai_generated": True,
        "max_pages_per_run": 3,
        "max_works_per_run": 60,
        "max_download_bytes": 128 * 1024 * 1024,
        "storage_quota_bytes": 0,
        "request_delay_sec": 1.2,
        "proxy_url": "",
        "browser_mode": False,
        "thumbnail_only_pages": True,
        "retry_max": 4,
        "backoff_base_sec": 2.0,
        "work_failure_threshold": 3,
        "watch_interval_sec": 300,
    }


def _bounded_int(value: Any, *, low: int, high: int, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < low or parsed > high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return parsed


def _bounded_float(value: Any, *, low: float, high: float, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if parsed < low or parsed > high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return parsed


def _validate_proxy_url(value: Any) -> str:
    proxy = str(value or "").strip()
    if not proxy:
        return ""
    parsed = urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("proxy_url must be an http(s) proxy URL")
    return proxy


def normalize_task(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = default_task()
    source = dict(payload or {})
    scopes_raw = source.get("scopes", defaults["scopes"])
    if not isinstance(scopes_raw, list) or not scopes_raw:
        raise ValueError("at least one Pixiv discovery scope is required")
    scopes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in scopes_raw:
        if not isinstance(raw, dict):
            raise ValueError("each Pixiv discovery scope must be an object")
        scope = dict(raw)
        scope_id = str(scope.get("id") or "").strip()
        if not _SCOPE_ID_RE.fullmatch(scope_id) or scope_id in seen_ids:
            raise ValueError("Pixiv scope ids must be unique safe identifiers")
        scope_type = str(scope.get("type") or "search").strip().lower()
        if scope_type not in {"search", "user", "ranking"}:
            raise ValueError(f"unsupported Pixiv scope type: {scope_type}")
        normalized: dict[str, Any] = {
            "id": scope_id,
            "type": scope_type,
            "enabled": bool(scope.get("enabled", True)),
        }
        if scope_type == "search":
            query = str(scope.get("query") or "").strip()
            if not query:
                raise ValueError("Pixiv search scope requires query")
            sort = str(scope.get("sort") or "date_desc").strip()
            if sort not in {"date_desc", "popular_desc"}:
                raise ValueError("Pixiv search sort must be date_desc or popular_desc")
            normalized.update(
                query=query,
                sort=sort,
                search_target=str(
                    scope.get("search_target") or "partial_match_for_tags"
                ),
            )
        elif scope_type == "user":
            normalized.update(
                user_id=_bounded_int(
                    scope.get("user_id"), low=1, high=10**15, label="user_id"
                ),
                work_type=str(scope.get("work_type") or "illust"),
            )
        else:
            normalized["mode"] = str(scope.get("mode") or "day")
        scopes.append(normalized)
        seen_ids.add(scope_id)

    source_mode = str(source.get("source_mode", defaults["source_mode"]) or "auto").strip().lower()
    if source_mode not in {"auto", "api", "public"}:
        raise ValueError("source_mode must be auto, api, or public")

    return {
        "version": 1,
        "enabled": bool(source.get("enabled", defaults["enabled"])),
        "source_mode": source_mode,
        "account_id": str(source.get("account_id") or "").strip(),
        "scopes": scopes,
        "require_pixiv_ai_generated": bool(
            source.get(
                "require_pixiv_ai_generated",
                defaults["require_pixiv_ai_generated"],
            )
        ),
        "max_pages_per_run": _bounded_int(
            source.get("max_pages_per_run", defaults["max_pages_per_run"]),
            low=1,
            high=100,
            label="max_pages_per_run",
        ),
        "max_works_per_run": _bounded_int(
            source.get("max_works_per_run", defaults["max_works_per_run"]),
            low=1,
            high=5000,
            label="max_works_per_run",
        ),
        "max_download_bytes": _bounded_int(
            source.get("max_download_bytes", defaults["max_download_bytes"]),
            low=1024,
            high=1024 * 1024 * 1024,
            label="max_download_bytes",
        ),
        "storage_quota_bytes": _bounded_int(
            source.get("storage_quota_bytes", defaults["storage_quota_bytes"]),
            low=0,
            high=10**15,
            label="storage_quota_bytes",
        ),
        "request_delay_sec": _bounded_float(
            source.get("request_delay_sec", defaults["request_delay_sec"]),
            low=0,
            high=60,
            label="request_delay_sec",
        ),
        "proxy_url": _validate_proxy_url(
            source.get("proxy_url", defaults["proxy_url"])
        ),
        "browser_mode": bool(source.get("browser_mode", defaults["browser_mode"])),
        "thumbnail_only_pages": bool(
            source.get("thumbnail_only_pages", defaults["thumbnail_only_pages"])
        ),
        "retry_max": _bounded_int(
            source.get("retry_max", defaults["retry_max"]),
            low=1,
            high=10,
            label="retry_max",
        ),
        "backoff_base_sec": _bounded_float(
            source.get("backoff_base_sec", defaults["backoff_base_sec"]),
            low=0.1,
            high=120,
            label="backoff_base_sec",
        ),
        "work_failure_threshold": _bounded_int(
            source.get(
                "work_failure_threshold",
                defaults["work_failure_threshold"],
            ),
            low=1,
            high=100,
            label="work_failure_threshold",
        ),
        "watch_interval_sec": _bounded_int(
            source.get("watch_interval_sec", defaults["watch_interval_sec"]),
            low=10,
            high=86400,
            label="watch_interval_sec",
        ),
    }


def load_task(*, root: Path = ROOT) -> dict[str, Any]:
    path = _json_path(Path(root), TASK_FILE)
    raw = _read_json(path, default_task())
    try:
        return normalize_task(raw)
    except ValueError:
        return default_task()


def save_task(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    task = normalize_task(payload)
    _write_json(_json_path(Path(root), TASK_FILE), task)
    return task


def _active_pixiv_account_id(configured: str) -> str:
    configured = str(configured or "").strip()
    if configured:
        return configured
    try:
        from pixiv_accounts import get_active_account_id

        return str(get_active_account_id() or "").strip()
    except Exception:
        return ""


def _build_pixiv_source(task: dict[str, Any]) -> tuple[Any, str]:
    """Select the requested source without ever falling back after API auth errors."""

    mode = str(task.get("source_mode") or "auto").strip().lower()
    account_id = _active_pixiv_account_id(str(task.get("account_id") or ""))
    selected = "public" if mode == "public" or (mode == "auto" and not account_id) else "api"
    if selected == "public":
        public_kwargs: dict[str, Any] = {
            "max_download_bytes": int(task["max_download_bytes"]),
            "ai_prefilter": bool(task["require_pixiv_ai_generated"]),
            "request_delay_sec": float(task["request_delay_sec"]),
            "sleep_fn": time.sleep,
            "proxy_url": str(task.get("proxy_url") or ""),
        }
        if bool(task.get("browser_mode")) and PixivBrowserSource.available():
            return PixivBrowserSource(**public_kwargs), "public_browser"
        return PixivPublicWebSource(**public_kwargs), "public"
    # API mode is deliberately conservative: a 0.5s floor on the request
    # interval protects the logged-in account from rate-limit flags even if
    # the task configures no delay (aggressive settings are for the
    # logged-out public channel only).
    return (
        PixivNAISource(
            account_id=account_id or None,
            max_download_bytes=int(task["max_download_bytes"]),
            request_delay_sec=max(0.5, float(task["request_delay_sec"])),
        ),
        selected,
    )


def load_state(*, root: Path = ROOT) -> dict[str, Any]:
    state = _read_json(_json_path(Path(root), STATE_FILE), {"version": 1, "scopes": {}})
    if not isinstance(state.get("scopes"), dict):
        state["scopes"] = {}
    if not isinstance(state.get("failures"), dict):
        state["failures"] = {}
    if not isinstance(state.get("quarantine"), dict):
        state["quarantine"] = {}
    state["version"] = 1
    return state


def _save_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now_iso()
    _write_json(_json_path(root, STATE_FILE), state)


def list_presets() -> list[dict[str, Any]]:
    """Visible Pixiv intake shortcuts for the progress page."""
    base = default_task()
    return [
        {
            "id": "novelai",
            "label": "NovelAI 标签",
            "task": {**base, "enabled": True},
        },
        {
            "id": "arknights",
            "label": "明日方舟",
            "task": {
                **base,
                "enabled": True,
                "scopes": [
                    {
                        "id": "arknights",
                        "type": "search",
                        "query": "アークナイツ",
                        "sort": "date_desc",
                        "search_target": "partial_match_for_tags",
                        "enabled": True,
                    }
                ],
            },
        },
        {
            "id": "probe",
            "label": "试跑 1 页",
            "task": {**base, "enabled": True, "max_pages_per_run": 1, "max_works_per_run": 12},
        },
    ]


def reset_search_progress(*, root: Path = ROOT) -> dict[str, Any]:
    """Clear discovery cursors so the next run starts from the current scopes."""
    state = load_state(root=root)
    scopes = state.get("scopes") or {}
    reset_count = 0
    if isinstance(scopes, dict):
        for scope_state in scopes.values():
            if not isinstance(scope_state, dict):
                continue
            scope_state["cursor"] = ""
            scope_state["offset"] = 0
            reset_count += 1
    _save_state(Path(root), state)
    return {"ok": True, "reset": True, "scopes": reset_count}


def list_quarantined(*, root: Path = ROOT) -> list[dict[str, Any]]:
    """Summarize currently quarantined works without clearing anything."""
    state = load_state(root=root)
    items: list[dict[str, Any]] = []
    for key, record in (state.get("quarantine") or {}).items():
        if isinstance(record, dict):
            items.append(
                {
                    "key": str(key),
                    "reason": str(record.get("reason") or ""),
                    "failure_kind": str(record.get("failure_kind") or ""),
                    "quarantined_at": str(record.get("quarantined_at") or ""),
                }
            )
    return items


def retry_quarantined(*, root: Path = ROOT) -> dict[str, Any]:
    """Clear the quarantine so the next crawl retries those works."""
    state = load_state(root=root)
    items = list_quarantined(root=root)
    state["quarantine"] = {}
    _save_state(root, state)
    return {"cleared": len(items), "items": items}


def get_report(*, root: Path = ROOT) -> dict[str, Any]:
    return _read_json(
        _json_path(Path(root), REPORT_FILE),
        {
            "status": "never_run",
            "source_mode": "",
            "works_seen": 0,
            "accepted_pages": 0,
            "rejected_pages": 0,
            "failed_pages": 0,
            "rejection_reasons": {},
            "failure_kinds": {},
            "history": [],
        },
    )


def _safe_failure_kinds(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, int] = {}
    for kind in ("retryable", "permanent"):
        try:
            count = max(0, int(source.get(kind) or 0))
        except (TypeError, ValueError):
            count = 0
        if count:
            result[kind] = count
    return result


def _safe_error_name(value: Any) -> str:
    name = str(value or "")
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name) else ""


def _write_report(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    public = {
        "status": str(report.get("status") or "unknown"),
        "source_mode": str(report.get("source_mode") or ""),
        "started_at": str(report.get("started_at") or ""),
        "updated_at": _now_iso(),
        "scope_id": str(report.get("scope_id") or ""),
        "works_seen": int(report.get("works_seen") or 0),
        "works_accepted": int(report.get("works_accepted") or 0),
        "works_partial": int(report.get("works_partial") or 0),
        "works_rejected": int(report.get("works_rejected") or 0),
        "works_unchanged": int(report.get("works_unchanged") or 0),
        "works_updated": int(report.get("works_updated") or 0),
        "works_failed": int(report.get("works_failed") or 0),
        "works_quarantined": int(report.get("works_quarantined") or 0),
        "works_recovered": int(report.get("works_recovered") or 0),
        "pages_fetched": int(report.get("pages_fetched") or 0),
        "accepted_pages": int(report.get("accepted_pages") or 0),
        "rejected_pages": int(report.get("rejected_pages") or 0),
        "failed_pages": int(report.get("failed_pages") or 0),
        "rejection_reasons": dict(report.get("rejection_reasons") or {}),
        "failure_kinds": _safe_failure_kinds(report.get("failure_kinds")),
        "last_error": _safe_error_name(report.get("last_error")),
    }
    history: list[dict[str, Any]] = []
    for raw in report.get("history") or []:
        if not isinstance(raw, dict):
            continue
        history.append(
            {
                "status": str(raw.get("status") or "unknown"),
                "source_mode": str(raw.get("source_mode") or ""),
                "started_at": str(raw.get("started_at") or ""),
                "finished_at": str(raw.get("finished_at") or ""),
                "works_seen": int(raw.get("works_seen") or 0),
                "works_accepted": int(raw.get("works_accepted") or 0),
                "works_failed": int(raw.get("works_failed") or 0),
                "works_quarantined": int(raw.get("works_quarantined") or 0),
                "failure_kinds": _safe_failure_kinds(raw.get("failure_kinds")),
                "last_error": _safe_error_name(raw.get("last_error")),
            }
        )
    if public["status"] not in {"starting", "running"} and not report.get(
        "_history_recorded"
    ):
        history.append(
            {
                "status": public["status"],
                "source_mode": public["source_mode"],
                "started_at": public["started_at"],
                "finished_at": public["updated_at"],
                "works_seen": public["works_seen"],
                "works_accepted": public["works_accepted"],
                "works_failed": public["works_failed"],
                "works_quarantined": public["works_quarantined"],
                "failure_kinds": public["failure_kinds"],
                "last_error": public["last_error"],
            }
        )
        report["_history_recorded"] = True
    history = history[-REPORT_HISTORY_LIMIT:]
    report["history"] = history
    public["history"] = history
    _write_json(_json_path(root, REPORT_FILE), public)
    heartbeat = root / "logs" / HEARTBEAT_FILE
    _write_json(
        heartbeat,
        {
            "status": public["status"],
            "updated_at": public["updated_at"],
            "scope_id": public["scope_id"],
            "works_seen": public["works_seen"],
            "accepted_pages": public["accepted_pages"],
            "rejected_pages": public["rejected_pages"],
            "failed_pages": public["failed_pages"],
        },
    )
    return public


def _fetch_with_retry(
    source: PixivNAISource,
    scope: dict[str, Any],
    cursor: str,
    task: dict[str, Any],
    sleep_fn: Callable[[float], None],
) -> PixivSourcePage:
    for attempt in range(int(task["retry_max"])):
        try:
            return source.fetch_page(scope, cursor)
        except PixivAPIError as exc:
            if not exc.retryable or attempt + 1 >= int(task["retry_max"]):
                raise
            backoff = exc.retry_after
            if backoff is None:
                base = float(task["backoff_base_sec"]) * (2**attempt)
                backoff = base + random.uniform(0, min(1.0, base * 0.25))
            sleep_fn(min(300.0, max(0.0, backoff)))
    raise RuntimeError("Pixiv page retry loop exhausted")


def _classify_failed_receipt(source: Any, receipt: Any) -> tuple[str, str]:
    """Recover safe failure semantics hidden behind the intake receipt boundary."""

    classified: list[tuple[str, str]] = []
    consume = getattr(source, "consume_download_failure", None)
    for page in receipt.pages:
        if page.status != "failed":
            continue
        failure = consume(page.original_url) if callable(consume) else None
        if failure is None:
            if str(page.reason or "") == "work_incomplete":
                continue
            classified.append(("retryable", str(page.reason or "download_error")))
            continue
        kind = "permanent" if str(failure.kind) == "permanent" else "retryable"
        reason = str(failure.reason or "download_error")
        if not re.fullmatch(r"[a-z0-9_]{1,64}", reason):
            reason = "download_error"
        classified.append((kind, reason))
    if not classified:
        return "retryable", "work_failed"
    kind = "retryable" if any(item[0] == "retryable" for item in classified) else "permanent"
    reason = next((item[1] for item in classified if item[0] == kind), classified[0][1])
    return kind, reason


def _classify_work_exception(exc: Exception) -> tuple[str, str] | None:
    """Accept only exceptions that explicitly expose safe retry semantics."""

    if not hasattr(exc, "retryable") or not hasattr(exc, "reason"):
        return None
    reason = str(getattr(exc, "reason", "") or "")
    if not re.fullmatch(r"[a-z0-9_]{1,64}", reason):
        return None
    kind = "retryable" if bool(getattr(exc, "retryable", False)) else "permanent"
    return kind, reason


def crawl_once(
    *,
    root: Path = ROOT,
    source: PixivNAISource | None = None,
    intake: PixivNAIIntake | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    root = Path(root).resolve()
    task = load_task(root=root)
    prior_report = get_report(root=root)
    report: dict[str, Any] = {
        "status": "starting",
        "source_mode": "",
        "started_at": _now_iso(),
        "scope_id": "",
        "works_seen": 0,
        "works_accepted": 0,
        "works_partial": 0,
        "works_rejected": 0,
        "works_unchanged": 0,
        "works_updated": 0,
        "works_failed": 0,
        "works_quarantined": 0,
        "works_recovered": 0,
        "pages_fetched": 0,
        "accepted_pages": 0,
        "rejected_pages": 0,
        "failed_pages": 0,
        "rejection_reasons": {},
        "failure_kinds": {},
        "last_error": "",
        "history": list(prior_report.get("history") or []),
    }
    if not task["enabled"]:
        report["status"] = "disabled"
        return _write_report(root, report)

    data = _data_path(root)
    own_db: Database | None = None
    own_source = source is None
    if source is None:
        source, selected_source_mode = _build_pixiv_source(task)
        report["source_mode"] = selected_source_mode
    else:
        report["source_mode"] = "injected"
    if intake is None:
        own_db = Database(data / "aitag.db")
        intake = PixivNAIIntake(
            db=own_db,
            images_dir=data / "images",
            staging_dir=data / "pixiv_nai_staging",
            max_download_bytes=int(task["max_download_bytes"]),
            storage_quota_bytes=int(task["storage_quota_bytes"]),
            thumbnail_only_pages=bool(task["thumbnail_only_pages"]),
        )

    state = load_state(root=root)
    reason_counts: Counter[str] = Counter()
    failure_kind_counts: Counter[str] = Counter()
    report["status"] = "running"
    _write_report(root, report)
    stop_for_budget = False
    try:
        for scope in task["scopes"]:
            if not scope.get("enabled", True):
                continue
            scope_id = str(scope["id"])
            report["scope_id"] = scope_id
            scope_state = state["scopes"].setdefault(
                scope_id, {"cursor": "", "offset": 0}
            )
            cursor = str(scope_state.get("cursor") or "")
            offset = max(0, int(scope_state.get("offset") or 0))
            pages_for_scope = 0
            while pages_for_scope < int(task["max_pages_per_run"]):
                page = _fetch_with_retry(source, scope, cursor, task, sleep_fn)
                pages_for_scope += 1
                report["pages_fetched"] += 1
                if offset > len(page.works):
                    offset = 0
                for index in range(offset, len(page.works)):
                    work = page.works[index]
                    report["works_seen"] += 1
                    scope_state["cursor"] = cursor
                    scope_state["offset"] = index
                    if (
                        task["require_pixiv_ai_generated"]
                        and work.pixiv_ai_type not in {None, 2}
                    ):
                        report["works_rejected"] += 1
                        reason_counts["pixiv_not_marked_ai"] += len(work.pages)
                    else:
                        active_quarantine_keys = [
                            key
                            for key, item in state["quarantine"].items()
                            if isinstance(item, dict)
                            and int(item.get("work_id") or 0) == work.work_id
                        ]
                        work_failure: tuple[str, str] | None = None
                        receipt = None
                        try:
                            receipt = intake.ingest_work(
                                work,
                                source.download_original,
                            )
                        except Exception as exc:
                            work_failure = _classify_work_exception(exc)
                            if work_failure is not None:
                                report["works_failed"] += 1
                                report["rejected_pages"] += len(work.pages)
                                report["failed_pages"] += len(work.pages)
                                report["last_error"] = type(exc).__name__
                                reason_counts[work_failure[1]] += len(work.pages)
                            else:
                                report["works_failed"] += 1
                                report["last_error"] = type(exc).__name__
                                report["status"] = "failed"
                                report["rejection_reasons"] = dict(reason_counts)
                                _save_state(root, state)
                                return _write_report(root, report)
                        if receipt is not None:
                            status_key = f"works_{receipt.status}"
                            if status_key in report:
                                report[status_key] += 1
                            report["accepted_pages"] += receipt.accepted_pages
                            report["rejected_pages"] += receipt.rejected_pages
                            for page_receipt in receipt.pages:
                                if page_receipt.status == "failed":
                                    report["failed_pages"] += 1
                                if page_receipt.status != "accepted":
                                    reason_counts[page_receipt.reason] += 1
                        if receipt is not None and receipt.status != "failed":
                            if active_quarantine_keys:
                                report["works_recovered"] += 1
                            for key in active_quarantine_keys:
                                state["quarantine"].pop(key, None)
                            stale_failures = [
                                key
                                for key, item in state["failures"].items()
                                if isinstance(item, dict)
                                and int(item.get("work_id") or 0) == work.work_id
                            ]
                            for key in stale_failures:
                                state["failures"].pop(key, None)
                        if work_failure is not None or (
                            receipt is not None and receipt.status == "failed"
                        ):
                            if work_failure is not None:
                                failure_kind, failure_reason = work_failure
                            else:
                                failure_kind, failure_reason = _classify_failed_receipt(
                                    source, receipt
                                )
                            failure_kind_counts[failure_kind] += 1
                            report["failure_kinds"] = dict(failure_kind_counts)
                            failure_key = f"{scope_id}:{work.work_id}"
                            if active_quarantine_keys:
                                for key in active_quarantine_keys:
                                    active = dict(state["quarantine"].get(key) or {})
                                    active["failure_count"] = (
                                        int(active.get("failure_count") or 0) + 1
                                    )
                                    active["failure_kind"] = failure_kind
                                    active["reason"] = failure_reason
                                    active["last_failed_at"] = _now_iso()
                                    state["quarantine"][key] = active
                                state["failures"].pop(failure_key, None)
                            else:
                                prior_failure = state["failures"].get(failure_key)
                                prior_count = (
                                    int(prior_failure.get("count") or 0)
                                    if isinstance(prior_failure, dict)
                                    else 0
                                )
                                failure_count = prior_count + 1
                                state["failures"][failure_key] = {
                                    "scope_id": scope_id,
                                    "work_id": work.work_id,
                                    "count": failure_count,
                                    "failure_kind": failure_kind,
                                    "reason": failure_reason,
                                    "updated_at": _now_iso(),
                                }
                                failure_threshold = (
                                    1
                                    if failure_kind == "permanent"
                                    else int(task["work_failure_threshold"])
                                )
                                if failure_count < failure_threshold:
                                    report["status"] = "failed"
                                    report["rejection_reasons"] = dict(reason_counts)
                                    _save_state(root, state)
                                    return _write_report(root, report)
                                state["quarantine"][failure_key] = {
                                    "scope_id": scope_id,
                                    "work_id": work.work_id,
                                    "failure_count": failure_count,
                                    "failure_kind": failure_kind,
                                    "reason": failure_reason,
                                    "quarantined_at": _now_iso(),
                                }
                                state["failures"].pop(failure_key, None)
                                report["works_quarantined"] += 1
                    scope_state["offset"] = index + 1
                    report["rejection_reasons"] = dict(reason_counts)
                    _save_state(root, state)
                    _write_report(root, report)
                    if report["works_seen"] >= int(task["max_works_per_run"]):
                        if index + 1 >= len(page.works):
                            scope_state["cursor"] = page.next_cursor
                            scope_state["offset"] = 0
                            _save_state(root, state)
                        stop_for_budget = True
                        break
                    delay = float(task["request_delay_sec"])
                    if delay:
                        sleep_fn(delay)
                if stop_for_budget:
                    break
                scope_state["cursor"] = page.next_cursor
                scope_state["offset"] = 0
                _save_state(root, state)
                if not page.next_cursor:
                    break
                if page.next_cursor == cursor:
                    report["status"] = "source_loop"
                    break
                cursor = page.next_cursor
                offset = 0
            if stop_for_budget:
                break
        if report["status"] != "source_loop":
            report["status"] = "budget_reached" if stop_for_budget else "completed"
        report["rejection_reasons"] = dict(reason_counts)
        return _write_report(root, report)
    except Exception as exc:
        report["status"] = "failed"
        report["last_error"] = type(exc).__name__
        report["rejection_reasons"] = dict(reason_counts)
        if isinstance(exc, PixivAPIError):
            failure_kind_counts[
                "retryable" if exc.retryable else "permanent"
            ] += 1
        report["failure_kinds"] = dict(failure_kind_counts)
        _save_state(root, state)
        return _write_report(root, report)
    finally:
        if own_db is not None:
            own_db.close()
        if own_source:
            source.close()


def watch(*, root: Path = ROOT) -> None:
    while True:
        task = load_task(root=root)
        crawl_once(root=root)
        time.sleep(int(task["watch_interval_sec"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pixiv -> verified NovelAI gallery")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    from crawler_control import (
        CrawlerFileLock,
        CrawlerLockHeld,
        pixiv_crawler_lock_path,
    )
    from gallery_snapshot import maintenance_mode_active

    data = _data_path(ROOT)
    if maintenance_mode_active(data):
        print(
            json.dumps(
                {
                    "status": "maintenance",
                    "detail": "gallery maintenance in progress; crawler refused to start",
                },
                ensure_ascii=False,
            )
        )
        return 0
    lock = CrawlerFileLock(pixiv_crawler_lock_path(ROOT))
    try:
        lock.acquire()
    except CrawlerLockHeld as exc:
        print(
            json.dumps(
                {"status": "already_running", "pid": exc.pid},
                ensure_ascii=False,
            )
        )
        return 0
    try:
        if args.watch:
            watch(root=ROOT)
        else:
            result = crawl_once(root=ROOT)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
