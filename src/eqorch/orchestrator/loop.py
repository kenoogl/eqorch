"""Core orchestration loop."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from eqorch.app import ErrorCoordinator
from eqorch.domain import Action, MemoryEntry, State
from eqorch.memory import WorkingMemory
from eqorch.memory import PersistenceCommit, PersistentMemoryStore
from eqorch.orchestrator.action_dispatcher import DispatchRecord
from eqorch.orchestrator.decision_context import DecisionContextAssembler
from eqorch.tracing import TraceRecorder

if TYPE_CHECKING:
    from eqorch.app.research_concierge import ResearchConcierge
    from eqorch.orchestrator.action_dispatcher import ActionDispatcher


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True, frozen=True)
class LoopCycleResult:
    state: State
    actions: tuple[Action, ...]
    dispatches: tuple[DispatchRecord, ...]
    should_continue: bool


class OrchestrationLoop:
    """Runs one orchestration cycle over state, decision, dispatch, and persistence."""

    def __init__(
        self,
        *,
        context_assembler: DecisionContextAssembler,
        concierge: ResearchConcierge,
        dispatcher: ActionDispatcher,
        trace_recorder: TraceRecorder,
        persistent_store: PersistentMemoryStore,
        error_coordinator: ErrorCoordinator,
    ) -> None:
        self._context_assembler = context_assembler
        self._concierge = concierge
        self._dispatcher = dispatcher
        self._trace_recorder = trace_recorder
        self._persistent_store = persistent_store
        self._error_coordinator = error_coordinator

    def run_cycle(self, state: State, *, issued_at: str | None = None) -> LoopCycleResult:
        issued_at = issued_at or _now()
        next_state = deepcopy(state)
        memory = WorkingMemory(next_state)
        memory.clear_last_errors()
        self._process_pending_jobs(memory, issued_at=issued_at)

        context = self._context_assembler.assemble(memory.state)
        decision = self._concierge.decide_with_retry(context, issued_at=issued_at)
        actions = tuple(decision.actions)
        if not actions:
            raise ValueError("orchestration loop requires at least one action")
        if len(actions) > memory.state.policy_context.max_parallel_actions:
            raise ValueError("action batch exceeds max_parallel_actions")

        if decision.coordinated_error is not None and decision.coordinated_error.should_record_last_error:
            memory.record_error(actions[0].action_id, decision.coordinated_error.error)

        memory.state.step += 1
        self._dispatcher._validate_batch(list(actions))  # type: ignore[attr-defined]
        dispatches: list[DispatchRecord] = []
        trace_entries = []
        should_continue = True

        for action in actions:
            before_state = deepcopy(memory.state)
            record = self._dispatcher.dispatch([action], memory.state)[0]
            dispatches.append(record)

            if record.result.status == "success":
                # dispatcher mutates the working state for successful control actions.
                plan = self._trace_recorder.record(
                    action=record.action,
                    result=record.result,
                    previous_state=before_state,
                    next_state=memory.state,
                    duration_ms=0,
                    timestamp=issued_at,
                )
            else:
                coordinated = self._error_coordinator.normalize(source="external", failure=record.result.error or "dispatch failed")
                if coordinated.should_record_last_error:
                    memory.record_error(record.action.action_id, coordinated.error)
                plan = self._trace_recorder.record(
                    action=record.action,
                    result=record.result,
                    previous_state=before_state,
                    next_state=before_state,
                    duration_ms=0,
                    timestamp=issued_at,
                )
            trace_entries.append(plan.log_entry)
            if record.action.type == "terminate":
                should_continue = False

        memory.set_pending_jobs(list(self._dispatcher.list_pending_jobs()))
        self._persistent_store.commit(
            PersistenceCommit(
                state_snapshot=deepcopy(memory.state),
                state_summaries={"step": memory.state.step, "mode": memory.state.current_mode},
                trace_entries=tuple(trace_entries),
            )
        )
        self._persistent_store.flush(timeout=5)

        return LoopCycleResult(
            state=memory.state,
            actions=actions,
            dispatches=tuple(dispatches),
            should_continue=should_continue,
        )

    def _process_pending_jobs(self, memory: WorkingMemory, *, issued_at: str) -> None:
        remaining = []
        for job in memory.state.pending_jobs:
            result = self._dispatcher.poll_pending_job(job.job_id)
            if result.status == "partial":
                remaining.append(job)
            elif result.status == "success":
                memory.upsert_memory_entry(
                    MemoryEntry(
                        key=f"pending_job:{job.job_id}",
                        value=result.payload,
                        created_at=issued_at,
                        last_accessed=issued_at,
                    )
                )
            elif result.error is not None:
                memory.record_error(job.action_id, result.error)
        memory.set_pending_jobs(remaining)


__all__ = ["LoopCycleResult", "OrchestrationLoop"]
