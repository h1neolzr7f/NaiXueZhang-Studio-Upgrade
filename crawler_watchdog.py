"""图库服务内置爬虫守护：可开关，任务完成后可自动关闭。"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from crawler_control import (
    crawler_running,
    list_supervisor_pids,
    restart_crawler,
    start_crawler,
)
from db import Database
from paths import data_dir

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DONE_FILE = ROOT / "logs" / "COMPLETED.txt"
LOG_FILE = ROOT / "logs" / "crawler-watchdog.log"
DB_PATH: Path | None = None


def _db_path() -> Path:
    return Path(DB_PATH) if DB_PATH is not None else data_dir() / "aitag.db"


_WORK_REMAINING_TTL_SEC = 60.0
_DEFAULT_WATCHDOG_INTERVAL_SEC = 60.0
_MIN_WATCHDOG_INTERVAL_SEC = 60.0
_HEARTBEAT_FILE = ROOT / "logs" / "crawler-heartbeat.json"
_CRAWLER_STALE_SEC = 180.0


def _log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _read_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_config_flag(key: str, value) -> None:
    cfg = _read_config()
    cfg[key] = value
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _crawler_phase() -> str:
    cfg = _read_config()
    phase = str(cfg.get("crawler_phase", "all")).strip() or "all"
    return phase if phase in {"all", "search", "detail", "preview"} else "all"


def _arknights_only(config: dict) -> bool:
    query = str(config.get("search_query", ""))
    low = query.lower()
    return "明日方舟" in query or "arknights" in low or "アークナイツ" in query


def crawl_work_snapshot() -> dict[str, object]:
    config = _read_config()
    phase = _crawler_phase()
    max_attempts = max(1, int(config.get("preview_max_attempts", 6) or 6))
    detail_ark = _arknights_only(config)
    preview_ark = False if config.get("preview_all_local", False) else detail_ark

    snapshot: dict[str, object] = {
        "phase": phase,
        "search_done": False,
        "works": 0,
        "details": 0,
        "covers": 0,
        "detail_pending": 0,
        "preview_pending": 0,
        "preview_exhausted": 0,
        "work_remaining": True,
        "done_file": DONE_FILE.exists(),
    }
    try:
        db = Database(_db_path())
        conn = db.conn
        states = dict(conn.execute("SELECT key, value FROM crawl_state"))
        works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        details = conn.execute(
            "SELECT COUNT(*) FROM works WHERE detail_json IS NOT NULL"
        ).fetchone()[0]
        previews = conn.execute(
            "SELECT COUNT(*) FROM works WHERE preview_downloaded = 1"
        ).fetchone()[0]
        detail_pending = db.count_pending_details(arknights_only=detail_ark)
        preview_pending = db.count_pending_previews(
            arknights_only=preview_ark, max_attempts=max_attempts
        )
        preview_exhausted = db.count_exhausted_previews(
            arknights_only=preview_ark, max_attempts=max_attempts
        )
        conn.close()
    except Exception as exc:
        snapshot["message"] = f"状态读取失败，保守认为仍需守护: {exc}"
        return snapshot

    search_done = states.get("search_done") == "1"
    if phase == "search":
        remaining = not search_done
    elif phase == "detail":
        remaining = works <= 0 or detail_pending > 0
    elif phase == "preview":
        remaining = works <= 0 or preview_pending > 0
    else:
        remaining = works <= 0 or not search_done or detail_pending > 0 or preview_pending > 0

    snapshot.update(
        {
            "search_done": search_done,
            "works": works,
            "details": details,
            "covers": previews,
            "detail_pending": detail_pending,
            "preview_pending": preview_pending,
            "preview_exhausted": preview_exhausted,
            "work_remaining": remaining,
        }
    )
    if not remaining and works > 0 and not DONE_FILE.exists():
        DONE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DONE_FILE.write_text(
            f"{datetime.now().isoformat(timespec='seconds')} phase={phase} "
            f"detail_pending={detail_pending} preview_pending={preview_pending}\n",
            encoding="utf-8",
        )
    return snapshot


def crawl_work_remaining() -> bool:
    return bool(crawl_work_snapshot().get("work_remaining"))


def crawler_delivery_report() -> dict[str, object]:
    snapshot = crawl_work_snapshot()
    exhausted = int(snapshot.get("preview_exhausted") or 0)
    pending = int(snapshot.get("detail_pending") or 0) + int(
        snapshot.get("preview_pending") or 0
    )
    complete = (
        bool(snapshot.get("search_done"))
        and not bool(snapshot.get("work_remaining"))
        and pending == 0
    )
    passed = complete and exhausted == 0
    verdict = "passed" if passed else (
        "needs_attention" if complete and exhausted else "running"
    )
    return {
        "ok": True,
        "verdict": verdict,
        "quality": {
            "passed": passed,
            "preview_exhausted": exhausted,
            "pending": pending,
        },
        "work": snapshot,
    }


def _read_heartbeat() -> dict:
    if not _HEARTBEAT_FILE.exists():
        return {}
    try:
        data = json.loads(_HEARTBEAT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _heartbeat_age_sec() -> float | None:
    updated = str(_read_heartbeat().get("updated_at") or "").strip()
    if not updated:
        return None
    try:
        dt = datetime.fromisoformat(updated)
        return max(0.0, (datetime.now() - dt).total_seconds())
    except Exception:
        return None


def _crawler_looks_dead(*, stale_sec: float = _CRAWLER_STALE_SEC) -> bool:
    if crawler_running():
        return False
    heartbeat = _read_heartbeat()
    status = str(heartbeat.get("status") or "").lower()
    if status in ("complete", "idle", "paused", "waiting", "sleeping"):
        return False
    if status == "crashed":
        return True
    age = _heartbeat_age_sec()
    if age is None:
        return False
    if not crawl_work_remaining():
        return False
    return age > stale_sec


def ensure_crawler_running(*, reason: str = "watchdog") -> dict[str, object]:
    if not crawl_work_remaining():
        return {
            "action": "complete",
            "crawler_running": crawler_running(),
            "message": "爬取已完成，守护不启动爬虫",
        }

    if crawler_running():
        heartbeat = _read_heartbeat()
        heartbeat_status = str(heartbeat.get("status") or "").lower()
        heartbeat_age = _heartbeat_age_sec()
        if (
            heartbeat_status not in {"complete", "idle", "paused", "waiting", "sleeping"}
            and heartbeat_age is not None
            and heartbeat_age > _CRAWLER_STALE_SEC
        ):
            try:
                restarted = restart_crawler(wait_sec=1.0)
            except ValueError as exc:
                _log(f"stale restart blocked reason={reason} error={exc}")
                return {
                    "action": "blocked",
                    "crawler_running": False,
                    "message": str(exc),
                }
            return {
                "action": "restarted",
                "crawler_running": bool(restarted.get("crawler_running")),
                "restarted": restarted,
                "message": "crawler heartbeat was stale and has been restarted",
            }
        return {
            "action": "running",
            "crawler_running": True,
            "message": "爬虫已在运行",
        }

    if list_supervisor_pids():
        if not _crawler_looks_dead():
            return {
                "action": "supervisor",
                "crawler_running": False,
                "message": "监督进程在跑，等待其拉起爬虫",
            }
        try:
            restarted = restart_crawler(wait_sec=1.0)
        except ValueError as exc:
            _log(f"force-restart blocked reason={reason} error={exc}")
            return {
                "action": "blocked",
                "crawler_running": False,
                "message": str(exc),
            }
        _log(
            f"force-restart reason={reason} stale supervisor "
            f"ok={restarted.get('ok')} heartbeat_age={_heartbeat_age_sec()}"
        )
        return {
            "action": "restarted",
            "crawler_running": bool(restarted.get("crawler_running")),
            "restarted": restarted,
            "message": "监督进程在但爬虫无心跳，已强制重启",
        }

    try:
        started = start_crawler(use_supervisor=True)
    except ValueError as exc:
        _log(f"auto-start blocked reason={reason} error={exc}")
        return {
            "action": "blocked",
            "crawler_running": False,
            "message": str(exc),
        }
    _log(f"auto-start reason={reason} mode={started.get('mode')} pid={started.get('pid')}")
    return {
        "action": "started",
        "crawler_running": False,
        "started": started,
        "message": "已自动启动爬虫监督进程",
    }


class CrawlerWatchdog:
    def __init__(self, config: dict | None = None):
        cfg = config or _read_config()
        self.enabled = bool(cfg.get("crawler_auto_restart", False))
        self.auto_off_on_complete = bool(
            cfg.get("crawler_watchdog_auto_off_on_complete", True)
        )
        self.interval_sec = self._normalize_interval(
            cfg.get("crawler_watchdog_interval_sec", _DEFAULT_WATCHDOG_INTERVAL_SEC)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_action = ""
        self._last_check = ""
        self._disabled_reason = ""
        self._work_remaining_cache: tuple[float, bool] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_interval(raw: object) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = _DEFAULT_WATCHDOG_INTERVAL_SEC
        return max(_MIN_WATCHDOG_INTERVAL_SEC, value)

    def _reload_runtime_config(self) -> None:
        cfg = _read_config()
        self.auto_off_on_complete = bool(
            cfg.get("crawler_watchdog_auto_off_on_complete", self.auto_off_on_complete)
        )
        self.interval_sec = self._normalize_interval(
            cfg.get("crawler_watchdog_interval_sec", self.interval_sec)
        )

    def _work_remaining(self) -> bool:
        now = time.time()
        if self._work_remaining_cache:
            ts, value = self._work_remaining_cache
            if now - ts < _WORK_REMAINING_TTL_SEC:
                return value
        value = crawl_work_remaining()
        self._work_remaining_cache = (now, value)
        return value

    def _invalidate_work_cache(self) -> None:
        self._work_remaining_cache = None

    def set_enabled(
        self,
        enabled: bool,
        *,
        persist: bool = True,
        reason: str = "manual",
    ) -> dict[str, object]:
        with self._lock:
            self.enabled = bool(enabled)
            if enabled:
                self._disabled_reason = ""
            else:
                self._disabled_reason = reason
        if persist:
            _write_config_flag("crawler_auto_restart", self.enabled)
        _log(f"watchdog {'enabled' if self.enabled else 'disabled'} reason={reason}")
        self._invalidate_work_cache()
        if enabled:
            try:
                result = ensure_crawler_running(reason=reason)
                with self._lock:
                    self._last_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._last_action = str(result.get("action") or "enabled")
            except Exception as exc:
                _log(f"enable ensure failed: {exc!r}")
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            enabled = self.enabled
            disabled_reason = self._disabled_reason
            last_action = self._last_action
            last_check = self._last_check
        work_snapshot = crawl_work_snapshot()
        self._work_remaining_cache = (
            time.time(),
            bool(work_snapshot.get("work_remaining")),
        )
        work_remaining = bool(work_snapshot.get("work_remaining"))
        crawler_alive = crawler_running()
        supervisor_alive = bool(list_supervisor_pids())
        return {
            "enabled": enabled,
            "auto_off_on_complete": self.auto_off_on_complete,
            "interval_sec": self.interval_sec,
            "work_remaining": work_remaining,
            "crawler_running": crawler_alive,
            "supervisor_running": supervisor_alive,
            "work": work_snapshot,
            "last_action": last_action,
            "last_check": last_check,
            "disabled_reason": disabled_reason,
            "message": self._status_message(enabled, work_remaining, disabled_reason),
        }

    @staticmethod
    def _status_message(
        enabled: bool,
        work_remaining: bool,
        disabled_reason: str,
        *,
        preview_exhausted: int = 0,
    ) -> str:
        if not work_remaining and preview_exhausted:
            return (
                f"任务主体已完成，但有 {int(preview_exhausted)} 个封面重试耗尽，"
                "需要手动重新入队。"
            )
        if not work_remaining:
            return "任务已完成，守护无需继续"
        if enabled:
            return "自动守护已开启：定时检测并自动拉起爬虫，直至当前任务全部完成"
        if disabled_reason == "auto_complete":
            return "任务已完成，自动守护已自动关闭"
        if disabled_reason == "manual":
            return "自动守护已手动关闭，需自行点「启动爬虫」"
        return "自动守护已关闭"

    def _maybe_auto_disable(self) -> None:
        if not self.auto_off_on_complete or not self.enabled:
            return
        if self._work_remaining():
            return
        self.set_enabled(False, reason="auto_complete")

    def _tick(self) -> None:
        self._reload_runtime_config()
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.enabled:
            with self._lock:
                self._last_check = now_text
                self._last_action = "disabled"
            return

        if not self._work_remaining():
            with self._lock:
                self._last_check = now_text
                self._last_action = "complete"
            self._maybe_auto_disable()
            return

        result = ensure_crawler_running(reason="interval")
        with self._lock:
            self._last_check = now_text
            self._last_action = str(result.get("action") or "")
        if result.get("action") in {"started", "restarted"}:
            _log(f"interval-check action={result.get('action')}")
        if result.get("action") == "complete":
            self._maybe_auto_disable()

    def _loop(self) -> None:
        _log("watchdog thread started")
        if self.enabled and self._work_remaining():
            try:
                boot = ensure_crawler_running(reason="boot")
                with self._lock:
                    self._last_action = str(boot.get("action") or "boot")
                    self._last_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except Exception as exc:
                _log(f"boot ensure failed: {exc!r}")
        else:
            with self._lock:
                self._last_action = "disabled" if not self.enabled else "complete"
                self._last_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        while not self._stop.is_set():
            self._reload_runtime_config()
            if self._stop.wait(self.interval_sec):
                break
            try:
                self._tick()
            except Exception as exc:
                _log(f"tick failed: {exc!r}")

        _log("watchdog thread stopped")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="crawler-watchdog", daemon=True
        )
        self._thread.start()
        _log(f"watchdog thread scheduled enabled={self.enabled}")

    def stop(self) -> None:
        self._stop.set()


_WATCHDOG: CrawlerWatchdog | None = None


def get_watchdog(config: dict | None = None) -> CrawlerWatchdog:
    global _WATCHDOG
    if _WATCHDOG is None:
        _WATCHDOG = CrawlerWatchdog(config)
    return _WATCHDOG
