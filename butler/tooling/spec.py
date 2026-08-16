from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

RISK_LEVELS = ("read", "draft", "confirm", "cost", "destructive")
EXECUTABLE_RISKS = ("read", "draft")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    risk: str
    allowed_agents: tuple[str, ...]
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    timeout_ms: int = 15_000
    idempotency: str = "none"
    executor_domain: str = "interactive"
    required_capabilities: tuple[str, ...] = ()
    redact_paths: tuple[str, ...] = ()
    result_size_limit: int = 8_000
    legacy_tool: str = ""

    def __post_init__(self) -> None:
        if self.risk not in RISK_LEVELS:
            raise ValueError(f"unsupported risk: {self.risk}")
        if not self.name:
            raise ValueError("tool name is required")
        if not self.version:
            raise ValueError("tool version is required")

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def interactive_executable(self) -> bool:
        return self.risk in EXECUTABLE_RISKS and self.executor_domain == "interactive"
