from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from eqorch.app import PolicyContextStore, PolicyLoadError


class PolicyContextStoreTest(unittest.TestCase):
    def test_loads_yaml_with_defaults(self) -> None:
        content = textwrap.dedent(
            """
            goals:
              - find equation
            """
        ).strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.yaml"
            path.write_text(content, encoding="utf-8")
            policy = PolicyContextStore().load_file(path)

        self.assertEqual(policy.goals, ("find equation",))
        self.assertEqual(policy.max_candidates, 100)
        self.assertEqual(policy.retry.max_retries, 3)

    def test_loads_toml(self) -> None:
        content = textwrap.dedent(
            """
            goals = ["find equation"]
            max_parallel_actions = 4

            [retry]
            max_retries = 2
            """
        ).strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.toml"
            path.write_text(content, encoding="utf-8")
            policy = PolicyContextStore().load_file(path)

        self.assertEqual(policy.max_parallel_actions, 4)
        self.assertEqual(policy.retry.max_retries, 2)

    def test_loads_markdown_frontmatter(self) -> None:
        content = textwrap.dedent(
            """
            ---
            goals:
              - find equation
            mode_switch_criteria:
              notes:
                - watch stagnation
            ---

            # Policy
            """
        ).lstrip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.md"
            path.write_text(content, encoding="utf-8")
            policy = PolicyContextStore().load_file(path)

        self.assertEqual(policy.mode_switch_notes, ("watch stagnation",))

    def test_invalid_policy_keeps_old_policy(self) -> None:
        store = PolicyContextStore()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.yaml"
            path.write_text("goals:\n  - valid\n", encoding="utf-8")
            old_policy = store.load_file(path)

            path.write_text("goals: []\n", encoding="utf-8")
            with self.assertRaises(PolicyLoadError):
                store.load_file(path)

        self.assertEqual(store.current, old_policy)

    def test_apply_patch_updates_next_policy(self) -> None:
        store = PolicyContextStore()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy.yaml"
            path.write_text("goals:\n  - valid\n", encoding="utf-8")
            store.load_file(path)

        updated = store.apply_patch({"max_candidates": 5, "retry": {"max_retries": 1}})

        self.assertEqual(updated.max_candidates, 5)
        self.assertEqual(updated.retry.max_retries, 1)


if __name__ == "__main__":
    unittest.main()
