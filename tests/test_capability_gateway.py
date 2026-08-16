from __future__ import annotations

import time
import unittest

from capability.delegation import DelegationError, DelegationStore
from capability.gateway import EXECUTION_WIRED, CapabilityGateway
from capability.orchestrator import Orchestrator


class CapabilityGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DelegationStore()
        self.gateway = CapabilityGateway(self.store)

    def test_service_cannot_generate_or_delete(self) -> None:
        self.assertEqual(self.gateway.decide("service", "nai.generate_paid").decision, "DENY")
        self.assertEqual(self.gateway.decide("service", "library.delete").decision, "DENY")
        self.assertEqual(self.gateway.decide("service", "library.search").decision, "ALLOW")

    def test_acquire_adjacent_library_needs_delegation(self) -> None:
        decision = self.gateway.decide("acquire", "asset.materialize")
        self.assertEqual(decision.decision, "DELEGATE")

    def test_delegation_replay_expiry_and_scope(self) -> None:
        token = self.store.issue(
            requester_agent="acquire",
            capability_id="asset.materialize",
            workflow_id="wf-1",
            provider_scope="synthetic",
            asset_scope="syn-1",
            payload_hash="abc",
            quantity_ceiling=1,
        )
        allowed = self.gateway.decide(
            "acquire",
            "asset.materialize",
            delegation_token=token.token_id,
            workflow_id="wf-1",
            provider_scope="synthetic",
            asset_scope="syn-1",
            payload_hash="abc",
        )
        self.assertEqual(allowed.decision, "ALLOW")
        replay = self.gateway.decide(
            "acquire",
            "asset.materialize",
            delegation_token=token.token_id,
            workflow_id="wf-1",
            provider_scope="synthetic",
            asset_scope="syn-1",
            payload_hash="abc",
        )
        self.assertEqual(replay.decision, "DENY")
        self.assertIn("already used", replay.reason)

        expired = self.store.issue(
            requester_agent="acquire",
            capability_id="asset.materialize",
            workflow_id="wf-2",
            ttl_seconds=30,
        )
        expired.expires_at = time.time() - 1
        self.store._items[expired.token_id] = expired
        late = self.gateway.decide(
            "acquire",
            "asset.materialize",
            delegation_token=expired.token_id,
            workflow_id="wf-2",
        )
        self.assertEqual(late.decision, "DENY")
        self.assertIn("expired", late.reason)

        scoped = self.store.issue(
            requester_agent="library",
            capability_id="transform.character_replace",
            workflow_id="wf-3",
            asset_scope="work:1",
            payload_hash="p1",
        )
        mismatch = self.gateway.decide(
            "library",
            "transform.character_replace",
            delegation_token=scoped.token_id,
            workflow_id="wf-3",
            asset_scope="work:2",
            payload_hash="p1",
        )
        self.assertEqual(mismatch.decision, "DENY")
        changed = self.gateway.decide(
            "library",
            "transform.character_replace",
            delegation_token=scoped.token_id,
            workflow_id="wf-3",
            asset_scope="work:1",
            payload_hash="p2",
        )
        self.assertEqual(changed.decision, "DENY")

    def test_orchestrator_cannot_execute(self) -> None:
        orch = Orchestrator(self.gateway)
        self.assertEqual(orch.execute_denied("library.search").decision, "DENY")
        routed = orch.route("帮我在线搜索角色", from_persona="service")
        self.assertEqual(routed["target_persona"], "acquire")
        self.assertEqual(routed["capability_id"], "provider.search")

    def test_studio_paid_needs_confirm_workflow(self) -> None:
        decision = self.gateway.decide("studio", "nai.generate_paid", confirmed=True)
        self.assertEqual(decision.decision, "CONFIRM")
        self.assertTrue(decision.workflow_request)

    def test_orchestrator_http_route_cannot_grant_execution(self) -> None:
        from tests.asgi_client import TestClient

        import server

        client = TestClient(server.app)
        denied = client.post(
            "/api/capability/decide",
            json={"persona_id": "orchestrator", "capability_id": "nai.generate_paid"},
        )
        self.assertEqual(denied.status_code, 200)
        self.assertEqual(denied.json()["decision"], "DENY")
        routed = client.post(
            "/api/capability/route",
            json={"user_intent": "帮我删除图库", "from_persona": "service"},
        )
        self.assertEqual(routed.status_code, 200)
        body = routed.json()
        self.assertEqual(body["capability_id"], "library.delete")
        self.assertEqual(body["decision"], "DENY")

    def test_capability_is_decision_prototype_not_execution(self) -> None:
        self.assertFalse(EXECUTION_WIRED)
        from tests.asgi_client import TestClient

        import server

        client = TestClient(server.app)
        response = client.post(
            "/api/capability/decide",
            json={"persona_id": "studio", "capability_id": "nai.generate_paid", "confirmed": True},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["decision"], "CONFIRM")
        self.assertFalse(body["execution_wired"])
        self.assertTrue(body["prototype"])
