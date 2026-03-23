"""Replay loader for canonical state and trace reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
import json

from eqorch.domain import LogEntry, State
from .persistent_store import PersistentMemoryStore, _serialize_state


@dataclass(slots=True, frozen=True)
class ReplayFrame:
    base_state: State
    trace_entries: tuple[LogEntry, ...]


@dataclass(slots=True, frozen=True)
class ReplayVerification:
    matched_step: int
    trace_count: int
    verified_action_ids: tuple[str, ...]


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

    def verify_frame(self, frame: ReplayFrame, *, expected_step: int | None = None) -> ReplayVerification:
        if expected_step is not None and frame.base_state.step != expected_step:
            raise ValueError("base_state.step does not match requested replay step")

        previous_step = -1
        verified_action_ids: list[str] = []
        for entry in frame.trace_entries:
            if entry.session_id != frame.base_state.session_id:
                raise ValueError("trace entry session_id does not match replay base state")
            if entry.step < previous_step:
                raise ValueError("trace entries must be ordered by non-decreasing step")
            previous_step = entry.step
            verified_action_ids.append(entry.action_id)
            self._parse_summary(entry.input_summary)
            self._parse_summary(entry.output_summary)

        if frame.trace_entries and frame.trace_entries[-1].step > frame.base_state.step:
            raise ValueError("trace entries extend beyond replay base state")

        relevant_entries = [entry for entry in frame.trace_entries if entry.step == frame.base_state.step]
        if relevant_entries:
            final_output = self._parse_summary(relevant_entries[-1].output_summary)
            if final_output is not None:
                expected_output = _serialize_state(frame.base_state)
                if not _is_subset(final_output, expected_output):
                    raise ValueError("trace output summary does not match replay base state")

        return ReplayVerification(
            matched_step=frame.base_state.step,
            trace_count=len(frame.trace_entries),
            verified_action_ids=tuple(verified_action_ids),
        )

    def load_verified_frame(self, session_id: str, *, step: int | None = None) -> ReplayFrame | None:
        frame = self.load_frame(session_id, step=step)
        if frame is None:
            return None
        self.verify_frame(frame, expected_step=step)
        return frame

    def _parse_summary(self, summary: str) -> dict[str, object] | None:
        if summary == "pending":
            return None
        try:
            return json.loads(summary)
        except json.JSONDecodeError:
            return None


def _is_subset(actual: object, expected: object) -> bool:
    if isinstance(actual, dict) and isinstance(expected, dict):
        return all(key in expected and _is_subset(value, expected[key]) for key, value in actual.items())
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return False
        return all(_is_subset(left, right) for left, right in zip(actual, expected))
    return actual == expected
