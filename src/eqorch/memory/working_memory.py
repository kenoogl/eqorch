"""In-memory state container with eviction and rollback support."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from eqorch.domain.models import Candidate, ErrorInfo, Evaluation, Memory, MemoryEntry, PendingJob, State


@dataclass(slots=True)
class WorkingMemorySnapshot:
    state: State


class WorkingMemory:
    """Wraps State mutation rules used by the orchestration loop."""

    def __init__(self, state: State) -> None:
        self._state = state

    @property
    def state(self) -> State:
        return self._state

    def snapshot(self) -> WorkingMemorySnapshot:
        return WorkingMemorySnapshot(state=deepcopy(self._state))

    def restore(self, snapshot: WorkingMemorySnapshot) -> None:
        self._state = deepcopy(snapshot.state)

    def clear_last_errors(self) -> None:
        self._state.last_errors.clear()

    def set_pending_jobs(self, pending_jobs: list[PendingJob]) -> None:
        self._state.pending_jobs = pending_jobs

    def record_error(self, key: str, error: ErrorInfo) -> None:
        self._state.last_errors[key] = error

    def append_candidates(self, candidates: list[Candidate]) -> list[Candidate]:
        self._state.candidates.extend(candidates)
        overflow = max(0, len(self._state.candidates) - self._state.policy_context.max_candidates)
        evicted = self._state.candidates[:overflow]
        if overflow:
            self._state.candidates = self._state.candidates[overflow:]
        return evicted

    def append_evaluations(self, evaluations: list[Evaluation]) -> list[Evaluation]:
        self._state.evaluations.extend(evaluations)
        overflow = max(0, len(self._state.evaluations) - self._state.policy_context.max_evaluations)
        evicted = self._state.evaluations[:overflow]
        if overflow:
            self._state.evaluations = self._state.evaluations[overflow:]
        return evicted

    def upsert_memory_entry(self, entry: MemoryEntry) -> list[MemoryEntry]:
        entries = list(self._state.workflow_memory.entries)
        index = next((i for i, existing in enumerate(entries) if existing.key == entry.key), None)
        if index is not None:
            entries.pop(index)
        entries.append(entry)
        evicted: list[MemoryEntry] = []
        overflow = max(0, len(entries) - self._state.policy_context.max_memory_entries)
        if overflow:
            policy = self._state.workflow_memory.eviction_policy
            if policy == "fifo":
                evicted = entries[:overflow]
                entries = entries[overflow:]
            else:
                entries.sort(key=lambda item: item.last_accessed)
                evicted = entries[:overflow]
                entries = entries[overflow:]
        self._state.workflow_memory = Memory(
            entries=entries,
            max_entries=self._state.policy_context.max_memory_entries,
            eviction_policy=self._state.workflow_memory.eviction_policy,
        )
        return evicted
