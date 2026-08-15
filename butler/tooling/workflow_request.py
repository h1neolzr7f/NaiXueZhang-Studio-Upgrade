from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkflowRequest:
    requested_by_agent: str
    intent: str
    proposed_tool: str
    proposed_arguments: dict[str, Any]
    risk: str
    reason: str
    request_id: str = field(default_factory=lambda: f"wr_{uuid4().hex}")
    schema_version: int = 1
    estimated_cost: dict[str, Any] = field(
        default_factory=lambda: {"anlas_estimate": "unknown", "retry_policy": "no-5xx-retry"}
    )
    source_evidence: tuple[dict[str, Any], ...] = ()
    requires_confirmation: bool = True
    idempotency_key: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "requested_by_agent": self.requested_by_agent,
            "intent": self.intent,
            "proposed_tool": self.proposed_tool,
            "proposed_arguments": dict(self.proposed_arguments),
            "risk": self.risk,
            "estimated_cost": dict(self.estimated_cost),
            "reason": self.reason,
            "source_evidence": [dict(item) for item in self.source_evidence],
            "requires_confirmation": True,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
        }
