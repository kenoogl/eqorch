from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain.models import Candidate, Evaluation
from eqorch.validation import CandidateValidator


def ts() -> str:
    return "2026-03-22T00:00:00Z"


class CandidateValidatorTest(unittest.TestCase):
    def test_rejects_duplicate_candidates_and_unknown_evaluation_reference(self) -> None:
        candidate_id = str(uuid4())
        candidates = [
            Candidate(
                id=candidate_id,
                equation="x+y",
                score=1.0,
                reasoning="seed",
                origin="LLM",
                created_at=ts(),
                step=0,
            ),
            Candidate(
                id=candidate_id,
                equation="x+y",
                score=2.0,
                reasoning="duplicate",
                origin="LLM",
                created_at=ts(),
                step=0,
            ),
        ]
        evaluations = [
            Evaluation(
                id=str(uuid4()),
                candidate_id=str(uuid4()),
                metrics={"mse": 1.0, "complexity": 2.0, "extra": {}},
                evaluator="engine",
                timestamp=ts(),
            )
        ]

        errors = CandidateValidator().validate(candidates=candidates, evaluations=evaluations)

        self.assertEqual(
            {error.code for error in errors},
            {
                "DUPLICATE_CANDIDATE_ID",
                "DUPLICATE_CANDIDATE_EQUATION",
                "UNKNOWN_CANDIDATE_REFERENCE",
            },
        )


if __name__ == "__main__":
    unittest.main()
