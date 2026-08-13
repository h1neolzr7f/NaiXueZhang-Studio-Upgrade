"""Durable intelligent-butler workflow package.

Implementation modules (`config_ops`, `normalize`, `planning`, ...) are imported
by :mod:`butler_service`. Workflow exports stay lazy so that import does not
cycle through :mod:`butler.workflow` while the facade is still loading.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "cancel_butler_task",
    "butler_task_revision",
    "clear_butler_messages",
    "close_butler_runtime",
    "confirm_butler_action",
    "get_butler_task",
    "list_butler_tasks",
    "list_butler_messages",
    "resume_butler_task",
    "retry_butler_task",
    "start_butler_runtime",
    "submit_butler_chat",
    "submit_knowledge_rebuild",
    "workflow_runtime_status",
    "wait_for_butler_task_change",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import workflow

        return getattr(workflow, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals()) + __all__)
