"""Decision context assembly for LLM-facing orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from eqorch.domain import ErrorInfo, Evaluation, PendingJob, PolicyContext, State


@dataclass(slots=True, frozen=True)
class DecisionContext:
    policy_context: PolicyContext
    session_id: str
    step: int
    current_mode: str
    candidate_count: int
    evaluation_count: int
    pending_jobs: tuple[PendingJob, ...]
    last_errors: dict[str, ErrorInfo]
    workflow_memory_summary: tuple[str, ...]
    candidate_summary: tuple[str, ...]
    evaluation_summary: tuple[str, ...]


class DecisionContextAssembler:
    """Builds a compact context for the research concierge."""

    def assemble(self, state: State) -> DecisionContext:
        limit = state.policy_context.llm_context_steps
        memory_entries = state.workflow_memory.entries[-limit:]
        candidates = state.candidates[-limit:]
        evaluations = state.evaluations[-limit:]

        workflow_memory_summary = tuple(
            f"{entry.key}={_summarize_value(entry.value)}@{entry.last_accessed}" for entry in memory_entries
        )
        candidate_summary = tuple(
            f"{candidate.id}:{candidate.equation}:score={candidate.score}:origin={candidate.origin}"
            for candidate in candidates
        )
        evaluation_summary = tuple(
            f"{evaluation.id}:{evaluation.candidate_id}:{_summarize_metrics(evaluation)}"
            for evaluation in evaluations
        )

        return DecisionContext(
            policy_context=state.policy_context,
            session_id=state.session_id,
            step=state.step,
            current_mode=state.current_mode,
            candidate_count=len(state.candidates),
            evaluation_count=len(state.evaluations),
            pending_jobs=tuple(state.pending_jobs),
            last_errors=dict(state.last_errors),
            workflow_memory_summary=workflow_memory_summary,
            candidate_summary=candidate_summary,
            evaluation_summary=evaluation_summary,
        )


def _summarize_value(value: dict[str, object]) -> str:
    keys = sorted(value.keys())
    preview = ",".join(keys[:3])
    if len(keys) > 3:
        preview += ",..."
    return preview or "empty"


def _summarize_metrics(evaluation: Evaluation) -> str:
    mse = evaluation.metrics["mse"]
    complexity = evaluation.metrics["complexity"]
    extra = evaluation.metrics.get("extra", {})
    return f"mse={mse},complexity={complexity},extra={len(extra)}"

