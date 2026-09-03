from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .context import ToolContext
from .errors import ErrorEnvelope, ToolingError
from .events import EventEnvelope
from .registry import ToolRegistry
from .spec import ToolSpec
from .workflow_request import WorkflowRequest

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{10,}|pst-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._\-]+)", re.I)

Handler = Callable[[dict[str, Any], ToolContext], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return SECRET_RE.sub("[redacted]", value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _validate_object(data: dict[str, Any], schema: dict[str, Any], tool_name: str) -> None:
    if not schema:
        return
    if schema.get("type", "object") != "object":
        return
    required = schema.get("required") or []
    for key in required:
        if key not in data:
            raise ToolingError(
                ErrorEnvelope(code="schema_invalid", message=f"missing field: {key}", tool_name=tool_name)
            )
    properties = schema.get("properties") or {}
    additional = schema.get("additionalProperties", True)
    for key, value in data.items():
        if key not in properties and additional is False:
            raise ToolingError(
                ErrorEnvelope(code="schema_invalid", message=f"unexpected field: {key}", tool_name=tool_name)
            )
        expected = (properties.get(key) or {}).get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolingError(
                ErrorEnvelope(code="schema_invalid", message=f"{key} must be a string", tool_name=tool_name)
            )
        if expected == "integer" and not isinstance(value, int):
            raise ToolingError(
                ErrorEnvelope(code="schema_invalid", message=f"{key} must be an integer", tool_name=tool_name)
            )


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._handlers: dict[str, Handler] = {}
        self.events: list[EventEnvelope] = []

    def bind(self, name: str, handler: Handler, version: str = "1") -> None:
        self._handlers[f"{name}@{version}"] = handler
        self._handlers[name] = handler

    def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        call_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        call_id = call_id or f"call_{uuid4().hex}"
        started = _now()
        try:
            spec = self.registry.get(name)
            context.authorize(spec)
            _validate_object(arguments, dict(spec.input_schema), spec.name)
            if not spec.interactive_executable:
                request = WorkflowRequest(
                    requested_by_agent=context.agent_id,
                    intent=spec.risk,
                    proposed_tool=spec.name,
                    proposed_arguments=dict(arguments),
                    risk=spec.risk,
                    reason=reason or f"{spec.name} requires durable confirmation",
                )
                result = {
                    "call_id": call_id,
                    "tool_name": spec.name,
                    "tool_version": spec.version,
                    "status": "workflow_requested",
                    "started_at": started,
                    "finished_at": _now(),
                    "data": {},
                    "error": None,
                    "redactions": [],
                    "truncated": False,
                    "next_cursor": None,
                    "workflow_request": request.to_dict(),
                }
                self._record("tool.workflow_requested", spec, call_id, context)
                return result
            handler = self._handlers.get(spec.key) or self._handlers.get(spec.name)
            if handler is None:
                raise ToolingError(
                    ErrorEnvelope(code="unknown_tool", message=f"no handler bound for {spec.name}", tool_name=spec.name)
                )
            raw = handler(dict(arguments), context)
            data, truncated, redactions = self._limit_and_redact(raw, spec)
            result = {
                "call_id": call_id,
                "tool_name": spec.name,
                "tool_version": spec.version,
                "status": "succeeded",
                "started_at": started,
                "finished_at": _now(),
                "data": data,
                "error": None,
                "redactions": redactions,
                "truncated": truncated,
                "next_cursor": data.get("next_cursor") if isinstance(data, dict) else None,
                "workflow_request": None,
            }
            self._record("tool.succeeded", spec, call_id, context)
            return result
        except ToolingError as exc:
            envelope = exc.envelope
            return {
                "call_id": call_id,
                "tool_name": name,
                "tool_version": "",
                "status": "denied" if envelope.code == "permission_denied" else "failed",
                "started_at": started,
                "finished_at": _now(),
                "data": {},
                "error": envelope.to_dict(),
                "redactions": list(envelope.redactions),
                "truncated": False,
                "next_cursor": None,
                "workflow_request": None,
            }

    def _limit_and_redact(self, raw: dict[str, Any], spec: ToolSpec) -> tuple[dict[str, Any], bool, list[str]]:
        data = _redact(raw)
        redactions = ["token"] if raw != data else []
        text = str(data)
        truncated = len(text) > spec.result_size_limit
        if truncated:
            data = {"summary": text[: spec.result_size_limit], "truncated": True}
        return data, truncated, redactions

    def _record(self, event_type: str, spec: ToolSpec, call_id: str, context: ToolContext) -> None:
        self.events.append(
            EventEnvelope(
                type=event_type,
                source="interactive_agent",
                subject=f"agent:{context.agent_id}",
                dedupe_key=f"loop:{context.round_index}:call:{call_id}",
                payload={"tool_name": spec.name, "call_id": call_id},
            )
        )
