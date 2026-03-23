from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from eqorch.app import RuntimeEnvironmentChecks
from eqorch.gateways import LLMGateway


class HealthyAdapter:
    def decide(self, payload):
        return {
            "choices": [
                {
                    "message": {
                        "content": '[{"type":"terminate","target":"system","parameters":{"reason":"done"}}]'
                    }
                }
            ]
        }


class TimeoutAdapter:
    def decide(self, payload):
        raise TimeoutError("provider unavailable")


class RuntimeEnvironmentChecksTest(unittest.TestCase):
    def test_fails_when_policy_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.yaml"
            policy_path.write_text("goals: []\n", encoding="utf-8")
            components_path = Path(tmpdir) / "components.yaml"
            components_path.write_text("skills: []\ntools: []\nengines: []\nbackends: []\n", encoding="utf-8")

            result = RuntimeEnvironmentChecks().validate_startup(
                policy_path=policy_path,
                components_path=components_path,
                llm_gateway=LLMGateway(provider="openai", adapter=HealthyAdapter()),
            )

        self.assertFalse(result.ok)
        self.assertTrue(any(reason.startswith("invalid policy:") for reason in result.reasons))

    def test_fails_when_component_config_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.yaml"
            policy_path.write_text("goals:\n  - find equation\n", encoding="utf-8")
            components_path = Path(tmpdir) / "components.yaml"
            components_path.write_text(
                textwrap.dedent(
                    """
                    engines:
                      - name: broken
                        endpoint: dns:///engine
                        protocol: grpc
                    """
                ).strip(),
                encoding="utf-8",
            )

            result = RuntimeEnvironmentChecks().validate_startup(
                policy_path=policy_path,
                components_path=components_path,
                llm_gateway=LLMGateway(provider="anthropic", adapter=HealthyAdapter()),
            )

        self.assertFalse(result.ok)
        self.assertTrue(any(reason.startswith("invalid components config:") for reason in result.reasons))

    def test_fails_when_llm_connectivity_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.yaml"
            policy_path.write_text("goals:\n  - find equation\n", encoding="utf-8")
            components_path = Path(tmpdir) / "components.yaml"
            components_path.write_text("skills: []\ntools: []\nengines: []\nbackends: []\n", encoding="utf-8")

            result = RuntimeEnvironmentChecks().validate_startup(
                policy_path=policy_path,
                components_path=components_path,
                llm_gateway=LLMGateway(provider="google", adapter=TimeoutAdapter()),
            )

        self.assertFalse(result.ok)
        self.assertTrue(any(reason.startswith("llm connectivity failed:") for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
