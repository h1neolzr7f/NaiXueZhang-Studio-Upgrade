from __future__ import annotations

from typing import Any, Callable

from .context import ToolContext
from .errors import ErrorEnvelope, ToolingError
from .executor import ToolExecutor
from .registry import ToolRegistry

MAX_ROUNDS = 4

Planner = Callable[[ToolContext, list[dict[str, Any]]], dict[str, Any] | None]


class InteractiveLoop:
    def __init__(self, registry: ToolRegistry, executor: ToolExecutor, planner: Planner) -> None:
        self.registry = registry
        self.executor = executor
        self.planner = planner

    def run(self, *, agent_id: str | Callable[[], str], source: str = "chat") -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        for round_index in range(1, MAX_ROUNDS + 1):
            current_agent = agent_id() if callable(agent_id) else agent_id
            context = ToolContext.build(
                self.registry, agent_id=current_agent, source=source, round_index=round_index
            )
            planned = self.planner(context, results)
            if not planned:
                return {"status": "done", "rounds": round_index - 1, "results": results}
            call_id = str(planned.get("call_id") or "")
            if call_id and call_id in seen_calls:
                results.append(
                    {
                        "status": "failed",
                        "error": ErrorEnvelope(
                            code="schema_invalid", message="duplicate call id", call_id=call_id
                        ).to_dict(),
                    }
                )
                return {"status": "done", "rounds": round_index, "results": results}
            if call_id:
                seen_calls.add(call_id)
            result = self.executor.execute(
                name=str(planned.get("tool") or ""),
                arguments=dict(planned.get("arguments") or {}),
                context=context,
                call_id=call_id,
                reason=str(planned.get("reason") or ""),
            )
            results.append(result)
            if result.get("status") == "workflow_requested":
                return {"status": "workflow_requested", "rounds": round_index, "results": results}
        raise ToolingError(
            ErrorEnvelope(code="loop_limit", message="interactive tool loop reached the 4-round limit")
        )
