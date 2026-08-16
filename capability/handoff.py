from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TypedHandoff:
    selection: list[dict[str, Any]] = field(default_factory=list)
    user_intent: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    granted_capabilities: list[str] = field(default_factory=list)
    workflow_ref: str = ""
    from_persona: str = ""
    to_persona: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TypedHandoff":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            selection=list(data.get("selection") or []),
            user_intent=str(data.get("user_intent") or ""),
            provenance=dict(data.get("provenance") or {}),
            scope=dict(data.get("scope") or {}),
            granted_capabilities=list(data.get("granted_capabilities") or []),
            workflow_ref=str(data.get("workflow_ref") or ""),
            from_persona=str(data.get("from_persona") or ""),
            to_persona=str(data.get("to_persona") or ""),
        )
