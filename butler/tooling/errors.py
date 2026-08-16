from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorEnvelope:
    code: str
    message: str
    retryable: bool = False
    isolation: str = "none"
    tool_name: str = ""
    call_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    redactions: tuple[str, ...] = ()
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "schema_version": self.schema_version,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "isolation": self.isolation,
            "tool_name": self.tool_name,
            "call_id": self.call_id,
            "details": dict(self.details),
            "redactions": list(self.redactions),
        }


class ToolingError(Exception):
    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.message)
        self.envelope = envelope
