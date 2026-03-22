from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain import Action, ErrorInfo, Memory, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.tracing import TraceRecorder


def ts() -> str:
    return "2026-03-22T00:00:00Z"


class TraceRecorderTest(unittest.TestCase):
    def test_generates_json_patch_and_log_entry(self) -> None:
        previous = State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
            step=1,
        )
        current = State(
            policy_context=previous.policy_context,
            workflow_memory=previous.workflow_memory,
            session_id=previous.session_id,
            step=2,
            current_mode="batch",
        )
        action = Action(
            type="switch_mode",
            target="system",
            parameters={"target_mode": "batch"},
            issued_at=ts(),
            action_id=str(uuid4()),
        )
        result = Result(status="success", payload={"target_mode": "batch"}, error=None)

        plan = TraceRecorder().record(
            action=action,
            result=result,
            previous_state=previous,
            next_state=current,
            duration_ms=12,
            timestamp=ts(),
        )

        paths = {entry.path for entry in plan.state_diff}
        self.assertIn("/step", paths)
        self.assertIn("/current_mode", paths)
        self.assertEqual(plan.log_entry.duration_ms, 12)
        self.assertEqual(plan.log_entry.action_id, action.action_id)
        self.assertTrue(plan.log_entry.input_summary.startswith("{"))
        self.assertTrue(plan.log_entry.output_summary.startswith("{"))

    def test_json_pointer_paths_are_valid(self) -> None:
        previous = State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )
        current = State(
            policy_context=previous.policy_context,
            workflow_memory=previous.workflow_memory,
            session_id=previous.session_id,
            last_errors={"engine": ErrorInfo(code="ERR", message="failed", retryable=True)},
        )
        action = Action(
            type="run_engine",
            target="symbolic_regression",
            parameters={"instruction": "search"},
            issued_at=ts(),
            action_id=str(uuid4()),
        )
        result = Result(
            status="error",
            payload={},
            error=ErrorInfo(code="ERR", message="failed", retryable=True),
        )

        plan = TraceRecorder().record(
            action=action,
            result=result,
            previous_state=previous,
            next_state=current,
            duration_ms=1,
            timestamp=ts(),
        )

        for diff in plan.state_diff:
            self.assertTrue(diff.path == "" or diff.path.startswith("/"))


if __name__ == "__main__":
    unittest.main()
