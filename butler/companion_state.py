"""Confirmed companion memory, persona handoff, and anti-disturbance.

v1.9. TTS is intentionally not part of this module or its score.
Screen capture, key/mouse hooks, and God Agent are forbidden.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from atomic_io import atomic_write_text
from paths import data_dir

STATE_PATH = data_dir() / "companion_state.json"
STATE_VERSION = 1
MAX_MEMORIES = 40
MAX_EVENT_LOG = 40
DEFAULT_QUIET = {
    "enabled": False,
    "start": "22:00",
    "end": "08:00",
    "max_events_per_hour": 3,
    "min_interval_seconds": 1800,
    "timezone": "local",
}
FORBIDDEN_SOURCES = frozenset({"screen", "keyhook", "mousehook", "god_agent", "keylogger"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "memories": [],
        "quiet": dict(DEFAULT_QUIET),
        "handoff": None,
        "event_log": [],
        "deliveries": [],
        "updated_at": _utc_now(),
    }


def load_state() -> dict[str, Any]:
    payload = _empty_state()
    if STATE_PATH.exists():
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    memories = [
        item
        for item in list(payload.get("memories") or [])
        if isinstance(item, dict) and str(item.get("source") or "") not in FORBIDDEN_SOURCES
    ]
    payload["memories"] = memories[:MAX_MEMORIES]
    quiet = dict(DEFAULT_QUIET)
    if isinstance(payload.get("quiet"), dict):
        quiet.update({key: payload["quiet"].get(key, quiet[key]) for key in DEFAULT_QUIET})
    payload["quiet"] = quiet
    payload["event_log"] = [item for item in list(payload.get("event_log") or []) if isinstance(item, dict)][
        -MAX_EVENT_LOG:
    ]
    payload["deliveries"] = [item for item in list(payload.get("deliveries") or []) if isinstance(item, dict)][
        -MAX_EVENT_LOG:
    ]
    payload["version"] = STATE_VERSION
    return payload


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    payload["version"] = STATE_VERSION
    payload["updated_at"] = _utc_now()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        STATE_PATH,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def confirmed_memories(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = state or load_state()
    return [
        item
        for item in list(payload.get("memories") or [])
        if str(item.get("status") or "") == "confirmed"
    ]


def confirmed_lines(limit: int = 5) -> list[str]:
    rows = confirmed_memories()[: max(0, int(limit))]
    return [str(item.get("text") or "").strip() for item in rows if str(item.get("text") or "").strip()]


def propose_memory(
    text: str,
    *,
    agent: str = "",
    source: str = "user",
) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("memory text is required")
    if str(source or "") in FORBIDDEN_SOURCES:
        raise ValueError("this memory source is forbidden")
    state = load_state()
    item = {
        "id": f"mem-{secrets.token_hex(6)}",
        "text": cleaned[:400],
        "status": "proposed",
        "agent": str(agent or ""),
        "source": str(source or "user"),
        "created_at": _utc_now(),
        "confirmed_at": None,
    }
    state["memories"] = [item, *list(state.get("memories") or [])][:MAX_MEMORIES]
    save_state(state)
    return item


def confirm_memory(memory_id: str, *, confirm: bool = True) -> dict[str, Any]:
    state = load_state()
    found = None
    kept: list[dict[str, Any]] = []
    for item in list(state.get("memories") or []):
        if str(item.get("id") or "") != str(memory_id):
            kept.append(item)
            continue
        found = dict(item)
        if confirm:
            found["status"] = "confirmed"
            found["confirmed_at"] = _utc_now()
            kept.append(found)
        else:
            found["status"] = "forgotten"
            found["confirmed_at"] = None
    if found is None:
        raise ValueError("memory not found")
    state["memories"] = kept
    save_state(state)
    return found


def forget_memory(memory_id: str) -> dict[str, Any]:
    return confirm_memory(memory_id, confirm=False)


def record_handoff(*, from_agent: str, to_agent: str, note: str = "") -> dict[str, Any]:
    allowed = {"sakiko", "tomori"}
    source = str(from_agent or "").strip()
    target = str(to_agent or "").strip()
    if source not in allowed or target not in allowed or source == target:
        raise ValueError("handoff must be between sakiko and tomori")
    state = load_state()
    handoff = {
        "from_agent": source,
        "to_agent": target,
        "note": str(note or "").strip()[:400],
        "memories": confirmed_lines(5),
        "at": _utc_now(),
        "consumed": False,
    }
    state["handoff"] = handoff
    save_state(state)
    return handoff


def consume_handoff(agent_id: str) -> dict[str, Any] | None:
    state = load_state()
    handoff = state.get("handoff")
    if not isinstance(handoff, dict) or handoff.get("consumed"):
        return None
    if str(handoff.get("to_agent") or "") != str(agent_id or ""):
        return None
    handoff = dict(handoff)
    handoff["consumed"] = True
    state["handoff"] = handoff
    save_state(state)
    return handoff


def update_quiet(patch: dict[str, Any]) -> dict[str, Any]:
    state = load_state()
    quiet = dict(state.get("quiet") or DEFAULT_QUIET)
    if "enabled" in patch:
        quiet["enabled"] = bool(patch.get("enabled"))
    for key in ("start", "end", "timezone"):
        if key in patch and str(patch.get(key) or "").strip():
            quiet[key] = str(patch.get(key)).strip()
    if "max_events_per_hour" in patch:
        quiet["max_events_per_hour"] = max(0, min(int(patch.get("max_events_per_hour") or 0), 12))
    if "min_interval_seconds" in patch:
        quiet["min_interval_seconds"] = max(60, min(int(patch.get("min_interval_seconds") or 60), 24 * 3600))
    state["quiet"] = quiet
    save_state(state)
    return quiet


def _parse_hhmm(value: str) -> time | None:
    parts = str(value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except ValueError:
        return None


def in_quiet_hours(now: datetime | None = None, quiet: dict[str, Any] | None = None) -> bool:
    settings = quiet or load_state().get("quiet") or DEFAULT_QUIET
    if not settings.get("enabled"):
        return False
    start = _parse_hhmm(str(settings.get("start") or ""))
    end = _parse_hhmm(str(settings.get("end") or ""))
    if start is None or end is None:
        return False
    stamp = now or datetime.now()
    current = stamp.timetz().replace(tzinfo=None) if stamp.tzinfo else stamp.time()
    current = time(current.hour, current.minute)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def delivery_allowed(now: datetime | None = None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = state or load_state()
    quiet = payload.get("quiet") or DEFAULT_QUIET
    stamp = now or datetime.now(timezone.utc)
    if in_quiet_hours(stamp, quiet):
        return {"ok": False, "reason": "quiet_hours"}
    max_per_hour = int(quiet.get("max_events_per_hour") or 0)
    min_interval = int(quiet.get("min_interval_seconds") or 0)
    deliveries = list(payload.get("deliveries") or [])
    recent = []
    for item in deliveries:
        when = _parse_iso(str(item.get("at") or ""))
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = (stamp - when).total_seconds()
        if age <= 3600:
            recent.append((age, item))
    if max_per_hour and len(recent) >= max_per_hour:
        return {"ok": False, "reason": "rate_hour"}
    if min_interval and recent and min(age for age, _ in recent) < min_interval:
        return {"ok": False, "reason": "rate_interval"}
    return {"ok": True, "reason": ""}


def mark_delivered(event_id: str) -> None:
    state = load_state()
    deliveries = list(state.get("deliveries") or [])
    deliveries.append({"id": event_id, "at": _utc_now()})
    state["deliveries"] = deliveries[-MAX_EVENT_LOG:]
    save_state(state)


def collect_local_events(*, token_ok: bool = True, queue_count: int = 0, dirty: int = 0) -> list[dict[str, Any]]:
    """Local product signals only. No screen, hooks, or God Agent."""

    events: list[dict[str, Any]] = []
    if not token_ok:
        events.append(
            {
                "id": "token-missing",
                "kind": "token_missing",
                "title": "还没有配置 NovelAI Token",
                "body": "出图前先在设置里放入 Token。云端不会替你保存聊天里出现过的密钥。",
                "agent": "tomori",
            }
        )
    if int(queue_count or 0) > 0:
        events.append(
            {
                "id": f"queue-{int(queue_count)}",
                "kind": "queue_pending",
                "title": f"待生成队列还有 {int(queue_count)} 项",
                "body": "助手凑企鹅可以先准备参数，不会直接出图。",
                "agent": "tomori",
            }
        )
    if int(dirty or 0) > 0:
        events.append(
            {
                "id": f"index-dirty-{int(dirty)}",
                "kind": "gallery_index_dirty",
                "title": f"图库索引有 {int(dirty)} 条脏记录",
                "body": "客服小祥可以跑增量索引，不会改搜索 JSON。",
                "agent": "sakiko",
            }
        )
    state = load_state()
    proposed = [item for item in list(state.get("memories") or []) if item.get("status") == "proposed"]
    if proposed:
        events.append(
            {
                "id": f"memory-{proposed[0].get('id')}",
                "kind": "memory_unconfirmed",
                "title": "有一条偏好还没确认",
                "body": str(proposed[0].get("text") or ""),
                "agent": str(proposed[0].get("agent") or "sakiko"),
            }
        )
    handoff = state.get("handoff")
    if isinstance(handoff, dict) and not handoff.get("consumed"):
        events.append(
            {
                "id": f"handoff-{handoff.get('at')}",
                "kind": "handoff_waiting",
                "title": "有一条人格交接还没读",
                "body": str(handoff.get("note") or "另一位助手把上下文交给你了。"),
                "agent": str(handoff.get("to_agent") or ""),
            }
        )
    return events


def public_state() -> dict[str, Any]:
    state = load_state()
    allowed = delivery_allowed(state=state)
    return {
        "ok": True,
        "tts": {"enabled": False, "core": False, "reason": "tts_not_in_v19_barrel"},
        "forbidden": sorted(FORBIDDEN_SOURCES),
        "quiet": state.get("quiet") or DEFAULT_QUIET,
        "handoff": state.get("handoff"),
        "memories": list(state.get("memories") or []),
        "confirmed": confirmed_memories(state),
        "delivery": allowed,
        "updated_at": state.get("updated_at"),
    }
