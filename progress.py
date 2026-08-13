import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from crawler_control import crawler_running, list_supervisor_pids
from crawler_task import get_task
from crawler_watchdog import crawl_work_snapshot, get_watchdog
from paths import data_dir, storage_paths

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def _db_path() -> Path:
    return data_dir() / "aitag.db"


WATCH_LOG = ROOT / "logs" / "watch.log"
DONE_FILE = ROOT / "logs" / "COMPLETED.txt"
HEARTBEAT_FILE = ROOT / "logs" / "crawler-heartbeat.json"


def _read_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tail_lines(path: Path, limit: int = 12) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return [line for line in lines[-limit:] if line.strip()]
    except Exception:
        return []


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _phase(current: int, total: int, done: bool = False) -> dict:
    total = max(int(total or 0), 0)
    current = max(min(int(current or 0), total), 0) if total else int(current or 0)
    if done and total:
        current = total
    percent = 100.0 if done and total else (current / total * 100 if total else 0.0)
    return {
        "current": current,
        "total": total,
        "percent": round(percent, 2),
        "done": bool(done or (total > 0 and current >= total)),
    }


def _estimate_finish(
    remaining: int, delay_sec: float, start_after_sec: float = 0
) -> str | None:
    if remaining <= 0:
        return None
    eta = datetime.now() + timedelta(
        seconds=start_after_sec + remaining * delay_sec
    )
    return eta.strftime("%Y-%m-%d %H:%M:%S")


