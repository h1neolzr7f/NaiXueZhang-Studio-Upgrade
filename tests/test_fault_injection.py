from __future__ import annotations

import unittest

from generation_jobs import partition_retry_targets
from nai.errors import GenerationProviderError


class FaultInjectionTests(unittest.TestCase):
    def test_timeout_after_send_is_billing_uncertain_and_not_auto_retried(self) -> None:
        error = GenerationProviderError(
            "NAI request timed out after send",
            retry_safe=False,
            billing_uncertain=True,
            request_attempted=True,
            error_code="billing_uncertain",
        )
        self.assertTrue(error.billing_uncertain)
        self.assertFalse(error.retry_safe)
        self.assertTrue(error.request_attempted)

    def test_connect_failure_before_send_is_retry_safe(self) -> None:
        error = GenerationProviderError(
            "TLS/connect failed before request was sent",
            retry_safe=True,
            billing_uncertain=False,
            request_attempted=False,
            error_code="connect_failed",
        )
        self.assertFalse(error.billing_uncertain)
        self.assertTrue(error.retry_safe)
        self.assertFalse(error.request_attempted)

    def test_unknown_recovered_job_indexes_are_blocked(self) -> None:
        retryable, blocked = partition_retry_targets(
            [{"work_id": 1}, {"work_id": 2}],
            [],
            status="unknown",
            recovered_after_restart=True,
        )
        self.assertEqual(retryable, [])
        self.assertEqual(blocked, [0, 1])

    def test_billing_uncertain_item_is_blocked_even_when_job_errored(self) -> None:
        retryable, blocked = partition_retry_targets(
            [{"work_id": 1}],
            [{"target_index": 0, "ok": False, "billing_uncertain": True, "retry_safe": False}],
            status="error",
        )
        self.assertEqual(retryable, [])
        self.assertEqual(blocked, [0])
