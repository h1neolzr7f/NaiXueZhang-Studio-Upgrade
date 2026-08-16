from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


DELEGATION_TTL_SECONDS = 600


class DelegationError(ValueError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass
class DelegationToken:
    token_id: str
    requester_agent: str
    capability_id: str
    workflow_id: str
    provider_scope: str = ""
    asset_scope: str = ""
    quantity_ceiling: int = 1
    expires_at: float = 0.0
    payload_hash: str = ""
    consumed: bool = False


class DelegationStore:
    def __init__(self) -> None:
        self._items: dict[str, DelegationToken] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        requester_agent: str,
        capability_id: str,
        workflow_id: str,
        provider_scope: str = "",
        asset_scope: str = "",
        quantity_ceiling: int = 1,
        payload_hash: str = "",
        ttl_seconds: int = DELEGATION_TTL_SECONDS,
    ) -> DelegationToken:
        token = DelegationToken(
            token_id=secrets.token_urlsafe(16),
            requester_agent=str(requester_agent),
            capability_id=str(capability_id),
            workflow_id=str(workflow_id),
            provider_scope=str(provider_scope or ""),
            asset_scope=str(asset_scope or ""),
            quantity_ceiling=max(1, int(quantity_ceiling)),
            expires_at=time.time() + max(30, int(ttl_seconds)),
            payload_hash=str(payload_hash or ""),
        )
        with self._lock:
            self._items[token.token_id] = token
        return token

    def consume(
        self,
        token_id: str,
        *,
        capability_id: str,
        workflow_id: str,
        provider_scope: str = "",
        asset_scope: str = "",
        payload_hash: str = "",
        quantity: int = 1,
    ) -> DelegationToken:
        with self._lock:
            token = self._items.get(str(token_id or ""))
            if token is None:
                raise DelegationError("delegation token is invalid", error_code="delegation_invalid")
            if token.consumed:
                raise DelegationError("delegation token already used", error_code="delegation_replay")
            if token.expires_at < time.time():
                raise DelegationError("delegation token has expired", error_code="delegation_expired")
            if token.capability_id != capability_id or token.workflow_id != workflow_id:
                raise DelegationError("delegation scope mismatch", error_code="delegation_scope")
            if token.provider_scope and token.provider_scope != provider_scope:
                raise DelegationError("delegation provider scope mismatch", error_code="delegation_scope")
            if token.asset_scope and token.asset_scope != asset_scope:
                raise DelegationError("delegation asset scope mismatch", error_code="delegation_scope")
            if token.payload_hash and token.payload_hash != payload_hash:
                raise DelegationError("delegation payload changed", error_code="delegation_payload")
            if int(quantity) > token.quantity_ceiling:
                raise DelegationError("delegation quantity exceeds ceiling", error_code="delegation_scope")
            token.consumed = True
            return token


_STORE = DelegationStore()


def issue_delegation(**kwargs: Any) -> DelegationToken:
    return _STORE.issue(**kwargs)


def consume_delegation(token_id: str, **kwargs: Any) -> DelegationToken:
    return _STORE.consume(token_id, **kwargs)


def reset_delegation_store_for_tests() -> None:
    _STORE._items.clear()
