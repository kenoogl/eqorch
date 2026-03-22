from __future__ import annotations

import unittest

from eqorch.domain.policy import ModeRule
from eqorch.orchestrator import ModeRuleEvaluator


class ModeRuleEvaluatorTest(unittest.TestCase):
    def test_matches_first_true_rule(self) -> None:
        evaluator = ModeRuleEvaluator()
        rules = (
            ModeRule(
                condition="stagnation >= 3 and current_mode == 'interactive'",
                target_mode="batch",
                reason="stagnated",
            ),
            ModeRule(
                condition="diversity < 2",
                target_mode="interactive",
                reason="low diversity",
            ),
        )

        result = evaluator.evaluate(
            rules,
            {"stagnation": 4, "current_mode": "interactive", "diversity": 5},
            notes=("watch metrics",),
        )

        self.assertEqual(result.target_mode, "batch")
        self.assertEqual(result.reason, "stagnated")
        self.assertEqual(result.notes, ("watch metrics",))

    def test_returns_empty_result_when_no_rule_matches(self) -> None:
        evaluator = ModeRuleEvaluator()
        result = evaluator.evaluate(
            (
                ModeRule(
                    condition="stagnation >= 3",
                    target_mode="batch",
                    reason="stagnated",
                ),
            ),
            {"stagnation": 1},
        )
        self.assertIsNone(result.target_mode)
        self.assertIsNone(result.reason)

    def test_rejects_unknown_variable(self) -> None:
        evaluator = ModeRuleEvaluator()
        with self.assertRaisesRegex(ValueError, "unknown mode rule variable"):
            evaluator.evaluate(
                (
                    ModeRule(
                        condition="missing > 0",
                        target_mode="batch",
                        reason="bad",
                    ),
                ),
                {},
            )


if __name__ == "__main__":
    unittest.main()
