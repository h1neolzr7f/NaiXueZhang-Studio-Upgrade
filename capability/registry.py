from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Risk = Literal["read", "write", "cost", "destructive"]
Confirm = Literal["none", "user", "ticket", "delegation"]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    capability_id: str
    risk: Risk
    gui_visible: bool
    agent_callable: bool
    confirmation: Confirm
    durable: bool
    audit: bool
    description: str


CAPABILITIES: dict[str, CapabilitySpec] = {
    spec.capability_id: spec
    for spec in (
        CapabilitySpec("provider.search", "read", True, True, "none", False, True, "Search a remote provider"),
        CapabilitySpec("provider.fetch", "read", True, True, "none", False, True, "Fetch remote metadata"),
        CapabilitySpec("crawler.start", "write", True, True, "user", True, True, "Start an acquire adapter"),
        CapabilitySpec("crawler.stop", "write", True, True, "user", True, True, "Stop an acquire adapter"),
        CapabilitySpec("asset.preview", "read", True, True, "none", False, False, "Preview a remote or local asset"),
        CapabilitySpec("asset.materialize", "write", True, True, "user", True, True, "Add to My Library"),
        CapabilitySpec("library.search", "read", True, True, "none", False, False, "Search local library"),
        CapabilitySpec("library.collection.add", "write", True, True, "none", False, True, "Add to a collection"),
        CapabilitySpec("library.delete", "destructive", True, True, "user", True, True, "Delete local assets"),
        CapabilitySpec("transform.character_replace", "cost", True, True, "ticket", True, True, "Batch character replace"),
        CapabilitySpec("nai.generate", "cost", True, True, "ticket", True, True, "Free-eligible generate"),
        CapabilitySpec("nai.generate_paid", "cost", True, True, "ticket", True, True, "Non-free generate"),
        CapabilitySpec("post.upscale", "write", True, True, "user", True, True, "Post-process upscale"),
        CapabilitySpec("publish.pixiv", "write", True, True, "user", True, True, "Prepare Pixiv draft"),
        CapabilitySpec("acquire.plan", "write", False, True, "user", True, True, "Agent-only acquisition plan"),
    )
}


def get_capability(capability_id: str) -> CapabilitySpec:
    spec = CAPABILITIES.get(str(capability_id or ""))
    if spec is None:
        raise KeyError(f"unknown capability: {capability_id}")
    return spec
