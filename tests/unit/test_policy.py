from __future__ import annotations

import unittest

from eqorch.domain.policy import PolicyContext, RetryPolicy


class PolicyContextTest(unittest.TestCase):
    def test_policy_context_applies_defaults(self) -> None:
        policy = PolicyContext(goals=("find equation",))
        self.assertEqual(policy.max_candidates, 100)
        self.assertEqual(policy.max_parallel_actions, 8)
        self.assertEqual(policy.retry, RetryPolicy())

    def test_policy_context_requires_goals(self) -> None:
        with self.assertRaisesRegex(ValueError, "goals"):
            PolicyContext(goals=())


if __name__ == "__main__":
    unittest.main()
