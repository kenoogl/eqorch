from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain.models import Candidate, ErrorInfo, Evaluation, Memory, MemoryEntry, Result, StateDiffEntry


def ts() -> str:
    return "2026-03-22T00:00:00Z"


class DomainModelTest(unittest.TestCase):
    def test_candidate_requires_non_empty_reasoning(self) -> None:
        with self.assertRaisesRegex(ValueError, "reasoning"):
            Candidate(
                id=str(uuid4()),
                equation="x+y",
                score=1.0,
                reasoning="",
                origin="LLM",
                created_at=ts(),
                step=0,
            )

    def test_evaluation_requires_core_metrics(self) -> None:
        with self.assertRaisesRegex(ValueError, "metrics must include complexity"):
            Evaluation(
                id=str(uuid4()),
                candidate_id=str(uuid4()),
                metrics={"mse": 1.0},
                evaluator="engine",
                timestamp=ts(),
            )

    def test_partial_result_requires_payload_and_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "partial result"):
            Result(status="partial", payload={}, error=None)

    def test_memory_respects_max_entries(self) -> None:
        entry = MemoryEntry(key="a", value={"x": 1}, created_at=ts(), last_accessed=ts())
        with self.assertRaisesRegex(ValueError, "max_entries must be > 0"):
            Memory(entries=[entry], max_entries=0, eviction_policy="fifo")

    def test_state_diff_requires_json_pointer(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON Pointer"):
            StateDiffEntry(op="replace", path="step", value=1)

    def test_error_info_requires_non_empty_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "code"):
            ErrorInfo(code="", message="bad", retryable=False)


if __name__ == "__main__":
    unittest.main()
