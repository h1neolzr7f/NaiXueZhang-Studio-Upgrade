"""Agent Capability Control Plane. Personas do not equal permissions."""

from .delegation import DelegationError, DelegationStore, issue_delegation, consume_delegation
from .gateway import CapabilityDecision, CapabilityGateway
from .handoff import TypedHandoff
from .orchestrator import Orchestrator
from .personas import PERSONAS, persona_defaults
from .registry import CAPABILITIES, CapabilitySpec, get_capability

__all__ = [
    "CAPABILITIES",
    "CapabilityDecision",
    "CapabilityGateway",
    "CapabilitySpec",
    "DelegationError",
    "DelegationStore",
    "Orchestrator",
    "PERSONAS",
    "TypedHandoff",
    "consume_delegation",
    "get_capability",
    "issue_delegation",
    "persona_defaults",
]
