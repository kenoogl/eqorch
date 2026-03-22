"""Replay loader for canonical state and trace reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from eqorch.domain import LogEntry, State
from .persistent_store import PersistentMemoryStore


@dataclass(slots=True, frozen=True)
class ReplayFrame:
    base_state: State
    trace_entries: tuple[LogEntry, ...]


class ReplayLoader:
    """Loads canonical replay inputs from workflow and trace stores."""

    def __init__(self, store: PersistentMemoryStore) -> None:
        self._store = store

    def load_latest(self, session_id: str) -> State | None:
        return self._store.load_latest(session_id)

    def load_frame(self, session_id: str, *, step: int | None = None) -> ReplayFrame | None:
        base_state = self._store.load_replay_base(session_id, step)
        if base_state is None:
            return None
        trace_entries = self._store.trace_store.load_entries(session_id, up_to_step=step)
        return ReplayFrame(base_state=base_state, trace_entries=trace_entries)
