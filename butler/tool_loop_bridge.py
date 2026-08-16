"""Safe chat adapter for the Tool Kernel.

Does not import ``butler.planning``. Cost and destructive tools never execute
here; they become ``WorkflowRequest``. Kernel read tools go through
``ToolExecutor`` (timeout, agent allow-list, keyed idempotency).
"""

from __future__ import annotations

from typing import Any

from butler.agents import current_agent
from butler.tooling import (
    ToolContext,
    ToolExecutor,
    ToolRegistry,
    WorkflowRequest,
    bind_kernel_tools,
)

KERNEL_READ_TOOLS = frozenset({"compile_nai_preview", "gallery_index_preview"})
COST_OR_DESTRUCTIVE = frozenset(
    {
        "generate_image",
        "batch_generate",
        "batch_director",
        "batch_generate_and_prepare_pixiv",
        "start_crawler",
        "delete_generated_item",
        "delete_generated_group",
        "run_pipeline",
    }
)

_REGISTRY: ToolRegistry | None = None
_EXECUTOR: ToolExecutor | None = None


def _runtime() -> tuple[ToolRegistry, ToolExecutor]:
    global _REGISTRY, _EXECUTOR
    if _REGISTRY is None or _EXECUTOR is None:
        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        bind_kernel_tools(registry, executor)
        _REGISTRY = registry
        _EXECUTOR = executor
    return _REGISTRY, _EXECUTOR


def execute_chat_action(action: dict[str, Any], *, agent_id: str = "") -> dict[str, Any] | None:
    """Handle a planned chat action through the kernel, or return None.

    ``None`` means the caller should keep the existing auto/confirm path.
    """

    tool = str(action.get("tool") or "").strip()
    if not tool:
        return None
    agent = str(agent_id or current_agent() or "shared")
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if tool in COST_OR_DESTRUCTIVE:
        request = WorkflowRequest(
            requested_by_agent=agent,
            intent="cost" if "generate" in tool or tool == "start_crawler" else "destructive",
            proposed_tool=tool,
            proposed_arguments=dict(arguments),
            risk="cost" if "generate" in tool else "destructive",
            reason="chat loop must not execute paid or destructive tools",
        )
        return {
            "status": "workflow_requested",
            "tool": tool,
            "workflow_request": request.to_dict(),
            "message": "付费或破坏性动作只产 WorkflowRequest，聊天循环不会直接执行。",
        }
    if tool not in KERNEL_READ_TOOLS:
        return None
    registry, executor = _runtime()
    context = ToolContext.build(registry, agent_id=agent, source="chat", round_index=1)
    return executor.execute(
        name=tool,
        arguments=arguments,
        context=context,
        call_id=str(action.get("call_id") or ""),
        reason=str(action.get("reason") or "chat kernel preview"),
    )
