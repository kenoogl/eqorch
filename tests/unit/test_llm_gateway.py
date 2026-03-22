from __future__ import annotations

import json
import unittest
from uuid import uuid4

from eqorch.app.research_concierge import DecisionSupportAdapter, ResearchConcierge
from eqorch.domain import Memory, State
from eqorch.domain.policy import PolicyContext
from eqorch.gateways import LLMGateway, LLMGatewayError
from eqorch.orchestrator import DecisionContextAssembler


class OpenAIStub:
    def decide(self, payload):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [
                                {
                                    "type": "call_tool",
                                    "target": "arxiv_search",
                                    "parameters": {"query": "symbolic regression"},
                                }
                            ]
                        )
                    }
                }
            ]
        }


class AnthropicStub:
    def decide(self, payload):
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        [
                            {
                                "type": "run_engine",
                                "target": "symbolic_regression",
                                "parameters": {"instruction": "search equation"},
                            }
                        ]
                    ),
                }
            ]
        }


class MarkerAdapter(DecisionSupportAdapter):
    def augment(self, context):
        return context


class GoogleStub:
    def decide(self, payload):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    [
                                        {
                                            "type": "call_skill",
                                            "target": "critic",
                                            "parameters": {"input": {"focus": "novelty"}},
                                        }
                                    ]
                                )
                            }
                        ]
                    }
                }
            ]
        }


class TimeoutStub:
    def decide(self, payload):
        raise TimeoutError("provider timed out")


class AuthFailureStub:
    def decide(self, payload):
        raise PermissionError("bad credentials")


class MalformedResponseStub:
    def decide(self, payload):
        return {"choices": [{"message": {"content": "{\"type\": \"call_tool\"}"}}]}


def _context():
    state = State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=str(uuid4()),
    )
    return DecisionContextAssembler().assemble(state)


class LLMGatewayTest(unittest.TestCase):
    def test_normalizes_openai_compatible_response(self) -> None:
        gateway = LLMGateway(provider="openai", adapter=OpenAIStub())

        actions = gateway.decide(_context())

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "call_tool")
        self.assertEqual(actions[0].target, "arxiv_search")

    def test_normalizes_anthropic_compatible_response(self) -> None:
        gateway = LLMGateway(provider="anthropic", adapter=AnthropicStub())

        actions = gateway.decide(_context())

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "run_engine")
        self.assertEqual(actions[0].target, "symbolic_regression")

    def test_research_concierge_requires_non_empty_actions(self) -> None:
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=OpenAIStub()), support_adapters=(MarkerAdapter(),))

        actions = concierge.decide(_context())

        self.assertGreaterEqual(len(actions), 1)

    def test_normalizes_google_compatible_response(self) -> None:
        gateway = LLMGateway(provider="google", adapter=GoogleStub())

        actions = gateway.decide(_context())

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].type, "call_skill")
        self.assertEqual(actions[0].parameters["input"], {"focus": "novelty"})

    def test_normalizes_timeout_failure_to_error_info(self) -> None:
        gateway = LLMGateway(provider="google", adapter=TimeoutStub())

        with self.assertRaises(LLMGatewayError) as ctx:
            gateway.decide(_context())

        self.assertEqual(ctx.exception.error.code, "TIMEOUT")
        self.assertTrue(ctx.exception.error.retryable)

    def test_normalizes_auth_failure_to_error_info(self) -> None:
        gateway = LLMGateway(provider="openai", adapter=AuthFailureStub())

        with self.assertRaises(LLMGatewayError) as ctx:
            gateway.decide(_context())

        self.assertEqual(ctx.exception.error.code, "LLM_AUTH_FAILED")
        self.assertFalse(ctx.exception.error.retryable)

    def test_normalizes_malformed_response_to_error_info(self) -> None:
        gateway = LLMGateway(provider="openai", adapter=MalformedResponseStub())

        with self.assertRaises(LLMGatewayError) as ctx:
            gateway.decide(_context())

        self.assertEqual(ctx.exception.error.code, "LLM_INVALID_RESPONSE")
        self.assertFalse(ctx.exception.error.retryable)


if __name__ == "__main__":
    unittest.main()
