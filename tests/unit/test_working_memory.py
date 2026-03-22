from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain.models import Candidate, Evaluation, Memory, MemoryEntry, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory import WorkingMemory


def ts() -> str:
    return "2026-03-22T00:00:00Z"


def candidate(step: int) -> Candidate:
    return Candidate(
        id=str(uuid4()),
        equation=f"x+{step}",
        score=1.0 + step,
        reasoning="valid reasoning",
        origin="LLM",
        created_at=ts(),
        step=step,
    )


def evaluation(candidate_id: str, index: int) -> Evaluation:
    return Evaluation(
        id=str(uuid4()),
        candidate_id=candidate_id,
        metrics={"mse": float(index), "complexity": float(index + 1), "extra": {}},
        evaluator="engine",
        timestamp=ts(),
    )


class WorkingMemoryTest(unittest.TestCase):
    def test_candidate_overflow_is_evicted_from_front(self) -> None:
        state = State(
            policy_context=PolicyContext(goals=("goal",), max_candidates=2),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )
        memory = WorkingMemory(state)

        first = candidate(1)
        second = candidate(2)
        third = candidate(3)
        memory.append_candidates([first, second, third])

        self.assertEqual([item.id for item in memory.state.candidates], [second.id, third.id])

    def test_memory_fifo_eviction_returns_overflow(self) -> None:
        state = State(
            policy_context=PolicyContext(goals=("goal",), max_memory_entries=2),
            workflow_memory=Memory(entries=[], max_entries=2, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )
        memory = WorkingMemory(state)

        evicted = memory.upsert_memory_entry(MemoryEntry(key="a", value={"v": 1}, created_at=ts(), last_accessed=ts()))
        self.assertEqual(evicted, [])
        memory.upsert_memory_entry(MemoryEntry(key="b", value={"v": 2}, created_at=ts(), last_accessed=ts()))
        evicted = memory.upsert_memory_entry(MemoryEntry(key="c", value={"v": 3}, created_at=ts(), last_accessed=ts()))

        self.assertEqual([entry.key for entry in evicted], ["a"])
        self.assertEqual([entry.key for entry in memory.state.workflow_memory.entries], ["b", "c"])

    def test_snapshot_restore_rollback(self) -> None:
        base_candidate = candidate(1)
        state = State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            candidates=[base_candidate],
            session_id=str(uuid4()),
        )
        memory = WorkingMemory(state)
        snapshot = memory.snapshot()

        next_candidate = candidate(2)
        memory.append_candidates([next_candidate])
        memory.restore(snapshot)

        self.assertEqual([item.id for item in memory.state.candidates], [base_candidate.id])

    def test_evaluation_overflow_is_evicted(self) -> None:
        candidate_item = candidate(1)
        state = State(
            policy_context=PolicyContext(goals=("goal",), max_evaluations=1),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            candidates=[candidate_item],
            session_id=str(uuid4()),
        )
        memory = WorkingMemory(state)

        first = evaluation(candidate_item.id, 1)
        second = evaluation(candidate_item.id, 2)
        evicted = memory.append_evaluations([first, second])

        self.assertEqual([item.id for item in evicted], [first.id])
        self.assertEqual([item.id for item in memory.state.evaluations], [second.id])


if __name__ == "__main__":
    unittest.main()
