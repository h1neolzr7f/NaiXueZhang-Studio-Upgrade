from __future__ import annotations

from .errors import ErrorEnvelope, ToolingError
from .spec import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._order: list[str] = []

    def register(self, spec: ToolSpec) -> None:
        if spec.key in self._specs:
            raise ToolingError(
                ErrorEnvelope(
                    code="duplicate_tool",
                    message=f"tool already registered: {spec.key}",
                    tool_name=spec.name,
                )
            )
        self._specs[spec.key] = spec
        self._order.append(spec.key)

    def get(self, name: str, version: str | None = None) -> ToolSpec:
        if version:
            spec = self._specs.get(f"{name}@{version}")
            if spec is None:
                raise ToolingError(
                    ErrorEnvelope(code="unknown_tool", message=f"unknown tool: {name}@{version}", tool_name=name)
                )
            return spec
        matches = [self._specs[key] for key in self._order if self._specs[key].name == name]
        if not matches:
            raise ToolingError(ErrorEnvelope(code="unknown_tool", message=f"unknown tool: {name}", tool_name=name))
        return matches[-1]

    def list_for_agent(self, agent_id: str) -> list[ToolSpec]:
        return [
            self._specs[key]
            for key in self._order
            if agent_id in self._specs[key].allowed_agents or "shared" in self._specs[key].allowed_agents
        ]

    def keys(self) -> list[str]:
        return list(self._order)
