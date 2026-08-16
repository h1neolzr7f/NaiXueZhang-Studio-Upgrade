"""Read-only catalog → ToolSpec projection.

This module never writes ``data/butler_catalog.json`` and never executes
tools. confirm / cost / destructive specs are durable WorkflowRequest
concepts only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from butler.agents import SAKIKO_TOOLS, TOMORI_TOOLS

from .spec import EXECUTABLE_RISKS, RISK_LEVELS, ToolSpec

CATALOG_RISK_MAP = {
    "read": "read",
    "draft": "draft",
    "auto": "read",
    "confirm": "confirm",
    "cost": "cost",
    "destructive": "destructive",
}

PAID_TOOLS = frozenset(
    {
        "generate_image",
        "batch_generate",
        "batch_director",
        "batch_generate_and_prepare_pixiv",
    }
)

DESTRUCTIVE_TOOLS = frozenset(
    {
        "delete_generated_item",
        "delete_generated_group",
    }
)

WORKFLOW_ONLY_RISKS = frozenset({"confirm", "cost", "destructive"})

_LOOSE_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "butler_catalog.json"


def read_catalog(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_catalog_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("catalog must be an object")
    return payload


def project_catalog_risk(name: str, catalog_risk: str) -> str:
    tool = str(name or "").strip()
    if tool in DESTRUCTIVE_TOOLS:
        return "destructive"
    if tool in PAID_TOOLS:
        return "cost"
    mapped = CATALOG_RISK_MAP.get(str(catalog_risk or "").strip())
    if mapped in RISK_LEVELS:
        return mapped
    return "confirm"


def allowed_agents_for(name: str) -> tuple[str, ...]:
    tool = str(name or "").strip()
    agents: list[str] = []
    if tool in SAKIKO_TOOLS:
        agents.append("sakiko")
    if tool in TOMORI_TOOLS:
        agents.append("tomori")
    return tuple(agents)


def is_workflow_only(risk: str) -> bool:
    return risk in WORKFLOW_ONLY_RISKS


def project_catalog_specs(
    catalog: Mapping[str, Any] | None = None,
    *,
    catalog_path: Path | None = None,
) -> list[ToolSpec]:
    payload = dict(catalog) if catalog is not None else read_catalog(catalog_path)
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("catalog.tools must be a list")
    specs: list[ToolSpec] = []
    seen: set[str] = set()
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        risk = project_catalog_risk(name, str(item.get("risk") or ""))
        description = str(item.get("description") or item.get("label") or name).strip() or name
        specs.append(
            ToolSpec(
                name=name,
                version="1",
                description=description,
                risk=risk,
                allowed_agents=allowed_agents_for(name),
                input_schema=dict(_LOOSE_OBJECT_SCHEMA),
                executor_domain="interactive" if risk in EXECUTABLE_RISKS else "durable",
                legacy_tool=name,
            )
        )
    return specs
