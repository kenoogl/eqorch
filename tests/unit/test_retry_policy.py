from __future__ import annotations

import unittest

from eqorch.app import RetryPolicyExecutor
from eqorch.domain import ErrorInfo
from eqorch.domain.policy import PolicyContext, RetryPolicy


class RetryPolicyExecutorTest(unittest.TestCase):
    def test_retries_before_exhaustion(self) -> None:
        executor = RetryPolicyExecutor()
        decision = executor.evaluate_llm_failure(
            policy=PolicyContext(goals=("goal",), retry=RetryPolicy(max_retries=3, retry_interval_sec=5)),
            current_mode="interactive",
            attempt=1,
            error=ErrorInfo(code="TIMEOUT", message="timeout", retryable=True),
            issued_at="2026-03-22T00:00:00Z",
        )

        self.assertTrue(decision.should_retry)
        self.assertEqual(decision.wait_seconds, 5)
        self.assertIsNone(decision.fallback_action)

    def test_interactive_falls_back_to_ask_user_after_exhaustion(self) -> None:
        executor = RetryPolicyExecutor()
        decision = executor.evaluate_llm_failure(
            policy=PolicyContext(goals=("goal",), retry=RetryPolicy(max_retries=2, retry_interval_sec=5)),
            current_mode="interactive",
            attempt=2,
            error=ErrorInfo(code="TIMEOUT", message="timeout", retryable=True),
            issued_at="2026-03-22T00:00:00Z",
        )

        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.fallback_action.type, "ask_user")

    def test_batch_falls_back_to_terminate_after_exhaustion(self) -> None:
        executor = RetryPolicyExecutor()
        decision = executor.evaluate_llm_failure(
            policy=PolicyContext(goals=("goal",), retry=RetryPolicy(max_retries=1, retry_interval_sec=5)),
            current_mode="batch",
            attempt=1,
            error=ErrorInfo(code="TIMEOUT", message="timeout", retryable=True),
            issued_at="2026-03-22T00:00:00Z",
        )

        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.fallback_action.type, "terminate")

    def test_non_retryable_error_skips_retry(self) -> None:
        executor = RetryPolicyExecutor()
        decision = executor.evaluate_llm_failure(
            policy=PolicyContext(goals=("goal",)),
            current_mode="interactive",
            attempt=0,
            error=ErrorInfo(code="BAD_REQUEST", message="bad", retryable=False),
            issued_at="2026-03-22T00:00:00Z",
        )

        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.fallback_action.type, "ask_user")


if __name__ == "__main__":
    unittest.main()
