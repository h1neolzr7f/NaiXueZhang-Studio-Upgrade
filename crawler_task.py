"""爬虫任务配置：读取、保存、应用与预设。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from paths import data_dir

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DONE_FILE = ROOT / "logs" / "COMPLETED.txt"
DB_PATH: Path | None = None


def _db_path() -> Path:
    return Path(DB_PATH) if DB_PATH is not None else data_dir() / "aitag.db"

SEARCH_KEYS = (
    "search_query",
    "search_sort",
    "search_time_range",
    "search_max_pages",
)
TASK_KEYS = (
    *SEARCH_KEYS,
    "crawler_phase",
    "dataset_name",
    "search_batch_pages",
)
VALID_PHASES = {"all", "search", "detail", "preview"}
VALID_SORTS = {"new", "monthly", "count"}
VALID_TIME_RANGES = {"all", "day", "week", "month", "year", "current"}

PRESETS: list[dict[str, Any]] = [
    {
        "id": "arknights_incremental",
        "label": "明日方舟增量更新",
        "search_query": "-NAI_X NAI 明日方舟",
        "search_sort": "new",
        "search_time_range": "all",
        "search_max_pages": 0,
        "crawler_phase": "all",
        "dataset_name": "arknights-nai",
    },
    {
        "id": "arknights_nai",
        "label": "明日方舟 NAI 全量",
        "search_query": "-NAI_X NAI 明日方舟",
        "search_sort": "new",
        "search_time_range": "all",
        "search_max_pages": 0,
        "crawler_phase": "all",
        "dataset_name": "arknights-nai",
    },
    {
        "id": "nai_only",
        "label": "全站 NAI（不限角色）",
        "search_query": "-NAI_X NAI",
        "search_sort": "new",
        "search_time_range": "all",
        "search_max_pages": 0,
        "crawler_phase": "all",
        "dataset_name": "nai-all",
    },
    {
        "id": "test_5_pages",
        "label": "试跑 5 页",
        "search_query": "-NAI_X NAI 明日方舟",
        "search_sort": "new",
        "search_time_range": "all",
        "search_max_pages": 5,
        "crawler_phase": "all",
        "dataset_name": "arknights-nai-test",
    },
    {
        "id": "search_only",
        "label": "仅爬作品列表",
        "crawler_phase": "search",
    },
    {
        "id": "detail_only",
        "label": "仅补详情元数据",
        "crawler_phase": "detail",
    },
    {
        "id": "preview_only",
        "label": "仅补封面预览",
        "crawler_phase": "preview",
    },
]

ARKNIGHTS_INCREMENTAL_TASK: dict[str, Any] = {
    "search_query": "-NAI_X NAI 明日方舟",
    "search_sort": "new",
    "search_time_range": "all",
    "search_max_pages": 0,
    "crawler_phase": "all",
    "dataset_name": "arknights-nai",
}

PERFORMANCE_PROFILES: dict[str, dict[str, Any]] = {
    "balanced": {
        "concurrent_workers": 2,
        "max_concurrent_workers": 4,
        "parallel_max_detail_workers": 3,
        "preview_workers": 3,
        "request_delay_sec": 0.8,
        "min_request_delay_sec": 0.45,
        "adaptive_growth_clean_batches": 2,
        "adaptive_latency_target_sec": 10.0,
        "detail_queue_high_watermark": 120,
        "crawler_wal_autocheckpoint_pages": 2048,
        "crawler_wal_journal_limit_mb": 64,
    },
    "safe": {
        "concurrent_workers": 1,
        "max_concurrent_workers": 2,
        "parallel_max_detail_workers": 2,
        "preview_workers": 2,
        "request_delay_sec": 1.2,
        "min_request_delay_sec": 0.8,
        "adaptive_growth_clean_batches": 3,
    },
}


def apply_performance_profile(profile: str = "balanced") -> dict[str, Any]:
    key = str(profile or "balanced").strip().lower()
    if key not in PERFORMANCE_PROFILES:
        raise ValueError(f"unknown crawler performance profile: {profile}")
    cfg = _read_config()
    values = dict(PERFORMANCE_PROFILES[key])
    cfg.update(values)
    _write_config(cfg)
    return {
        "ok": True,
        "id": key,
        "adaptive": True,
        "config": values,
    }


def _read_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _write_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_task(raw: dict, *, base: dict | None = None) -> dict[str, Any]:
    cfg = base or _read_config()
    task = {
        "search_query": str(raw.get("search_query", cfg.get("search_query", ""))).strip(),
        "search_sort": str(raw.get("search_sort", cfg.get("search_sort", "new"))).strip()
        or "new",
        "search_time_range": str(
            raw.get("search_time_range", cfg.get("search_time_range", "all"))
        ).strip()
        or "all",
        "search_max_pages": max(
            0, int(raw.get("search_max_pages", cfg.get("search_max_pages", 0)) or 0)
        ),
        "search_batch_pages": max(
            1, int(raw.get("search_batch_pages", cfg.get("search_batch_pages", 8)) or 8)
        ),
        "crawler_phase": str(raw.get("crawler_phase", cfg.get("crawler_phase", "all")))
        .strip()
        or "all",
        "dataset_name": str(raw.get("dataset_name", cfg.get("dataset_name", "local")))
        .strip()
        or "local",
    }
    if task["search_sort"] not in VALID_SORTS:
        raise ValueError(f"search_sort 无效: {task['search_sort']}")
    if task["search_time_range"] not in VALID_TIME_RANGES:
        raise ValueError(f"search_time_range 无效: {task['search_time_range']}")
    if task["crawler_phase"] not in VALID_PHASES:
        raise ValueError(f"crawler_phase 无效: {task['crawler_phase']}")
    if not task["search_query"] and task["crawler_phase"] in {"all", "search"}:
        raise ValueError("搜索类任务需要填写搜索关键词")
    return task


def get_task() -> dict[str, Any]:
    cfg = _read_config()
    task = _normalize_task(cfg, base=cfg)
    task["phase_label"] = _phase_label(task["crawler_phase"])
    return task


def search_params_changed(old: dict, new: dict) -> bool:
    return any(str(old.get(key, "")) != str(new.get(key, "")) for key in SEARCH_KEYS)


def reset_search_progress() -> None:
    if DONE_FILE.exists():
        DONE_FILE.unlink()
    conn = sqlite3.connect(_db_path())
    conn.execute(
        "DELETE FROM crawl_state WHERE key IN "
        "('search_page', 'search_done', 'search_total', 'search_total_pages')"
    )
    conn.executemany(
        "INSERT INTO crawl_state(key, value) VALUES (?, ?)",
        [("search_page", "1"), ("search_done", "0")],
    )
    conn.commit()
    conn.close()


def save_task(updates: dict) -> dict[str, Any]:
    cfg = _read_config()
    task = _normalize_task({**cfg, **updates}, base=cfg)
    for key in TASK_KEYS:
        cfg[key] = task[key]
    _write_config(cfg)
    task["phase_label"] = _phase_label(task["crawler_phase"])
    return task


def apply_task(
    updates: dict,
    *,
    reset_search: bool | None = None,
    restart: bool = False,
) -> dict[str, Any]:
    old = get_task()
    task = save_task(updates)
    phase = task["crawler_phase"]
    should_reset = bool(reset_search)
    if reset_search is None:
        should_reset = search_params_changed(old, task) and phase in {"all", "search"}
    reset_done = False
    if should_reset:
        reset_search_progress()
        reset_done = True
    restarted = False
    restart_result: dict[str, Any] | None = None
    if restart:
        from crawler_control import restart_crawler

        restart_result = restart_crawler()
        restarted = bool(restart_result.get("ok"))
    return {
        "ok": True,
        "task": task,
        "reset_search": reset_done,
        "restarted": restarted,
        "restart": restart_result,
        "message": _apply_message(task, reset_done, restarted, restart_result),
    }


def apply_arknights_incremental_update(*, restart: bool = True) -> dict[str, Any]:
    """从新作品排序重新扫描明日方舟 NAI，数据库/图片按已有去重增量补齐。"""
    cfg = _read_config()
    cfg["preview_mode"] = "cover_only"
    cfg["preview_all_local"] = True
    _write_config(cfg)
    result = apply_task(
        ARKNIGHTS_INCREMENTAL_TASK,
        reset_search=True,
        restart=restart,
    )
    result["mode"] = "arknights_incremental"
    result["message"] = (
        "明日方舟增量更新已启动：从新作品排序第 1 页重新扫描，"
        "已有详情/封面会自动跳过，只补库里没有的新作品。"
        if result.get("restarted")
        else "明日方舟增量更新任务已保存；下次启动爬虫会从新作品排序补齐缺失项。"
    )
    return result


def _phase_label(phase: str) -> str:
    return {
        "all": "全流程（列表→详情→封面）",
        "search": "仅作品列表",
        "detail": "仅详情元数据",
        "preview": "仅封面预览",
    }.get(phase, phase)


def _apply_message(
    task: dict,
    reset_search: bool,
    restarted: bool,
    restart_result: dict | None,
) -> str:
    parts = [f"任务已保存：{task['search_query'] or '（无新搜索）'} · {task['phase_label']}"]
    if reset_search:
        parts.append("已重置列表爬取进度")
    if restarted:
        parts.append(
            restart_result.get("message", "爬虫已重启")
            if restart_result
            else "已发送重启命令"
        )
    elif not reset_search:
        parts.append("下次启动/重启爬虫后生效")
    return "；".join(parts)


def list_presets() -> list[dict[str, Any]]:
    current = get_task()
    items: list[dict[str, Any]] = []
    for preset in PRESETS:
        merged = {**current, **preset}
        item = {
            "id": preset["id"],
            "label": preset["label"],
            "task": _normalize_task(merged, base=current),
        }
        item["task"]["phase_label"] = _phase_label(item["task"]["crawler_phase"])
        items.append(item)
    return items
