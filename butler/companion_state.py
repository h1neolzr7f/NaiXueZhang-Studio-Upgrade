"""Confirmed companion memory, persona handoff, and anti-disturbance.

v1.9. TTS is intentionally not part of this module or its score.
Screen capture, key/mouse hooks, and God Agent are forbidden.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from atomic_io import atomic_write_text
from paths import data_dir

STATE_PATH = data_dir() / "companion_state.json"
STATE_VERSION = 1
MAX_MEMORIES = 40
MAX_EVENT_LOG = 40
EVENT_TTL_SEC = 6 * 3600
_STATE_LOCK = threading.RLock()
_SENSITIVE_MEMORY = re.compile(
    r"(?i)("
    r"pst-[A-Za-z0-9._~+/-]+"
    r"|sk-[A-Za-z0-9._~+/-]+"
    r"|Bearer\s+\S+"
    r"|(?:cookie|password|token)\s*[:=]\s*\S+"
    r"|[A-Za-z]:\\[^\s]+"
    r"|/(?:home|Users|data|etc|tmp|var|root)(?:/[^\s]*)?"
    r")"
)
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
        "acks": [],
        "updated_at": _utc_now(),
    }


def _load_state_unlocked() -> dict[str, Any]:
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
    payload["acks"] = [item for item in list(payload.get("acks") or []) if isinstance(item, dict)][-MAX_EVENT_LOG:]
    payload["version"] = STATE_VERSION
    return payload


def _save_state_unlocked(state: dict[str, Any]) -> dict[str, Any]:
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


def load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return _load_state_unlocked()


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        return _save_state_unlocked(state)


def confirmed_memories(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = state if state is not None else load_state()
    return [
        item
        for item in list(payload.get("memories") or [])
        if str(item.get("status") or "") == "confirmed"
    ]


def confirmed_lines(limit: int = 5) -> list[str]:
    rows = confirmed_memories()[: max(0, int(limit))]
    return [str(item.get("text") or "").strip() for item in rows if str(item.get("text") or "").strip()]


def sanitize_memory_text(text: str) -> str:
    cleaned = _SENSITIVE_MEMORY.sub("[redacted]", str(text or ""))
    leftover = re.sub(r"\[redacted\]", "", cleaned).strip(" \t\r\n,;:|.-")
    if not leftover:
        return ""
    return " ".join(cleaned.split())


def planner_memory_context(limit: int = 5) -> list[str]:
    """Confirmed memories for the planner, with secrets and paths stripped."""

    with _STATE_LOCK:
        raw_lines = confirmed_lines(max(0, int(limit)) * 2)
    lines: list[str] = []
    for raw in raw_lines:
        cleaned = sanitize_memory_text(raw)
        if cleaned:
            lines.append(cleaned)
        if len(lines) >= max(0, int(limit)):
            break
    return lines


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
    item = {
        "id": f"mem-{secrets.token_hex(6)}",
        "text": cleaned[:400],
        "status": "proposed",
        "agent": str(agent or ""),
        "source": str(source or "user"),
        "created_at": _utc_now(),
        "confirmed_at": None,
    }
    with _STATE_LOCK:
        state = _load_state_unlocked()
        state["memories"] = [item, *list(state.get("memories") or [])][:MAX_MEMORIES]
        _save_state_unlocked(state)
    return item


def confirm_memory(memory_id: str, *, confirm: bool = True) -> dict[str, Any]:
    with _STATE_LOCK:
        state = _load_state_unlocked()
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
        _save_state_unlocked(state)
    return found


def forget_memory(memory_id: str) -> dict[str, Any]:
    return confirm_memory(memory_id, confirm=False)


def record_handoff(*, from_agent: str, to_agent: str, note: str = "") -> dict[str, Any]:
    allowed = {"sakiko", "tomori"}
    source = str(from_agent or "").strip()
    target = str(to_agent or "").strip()
    if source not in allowed or target not in allowed or source == target:
        raise ValueError("handoff must be between sakiko and tomori")
    with _STATE_LOCK:
        state = _load_state_unlocked()
        memories: list[str] = []
        for item in confirmed_memories(state)[:5]:
            cleaned = sanitize_memory_text(str(item.get("text") or "").strip())
            if cleaned:
                memories.append(cleaned)
        handoff = {
            "from_agent": source,
            "to_agent": target,
            "note": str(note or "").strip()[:400],
            "memories": memories,
            "at": _utc_now(),
            "consumed": False,
        }
        state["handoff"] = handoff
        _save_state_unlocked(state)
    return handoff


def consume_handoff(agent_id: str) -> dict[str, Any] | None:
    with _STATE_LOCK:
        state = _load_state_unlocked()
        handoff = state.get("handoff")
        if not isinstance(handoff, dict) or handoff.get("consumed"):
            return None
        if str(handoff.get("to_agent") or "") != str(agent_id or ""):
            return None
        handoff = dict(handoff)
        handoff["consumed"] = True
        state["handoff"] = handoff
        _save_state_unlocked(state)
    return handoff


def update_quiet(patch: dict[str, Any]) -> dict[str, Any]:
    with _STATE_LOCK:
        state = _load_state_unlocked()
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
        _save_state_unlocked(state)
    return quiet


def _parse_hhmm(value: str) -> time | None:
    parts = str(value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except ValueError:
        return None


def _quiet_timezone(name: str):
    raw = str(name or "local").strip() or "local"
    if raw.lower() in {"local", "system"}:
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return timezone.utc


def in_quiet_hours(now: datetime | None = None, quiet: dict[str, Any] | None = None) -> bool:
    settings = quiet or load_state().get("quiet") or DEFAULT_QUIET
    if not settings.get("enabled"):
        return False
    start = _parse_hhmm(str(settings.get("start") or ""))
    end = _parse_hhmm(str(settings.get("end") or ""))
    if start is None or end is None:
        return False
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    localized = stamp.astimezone(_quiet_timezone(str(settings.get("timezone") or "local")))
    current = time(localized.hour, localized.minute)
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
    stamp = _coerce_aware(now or datetime.now(timezone.utc))
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


def _coerce_aware(stamp: datetime) -> datetime:
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp


def _ack_is_active(ack: dict[str, Any], now: datetime) -> bool:
    when = _parse_iso(str(ack.get("at") or ""))
    if when is None:
        return False
    ttl = int(ack.get("ttl_sec") or EVENT_TTL_SEC)
    age = (_coerce_aware(now) - _coerce_aware(when)).total_seconds()
    return 0 <= age < ttl


def _upsert_ack(
    acks: list[dict[str, Any]],
    key: str,
    *,
    ttl_sec: int | None = None,
    at: datetime | None = None,
) -> list[dict[str, Any]]:
    stamp = _coerce_aware(at or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    ttl = EVENT_TTL_SEC if ttl_sec is None else max(1, int(ttl_sec))
    kept = [item for item in acks if str(item.get("key") or "") != key]
    kept.append({"key": key, "at": stamp, "ttl_sec": ttl})
    return kept[-MAX_EVENT_LOG:]


def _key_is_acked(state: dict[str, Any], key: str, now: datetime) -> bool:
    for ack in list(state.get("acks") or []):
        if str(ack.get("key") or "") == key and _ack_is_active(ack, now):
            return True
    return False


def ack_event(
    key: str,
    *,
    ttl_sec: int | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    cleaned = str(key or "").strip()
    if not cleaned:
        raise ValueError("event key is required")
    with _STATE_LOCK:
        state = _load_state_unlocked()
        state["acks"] = _upsert_ack(list(state.get("acks") or []), cleaned, ttl_sec=ttl_sec, at=at)
        _save_state_unlocked(state)
    return {"key": cleaned, "ttl_sec": EVENT_TTL_SEC if ttl_sec is None else max(1, int(ttl_sec))}


def mark_delivered(event_id: str, *, key: str = "", ttl_sec: int | None = None) -> None:
    with _STATE_LOCK:
        state = _load_state_unlocked()
        deliveries = list(state.get("deliveries") or [])
        ack_key = str(key or event_id or "").strip()
        deliveries.append({"id": event_id, "key": ack_key, "at": _utc_now()})
        state["deliveries"] = deliveries[-MAX_EVENT_LOG:]
        if ack_key:
            state["acks"] = _upsert_ack(list(state.get("acks") or []), ack_key, ttl_sec=ttl_sec)
        _save_state_unlocked(state)


def collect_local_events(
    *,
    token_ok: bool = True,
    queue_count: int = 0,
    dirty: int = 0,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Local product signals only. No screen, hooks, or God Agent."""

    stamp = _coerce_aware(now or datetime.now(timezone.utc))
    events: list[dict[str, Any]] = []
    if not token_ok:
        events.append(
            {
                "id": "token_missing",
                "key": "token_missing",
                "kind": "token_missing",
                "title": "还没有配置 NovelAI Token",
                "body": "出图前先在设置里放入 Token。云端不会替你保存聊天里出现过的密钥。",
                "agent": "tomori",
            }
        )
    if int(queue_count or 0) > 0:
        events.append(
            {
                "id": "queue_pending",
                "key": "queue_pending",
                "kind": "queue_pending",
                "title": f"待生成队列还有 {int(queue_count)} 项",
                "body": "助手凑企鹅可以先准备参数，不会直接出图。",
                "agent": "tomori",
            }
        )
    if int(dirty or 0) > 0:
        events.append(
            {
                "id": "gallery_index_dirty",
                "key": "gallery_index_dirty",
                "kind": "gallery_index_dirty",
                "title": f"图库索引有 {int(dirty)} 条脏记录",
                "body": "客服小祥可以跑增量索引，不会改搜索 JSON。",
                "agent": "sakiko",
            }
        )
    state = load_state()
    proposed = [item for item in list(state.get("memories") or []) if item.get("status") == "proposed"]
    if proposed:
        memory_id = str(proposed[0].get("id") or "")
        events.append(
            {
                "id": f"memory_unconfirmed:{memory_id}",
                "key": f"memory_unconfirmed:{memory_id}",
                "kind": "memory_unconfirmed",
                "title": "有一条偏好还没确认",
                "body": sanitize_memory_text(str(proposed[0].get("text") or ""))
                or "有一条偏好待确认",
                "agent": str(proposed[0].get("agent") or "sakiko"),
            }
        )
    handoff = state.get("handoff")
    if isinstance(handoff, dict) and not handoff.get("consumed"):
        events.append(
            {
                "id": "handoff_waiting",
                "key": "handoff_waiting",
                "kind": "handoff_waiting",
                "title": "有一条人格交接还没读",
                "body": str(handoff.get("note") or "另一位助手把上下文交给你了。"),
                "agent": str(handoff.get("to_agent") or ""),
            }
        )
    return [item for item in events if not _key_is_acked(state, str(item.get("key") or ""), stamp)]


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
