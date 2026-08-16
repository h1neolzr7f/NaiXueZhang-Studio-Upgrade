from __future__ import annotations

from typing import Any

from .gateway import CapabilityDecision, CapabilityGateway
from .handoff import TypedHandoff


class Orchestrator:
    """Understand → Plan → Route → Request Delegation → Track → Present.

    Never executes crawler/generator/library SQL and never bypasses the gateway.
    """

    def __init__(self, gateway: CapabilityGateway | None = None) -> None:
        self.gateway = gateway or CapabilityGateway()

    def route(self, user_intent: str, *, from_persona: str = "service") -> dict[str, Any]:
        intent = str(user_intent or "").lower()
        if any(token in intent for token in ("采集", "搜索", "在线", "crawl", "search")):
            target = "acquire"
            capability = "provider.search"
        elif any(token in intent for token in ("换角", "出图", "生成", "generate", "remix")):
            target = "studio"
            capability = "transform.character_replace" if "换角" in intent or "remix" in intent else "nai.generate"
        elif any(token in intent for token in ("删除", "delete")):
            target = "library"
            capability = "library.delete"
        else:
            target = "library"
            capability = "library.search"
        handoff = TypedHandoff(
            user_intent=user_intent,
            from_persona=from_persona,
            to_persona=target,
            granted_capabilities=[],
        )
        decision = self.gateway.decide(from_persona, capability)
        return {
            "ok": True,
            "target_persona": target,
            "capability_id": capability,
            "decision": decision.decision,
            "handoff": handoff.to_dict(),
            "workflow_request": decision.workflow_request,
        }

    def execute_denied(self, capability_id: str) -> CapabilityDecision:
        return self.gateway.decide("orchestrator", capability_id)
