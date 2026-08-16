"""Kernel-only tools. Not imported by ``butler.planning``."""

from __future__ import annotations

import sqlite3
from typing import Any

from nai_char_modules.generation import build_generate_payload

from .executor import ToolExecutor
from .registry import ToolRegistry
from .spec import ToolSpec

KERNEL_SPECS = (
    ToolSpec(
        name="compile_nai_preview",
        version="1",
        description="Compile a NovelAI comment without sending HTTP",
        risk="read",
        allowed_agents=("tomori", "shared"),
        input_schema={
            "type": "object",
            "required": ["comment"],
            "additionalProperties": False,
            "properties": {
                "comment": {"type": "object"},
                "force_free": {"type": "boolean"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["action", "requested_action", "unsupported_fields", "unknown_fields"],
            "properties": {
                "action": {"type": "string"},
                "requested_action": {"type": "string"},
                "unsupported_fields": {"type": "array"},
                "unknown_fields": {"type": "array"},
                "free_eligible": {"type": "boolean"},
                "model": {"type": "string"},
            },
        },
        idempotency="keyed",
        timeout_ms=5_000,
        result_size_limit=4_000,
    ),
    ToolSpec(
        name="gallery_index_preview",
        version="1",
        description="In-memory dirty/dup/similar preview; no butler store",
        risk="read",
        allowed_agents=("sakiko", "tomori", "shared"),
        input_schema={
            "type": "object",
            "required": ["items"],
            "additionalProperties": False,
            "properties": {
                "items": {"type": "array"},
                "query_work_id": {"type": "integer"},
            },
        },
        idempotency="keyed",
        timeout_ms=8_000,
    ),
)


def compile_nai_preview(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    comment = arguments.get("comment") or {}
    if not isinstance(comment, dict):
        comment = {}
    force_free = arguments.get("force_free", True)
    payload = build_generate_payload(comment, force_free=bool(force_free))
    return {
        "action": payload["action"],
        "requested_action": payload["requested_action"],
        "unsupported_fields": payload["unsupported_fields"],
        "unknown_fields": payload["unknown_fields"],
        "free_eligible": payload["free_eligible"],
        "model": payload["model"],
        "width": payload["width"],
        "height": payload["height"],
        "steps": payload["steps"],
    }


def gallery_index_preview(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    from gallery_index import IndexImage, find_exact_duplicates, find_similar, index_images

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    items = []
    for raw in arguments.get("items") or []:
        if not isinstance(raw, dict):
            continue
        items.append(
            IndexImage(
                work_id=int(raw.get("work_id") or 0),
                page_index=int(raw.get("page_index") or 0),
                source_sha256=str(raw.get("source_sha256") or ""),
            )
        )
    summary = index_images(conn, items, visual_enabled=False)
    duplicates = find_exact_duplicates(conn)
    query_id = arguments.get("query_work_id")
    similar = (
        find_similar(conn, work_id=int(query_id))
        if isinstance(query_id, int)
        else {"items": []}
    )
    conn.close()
    return {
        "scanned": summary["scanned"],
        "text_dirty": summary["text_dirty"],
        "duplicates": duplicates,
        "similar": similar.get("items") or [],
        "embed": {"provider": "local_none", "outbound": False},
    }


def bind_kernel_tools(registry: ToolRegistry, executor: ToolExecutor) -> None:
    for spec in KERNEL_SPECS:
        registry.register(spec)
    executor.bind("compile_nai_preview", compile_nai_preview)
    executor.bind("gallery_index_preview", gallery_index_preview)
