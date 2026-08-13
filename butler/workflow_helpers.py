"""Progress helpers and typed state for the Butler LangGraph runtime."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, TypedDict


class _LegacyProxy:
    def __getattr__(self, name: str) -> Any:
        import butler.workflow as wf

        return getattr(wf.legacy, name)


legacy = _LegacyProxy()

class WorkflowCancelled(RuntimeError):
    pass


class UnknownExternalOutcome(RuntimeError):
    pass


def _secure_local_configuration_plan(message: str) -> dict[str, Any] | None:
    """Consume explicitly submitted secrets locally before any planner/checkpoint boundary."""

    raw = str(message or "")
    folded = raw.casefold()
    if not any(word in folded for word in ("配置", "保存", "添加", "启用", "设置", "configure")):
        return None
    configured: list[str] = []
    nai_tokens = list(dict.fromkeys(re.findall(r"\bpst-[A-Za-z0-9_-]{20,}\b", raw, re.I)))
    if nai_tokens:
        from nai_api import add_token_entry

        for token in nai_tokens:
            add_token_entry({"token": token, "provider": "novelai"})
        configured.append(f"NovelAI 槽位 {len(nai_tokens)} 个")

    api_keys = list(dict.fromkeys(re.findall(r"\bsk-[A-Za-z0-9_-]{12,}\b", raw)))
    urls = re.findall(r"https?://[^\s,，;；]+", raw)
    if api_keys and urls and any(word in folded for word in ("api", "中转", "grok", "聊天", "识图")):
        from pixiv_launch import save_ai_key, save_config

        api_base = urls[0].rstrip("/")
        save_config(
            {
                "ai": {
                    "provider": "自定义 OpenAI-compatible",
                    "api_base": api_base,
                }
            }
        )
        save_ai_key(api_keys[0])
        configured.append("聊天/识图 API")

    password_present = bool(re.search(r"(?:密码|password)\s*[:：=]?\s*\S+", raw, re.I))
    if not configured and not password_present:
        return None
    if configured:
        reply = (
            f"已经在本机安全配置好：{'、'.join(configured)}。凭据没有交给模型，也没有写入聊天记录；"
            "图库、小镜、工作台和导演会共用这份配置。你可以到配置中心检查或测试连接。"
        )
    else:
        reply = (
            "我识别到了账号或密码，但没有保存密码，也不会把它发给模型。"
            "请在配置中心使用官方 Token/通行密钥入口完成登录；这样更安全，也便于失效后单独更新。"
        )
    return {"reply": reply, "actions": []}


class ButlerState(TypedDict, total=False):
    workflow_id: str
    message: str
    history: list[dict[str, str]]
    preplanned: dict[str, Any]
    model: str
    reply: str
    actions: list[dict[str, Any]]
    action_index: int
    tool_results: list[dict[str, Any]]
    rejected_actions: list[dict[str, str]]
    skipped_actions: list[dict[str, Any]]
    approval: Any
    cancelled: bool
    status: str
    phase: str
    result: dict[str, Any]


Planner = Callable[[str, Any], dict[str, Any]]
AutoExecutor = Callable[[dict[str, Any]], dict[str, Any]]
ConfirmedExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _operation_identity(workflow_id: str, index: int, action: dict[str, Any]) -> tuple[str, str]:
    canonical = json.dumps(
        {"tool": action["tool"], "arguments": action["arguments"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    arguments_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    operation_id = hashlib.sha256(
        f"{workflow_id}:{index}:{arguments_hash}".encode("utf-8")
    ).hexdigest()[:32]
    return operation_id, arguments_hash


def _format_eta(seconds: float | int) -> str:
    value = max(0, int(round(float(seconds or 0))))
    if value <= 20:
        return "预计不到 1 分钟"
    if value < 90:
        return "预计约 1 分钟"
    if value < 3600:
        minutes = max(2, int(round(value / 60)))
        return f"预计约 {minutes} 分钟"
    hours = max(1, int(round(value / 3600)))
    return f"预计约 {hours} 小时"


def _action_estimate_seconds(action: dict[str, Any]) -> int:
    """Return a deliberately broad initial estimate; live loops replace it with observed speed."""
    tool = str(action.get("tool") or "")
    args = action.get("arguments") or {}
    if tool == "generate_image":
        return min(1800, 75 * max(1, int(args.get("batch_count") or 1)))
    if tool in {"batch_generate", "batch_generate_and_prepare_pixiv"}:
        works = args.get("work_refs") or args.get("work_ids") or []
        copies = max(1, int(args.get("copies_per_work") or 1))
        return min(3600, 60 * max(1, len(works) * copies))
    if tool == "batch_director":
        return min(5400, 75 * max(1, len(args.get("sources") or [])))
    if tool == "run_pipeline":
        return 90
    if tool == "prepare_pixiv_submission":
        return 45
    if tool in {"start_crawler", "stop_crawler", "configure_crawler"}:
        return 20
    return 8 if tool in legacy._AUTO_TOOLS else 15


def _planned_progress(
    actions: list[dict[str, Any]],
    index: int,
    *,
    stage: str,
    skipped_indexes: set[int] | None = None,
    waiting: bool = False,
    cancelled: bool = False,
) -> dict[str, Any]:
    total = len(actions)
    cursor = max(0, min(int(index), total))
    skipped = skipped_indexes or set()
    steps: list[dict[str, Any]] = []
    for step_index, action in enumerate(actions):
        if step_index in skipped:
            state = "skipped"
        elif step_index < cursor:
            state = "completed"
        elif cancelled and step_index >= cursor:
            state = "cancelled"
        elif step_index == cursor and cursor < total:
            state = "waiting" if waiting else "running"
        else:
            state = "pending"
        steps.append(
            {
                "index": step_index + 1,
                "tool": str(action.get("tool") or ""),
                "label": str(action.get("label") or action.get("tool") or f"步骤 {step_index + 1}"),
                "status": state,
            }
        )
    remaining = sum(_action_estimate_seconds(item) for item in actions[cursor:])
    current_label = (
        str(actions[cursor].get("label") or actions[cursor].get("tool") or "正在执行")
        if cursor < total
        else "正在整理交付报告"
    )
    next_label = (
        str(actions[cursor + 1].get("label") or actions[cursor + 1].get("tool") or "下一步")
        if cursor + 1 < total
        else ("生成交付报告" if cursor < total else "无，正在收尾")
    )
    return {
        "workflow_current": min(cursor + 1, total) if total else 0,
        "workflow_completed": cursor,
        "workflow_total": total,
        "steps": steps,
        "stage": stage,
        "current_label": current_label,
        "next_label": next_label,
        "eta_seconds": remaining,
        "eta_text": _format_eta(remaining) if remaining else "马上完成",
        "eta_basis": "initial_estimate",
        "estimate_updated_at": _now(),
    }


def _elapsed_seconds(started_at: Any, finished_at: Any = None) -> int:
    try:
        started = datetime.fromisoformat(str(started_at or ""))
        finished = datetime.fromisoformat(str(finished_at or _now()))
        return max(0, int((finished - started).total_seconds()))
    except (TypeError, ValueError):
        return 0


def _status_poll_delay(started_monotonic: float) -> float:
    elapsed = max(0.0, time.monotonic() - started_monotonic)
    if elapsed < 2:
        return 0.2
    if elapsed < 10:
        return 0.4
    return 0.75


POLL_WALL_CLOCK_TIMEOUT_SEC = 6 * 60 * 60


def _poll_timed_out(started_monotonic: float) -> bool:
    return (time.monotonic() - started_monotonic) >= POLL_WALL_CLOCK_TIMEOUT_SEC
