from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EventEnvelope:
    type: str
    source: str
    subject: str
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    dedupe_key: str = ""
    sensitive: bool = False
    version: int = 1
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    occurred_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "version": self.version,
            "source": self.source,
            "subject": self.subject,
            "severity": self.severity,
            "occurred_at": self.occurred_at,
            "dedupe_key": self.dedupe_key,
            "payload": {} if self.sensitive else dict(self.payload),
            "sensitive": self.sensitive,
        }
