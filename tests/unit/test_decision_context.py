from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain import Candidate, ErrorInfo, Evaluation, Memory, MemoryEntry, PendingJob, State
from eqorch.domain.policy import PolicyContext
from eqorch.orchestrator import DecisionContextAssembler


def ts() -> str:
    return "2026-03-22T00:00:00Z"


def candidate(index: int) -> Candidate:
    return Candidate(
        id=str(uuid4()),
        equation=f"x+{index}",
        score=float(index),
        reasoning="reason",
        origin="LLM",
        created_at=ts(),
        step=index,
    )


def evaluation(candidate_id: str, index: int) -> Evaluation:
    return Evaluation(
        id=str(uuid4()),
        candidate_id=candidate_id,
        metrics={"mse": float(index), "complexity": float(index + 1), "extra": {"bonus": 1.0}},
        evaluator="engine",
        timestamp=ts(),
    )


class DecisionContextAssemblerTest(unittest.TestCase):
    def test_assembles_policy_state_memory_errors_and_pending_jobs(self) -> None:
        candidates = [candidate(1), candidate(2), candidate(3)]
        evaluations = [evaluation(candidates[0].id, 1), evaluation(candidates[1].id, 2)]
        state = State(
            policy_context=PolicyContext(goals=("goal",), llm_context_steps=2),
            workflow_memory=Memory(
                entries=[
                    MemoryEntry(key="m1", value={"a": 1}, created_at=ts(), last_accessed=ts()),
                    MemoryEntry(key="m2", value={"b": 2}, created_at=ts(), last_accessed=ts()),
                    MemoryEntry(key="m3", value={"c": 3}, created_at=ts(), last_accessed=ts()),
                ],
                max_entries=10,
                eviction_policy="fifo",
            ),
            candidates=candidates,
            evaluations=evaluations,
            session_id=str(uuid4()),
            step=7,
            pending_jobs=[
                PendingJob(
                    job_id="job-1",
                    engine_name="engine",
                    action_id=str(uuid4()),
                    issued_at=ts(),
                    timeout_at=ts(),
                )
            ],
            last_errors={"engine": ErrorInfo(code="ERR", message="failed", retryable=True)},
        )

        context = DecisionContextAssembler().assemble(state)

        self.assertEqual(context.step, 7)
        self.assertEqual(context.current_mode, "interactive")
        self.assertEqual(context.candidate_count, 3)
        self.assertEqual(context.evaluation_count, 2)
        self.assertEqual(len(context.pending_jobs), 1)
        self.assertEqual(context.last_errors["engine"].code, "ERR")
        self.assertEqual(len(context.workflow_memory_summary), 2)
        self.assertEqual(len(context.candidate_summary), 2)
        self.assertEqual(len(context.evaluation_summary), 2)
        self.assertTrue(context.workflow_memory_summary[-1].startswith("m3="))

    def test_llm_context_steps_limits_summaries(self) -> None:
        candidates = [candidate(index) for index in range(5)]
        state = State(
            policy_context=PolicyContext(goals=("goal",), llm_context_steps=1),
            workflow_memory=Memory(
                entries=[
                    MemoryEntry(key=f"m{index}", value={"v": index}, created_at=ts(), last_accessed=ts())
                    for index in range(3)
                ],
                max_entries=10,
                eviction_policy="fifo",
            ),
            candidates=candidates,
            evaluations=[evaluation(candidates[-1].id, 4)],
            session_id=str(uuid4()),
        )

        context = DecisionContextAssembler().assemble(state)

        self.assertEqual(len(context.workflow_memory_summary), 1)
        self.assertEqual(len(context.candidate_summary), 1)
        self.assertEqual(len(context.evaluation_summary), 1)


if __name__ == "__main__":
    unittest.main()