def get_progress_snapshot() -> dict:
    config = _read_config()
    delay = float(config.get("request_delay_sec", 1.0))
    workers = max(1, int(config.get("concurrent_workers", 1)))
    effective_rate = workers / max(delay, 0.05)
    preview_mode = config.get("preview_mode", "cover_only")

    conn = sqlite3.connect(_db_path())
    states = dict(conn.execute("SELECT key, value FROM crawl_state"))
    works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    details = conn.execute(
        "SELECT COUNT(*) FROM works WHERE detail_json IS NOT NULL"
    ).fetchone()[0]
    covers = conn.execute(
        "SELECT COUNT(*) FROM works WHERE preview_downloaded = 1"
    ).fetchone()[0]
    local_images = conn.execute(
        "SELECT COUNT(*) FROM work_images WHERE downloaded = 1"
    ).fetchone()[0]
    conn.close()

    search_total = int(states.get("search_total", "0") or 0)
    search_page = int(states.get("search_page", "1") or 1) - 1
    search_total_pages = int(states.get("search_total_pages", "0") or 0)
    search_done = states.get("search_done") == "1"
    page_size = int(config.get("page_size", 60))
    search_max_pages = int(config.get("search_max_pages", 0) or 0)

    work_snapshot = crawl_work_snapshot()
    detail_pending = int(work_snapshot.get("detail_pending") or 0)
    preview_pending = int(work_snapshot.get("preview_pending") or 0)
    work_remaining = bool(work_snapshot.get("work_remaining"))
    if "search_done" in work_snapshot:
        search_done = bool(work_snapshot.get("search_done"))

    # 详情/封面始终以本地已入库作品数为分母，避免增量更新时旧 search_total 导致假 100%
    works_total = works

    if search_max_pages > 0:
        search_phase = _phase(
            min(search_page, search_max_pages),
            search_max_pages,
            done=search_done or search_page >= search_max_pages,
        )
    elif search_total_pages > 0:
        search_phase = _phase(
            min(search_page, search_total_pages),
            search_total_pages,
            done=search_done,
        )
    elif search_total > 0 and works_total <= search_total:
        search_phase = _phase(works_total, search_total, done=search_done)
    else:
        search_phase = {
            "current": search_page,
            "total": search_total_pages or 0,
            "percent": 100.0 if search_done else 0.0,
            "done": search_done,
        }

    detail_done = works_total > 0 and detail_pending <= 0 and search_done
    cover_done = works_total > 0 and preview_pending <= 0 and search_done
    detail_phase = _phase(details, works_total, done=detail_done)
    cover_phase = _phase(covers, works_total, done=cover_done)

    detail_left = detail_pending
    cover_left = preview_pending
    search_left_pages = max((search_max_pages or search_total_pages) - search_page, 0)

    detail_eta = _estimate_finish(
        detail_left, 1.0 / effective_rate, search_left_pages / effective_rate
    )
    cover_eta = _estimate_finish(
        cover_left,
        1.0 / effective_rate,
        search_left_pages / effective_rate + detail_left / effective_rate,
    )

    recent = _tail_lines(WATCH_LOG, 8)
    retry_count = sum(1 for line in recent if "[retry]" in line or "502" in line)

    task = get_task()
    watchdog = get_watchdog(config)
    watchdog_status = watchdog.status()
    heartbeat = _read_json_file(HEARTBEAT_FILE)
    if not work_snapshot:
        work_snapshot = watchdog_status.get("work") or {}
    completed = bool(DONE_FILE.exists() or (works_total > 0 and not work_remaining))
    crawler_alive = bool(watchdog_status.get("crawler_running"))
    supervisor_alive = bool(watchdog_status.get("supervisor_running"))
    auto_restart = bool(watchdog_status.get("enabled"))
    watchdog_interval = int(watchdog_status.get("interval_sec") or 300)
    watchdog_auto_off = bool(watchdog_status.get("auto_off_on_complete"))

    if completed:
        status = "completed"
        status_text = "当前任务队列完成"
    elif crawler_alive:
        status = "running"
        status_text = "爬虫运行中"
    else:
        status = "paused"
        status_text = "爬虫未运行（可能网络中断或已暂停）"

    overall_percent = round(
        (search_phase["percent"] * 0.15)
        + (detail_phase["percent"] * 0.70)
        + (cover_phase["percent"] * 0.15),
        2,
    )
    if work_remaining and not completed:
        overall_percent = min(overall_percent, 99.5)

    return {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": task.get("dataset_name", config.get("dataset_name", "local")),
        "search_query": task.get("search_query", config.get("search_query", "")),
        "crawler_phase": task.get("crawler_phase", "all"),
        "crawler_phase_label": task.get("phase_label", ""),
        "preview_mode": preview_mode,
        "search_sort": config.get("search_sort", "new"),
        "search_max_pages": search_max_pages,
        "concurrent_workers": workers,
        "request_delay_sec": delay,
        "status": status,
        "status_text": status_text,
        "crawler_running": crawler_alive,
        "supervisor_running": supervisor_alive,
        "crawler_auto_restart": auto_restart,
        "crawler_watchdog_interval_sec": watchdog_interval,
        "crawler_watchdog_auto_off_on_complete": watchdog_auto_off,
        "crawler_watchdog_message": watchdog_status.get("message", ""),
        "crawler_watchdog_last_check": watchdog_status.get("last_check", ""),
        "crawler_watchdog_last_action": watchdog_status.get("last_action", ""),
        "crawler_work_remaining": bool(watchdog_status.get("work_remaining")),
        "crawler_work": work_snapshot,
        "crawler_heartbeat": heartbeat,
        "completed": completed,
        "retry_recent": retry_count,
        "overall_percent": overall_percent,
        "phases": {
            "search": {
                **search_phase,
                "label": "作品列表",
                "page": search_page,
                "total_pages": search_total_pages,
                "eta": None if search_phase["done"] else _estimate_finish(
                    search_left_pages, delay
                ),
            },
            "details": {
                **detail_phase,
                "label": "详情元数据",
                "pending": detail_pending,
                "eta": detail_eta,
            },
            "covers": {
                **cover_phase,
                "label": "封面预览" if preview_mode == "cover_only" else "全部预览图",
                "pending": preview_pending,
                "local_images": local_images,
                "eta": cover_eta,
            },
        },
        "recent_log": recent,
        "storage_paths": storage_paths(config, ROOT),
    }
