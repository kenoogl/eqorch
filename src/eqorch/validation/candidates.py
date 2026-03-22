"""Candidate and evaluation validation."""

from __future__ import annotations

from dataclasses import dataclass

from eqorch.domain.models import Candidate, Evaluation


@dataclass(slots=True, frozen=True)
class CandidateValidationError:
    code: str
    message: str


class CandidateValidator:
    """Validates candidate and evaluation batches before state application."""

    def validate(
        self,
        candidates: list[Candidate],
        evaluations: list[Evaluation],
        existing_candidates: list[Candidate] | None = None,
    ) -> list[CandidateValidationError]:
        errors: list[CandidateValidationError] = []
        existing_candidates = existing_candidates or []

        known_candidate_ids = {candidate.id for candidate in existing_candidates}
        known_equations = {candidate.equation for candidate in existing_candidates}
        seen_candidate_ids: set[str] = set()
        seen_equations: set[str] = set()

        for candidate in candidates:
            if candidate.id in known_candidate_ids or candidate.id in seen_candidate_ids:
                errors.append(
                    CandidateValidationError(
                        code="DUPLICATE_CANDIDATE_ID",
                        message=f"candidate id is duplicated: {candidate.id}",
                    )
                )
            if candidate.equation in known_equations or candidate.equation in seen_equations:
                errors.append(
                    CandidateValidationError(
                        code="DUPLICATE_CANDIDATE_EQUATION",
                        message=f"candidate equation is duplicated: {candidate.equation}",
                    )
                )
            if candidate.score < 0:
                errors.append(
                    CandidateValidationError(
                        code="NEGATIVE_CANDIDATE_SCORE",
                        message=f"candidate score must be >= 0: {candidate.id}",
                    )
                )
            seen_candidate_ids.add(candidate.id)
            seen_equations.add(candidate.equation)

        valid_ids = known_candidate_ids | seen_candidate_ids
        seen_evaluation_ids: set[str] = set()
        for evaluation in evaluations:
            if evaluation.id in seen_evaluation_ids:
                errors.append(
                    CandidateValidationError(
                        code="DUPLICATE_EVALUATION_ID",
                        message=f"evaluation id is duplicated: {evaluation.id}",
                    )
                )
            if evaluation.candidate_id not in valid_ids:
                errors.append(
                    CandidateValidationError(
                        code="UNKNOWN_CANDIDATE_REFERENCE",
                        message=f"evaluation references unknown candidate: {evaluation.candidate_id}",
                    )
                )
            seen_evaluation_ids.add(evaluation.id)

        return errors
