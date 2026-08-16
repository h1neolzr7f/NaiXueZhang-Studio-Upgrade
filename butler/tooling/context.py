from __future__ import annotations

from dataclasses import dataclass

from .errors import ErrorEnvelope, ToolingError
from .registry import ToolRegistry
from .spec import ToolSpec


@dataclass(frozen=True)
class ToolContext:
    agent_id: str
    source: str
    round_index: int
    allowed_names: frozenset[str]
    cancelled: bool = False

    @classmethod
    def build(
        cls,
        registry: ToolRegistry,
        *,
        agent_id: str,
        source: str,
        round_index: int,
        cancelled: bool = False,
    ) -> "ToolContext":
        if not agent_id:
            raise ToolingError(
                ErrorEnvelope(code="permission_denied", message="empty agent context is fail-closed")
            )
        allowed = frozenset(spec.name for spec in registry.list_for_agent(agent_id))
        return cls(
            agent_id=agent_id,
            source=source,
            round_index=round_index,
            allowed_names=allowed,
            cancelled=cancelled,
        )

    def authorize(self, spec: ToolSpec) -> None:
        if spec.name not in self.allowed_names:
            raise ToolingError(
                ErrorEnvelope(
                    code="permission_denied",
                    message=f"{self.agent_id} cannot use {spec.name}",
                    tool_name=spec.name,
                )
            )
