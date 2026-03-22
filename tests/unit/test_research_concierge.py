from __future__ import annotations

import json
import unittest
from uuid import uuid4

from eqorch.app.research_concierge import ResearchConcierge
from eqorch.domain import Memory, State
from eqorch.domain.policy import PolicyContext, RetryPolicy
from eqorch.gateways import LLMGateway
from eqorch.orchestrator import DecisionContextAssembler


class SequenceAdapter:
    def __init__(self, events):
        self._events = list(events)
        self.calls = 0

    def decide(self, payload):
        if not self._events:
            raise AssertionError("no more events configured")
        self.calls += 1
        event = self._events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def _action_response(action_type: str = "call_tool"):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        [
                            {
                                "type": action_type,
                                "target": "arxiv_search",
                                "parameters": {"query": "symbolic regression"},
                            }
                        ]
                    )
                }
            }
        ]
    }


def _context(*, mode: str = "interactive", max_retries: int = 1):
    state = State(
        current_mode=mode,
        policy_context=PolicyContext(
            goals=("goal",),
            retry=RetryPolicy(max_retries=max_retries, retry_interval_sec=1),
        ),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=str(uuid4()),
    )
    return DecisionContextAssembler().assemble(state)


class ResearchConciergeRetryTest(unittest.TestCase):
    def test_retries_retryable_failure_then_returns_actions(self) -> None:
        adapter = SequenceAdapter([TimeoutError("provider timed out"), _action_response()])
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=adapter))

        outcome = concierge.decide_with_retry(_context(max_retries=2), issued_at="2026-03-23T00:00:00Z")

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(len(outcome.actions), 1)
        self.assertEqual(outcome.actions[0].type, "call_tool")
        self.assertIsNone(outcome.coordinated_error)

    def test_interactive_mode_falls_back_to_ask_user_after_exhaustion(self) -> None:
        adapter = SequenceAdapter([TimeoutError("provider timed out"), TimeoutError("provider timed out")])
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=adapter))

        outcome = concierge.decide_with_retry(_context(mode="interactive", max_retries=1), issued_at="2026-03-23T00:00:00Z")

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(len(outcome.actions), 1)
        self.assertEqual(outcome.actions[0].type, "ask_user")
        self.assertIsNotNone(outcome.coordinated_error)
        self.assertTrue(outcome.coordinated_error.should_record_last_error)
        self.assertFalse(outcome.coordinated_error.should_stop)

    def test_batch_mode_falls_back_to_terminate_after_exhaustion(self) -> None:
        adapter = SequenceAdapter([TimeoutError("provider timed out"), TimeoutError("provider timed out")])
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=adapter))

        outcome = concierge.decide_with_retry(_context(mode="batch", max_retries=1), issued_at="2026-03-23T00:00:00Z")

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(len(outcome.actions), 1)
        self.assertEqual(outcome.actions[0].type, "terminate")
        self.assertIsNotNone(outcome.coordinated_error)
        self.assertFalse(outcome.coordinated_error.should_stop)

    def test_non_retryable_failure_skips_retry_and_returns_fallback(self) -> None:
        adapter = SequenceAdapter([PermissionError("bad credentials")])
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=adapter))

        outcome = concierge.decide_with_retry(_context(mode="interactive", max_retries=3), issued_at="2026-03-23T00:00:00Z")

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(outcome.attempts, 1)
        self.assertEqual(len(outcome.actions), 1)
        self.assertEqual(outcome.actions[0].type, "ask_user")
        self.assertEqual(outcome.coordinated_error.error.code, "LLM_AUTH_FAILED")
        self.assertTrue(outcome.coordinated_error.should_notify_user)


if __name__ == "__main__":
    unittest.main()
