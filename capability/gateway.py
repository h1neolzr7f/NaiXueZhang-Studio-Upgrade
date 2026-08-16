from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .delegation import DelegationError, DelegationStore, consume_delegation
from .personas import persona_defaults
from .registry import get_capability

Decision = Literal["ALLOW", "CONFIRM", "DELEGATE", "DENY"]


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    decision: Decision
    capability_id: str
    persona_id: str
    reason: str
    workflow_request: bool = False


class CapabilityGateway:
    def __init__(self, store: DelegationStore | None = None) -> None:
        self.store = store

    def decide(
        self,
        persona_id: str,
        capability_id: str,
        *,
        confirmed: bool = False,
        delegation_token: str = "",
        workflow_id: str = "",
        provider_scope: str = "",
        asset_scope: str = "",
        payload_hash: str = "",
        quantity: int = 1,
    ) -> CapabilityDecision:
        if persona_id == "orchestrator":
            return CapabilityDecision(
                "DENY",
                capability_id,
                persona_id,
                "orchestrator cannot execute capabilities",
            )
        try:
            spec = get_capability(capability_id)
        except KeyError:
            return CapabilityDecision("DENY", capability_id, persona_id, "unknown capability")
        access = persona_defaults(persona_id).get(capability_id, "deny")
        if access == "deny":
            return CapabilityDecision("DENY", capability_id, persona_id, "persona is denied this capability")
        if access == "primary" and spec.confirmation == "none":
            return CapabilityDecision("ALLOW", capability_id, persona_id, "primary low-risk")
        if access == "adjacent" and spec.confirmation == "none":
            return CapabilityDecision("ALLOW", capability_id, persona_id, "adjacent low-risk")
        if access == "restricted" or spec.confirmation in {"user", "ticket", "delegation"}:
            if delegation_token:
                try:
                    consumer = self.store.consume if self.store is not None else consume_delegation
                    consumer(
                        delegation_token,
                        capability_id=capability_id,
                        workflow_id=workflow_id,
                        provider_scope=provider_scope,
                        asset_scope=asset_scope,
                        payload_hash=payload_hash,
                        quantity=quantity,
                    )
                except DelegationError as exc:
                    return CapabilityDecision("DENY", capability_id, persona_id, str(exc))
                return CapabilityDecision("ALLOW", capability_id, persona_id, "delegation accepted")
            if confirmed and spec.confirmation in {"user", "ticket"}:
                return CapabilityDecision(
                    "CONFIRM",
                    capability_id,
                    persona_id,
                    "user confirmed; emit workflow request",
                    workflow_request=True,
                )
            if access == "adjacent" or access == "restricted":
                return CapabilityDecision(
                    "DELEGATE",
                    capability_id,
                    persona_id,
                    "cross-domain capability needs delegation or confirmation",
                )
            return CapabilityDecision(
                "CONFIRM",
                capability_id,
                persona_id,
                "high-risk capability needs confirmation",
                workflow_request=True,
            )
        return CapabilityDecision("ALLOW", capability_id, persona_id, "allowed")
