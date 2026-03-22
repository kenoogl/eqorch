"""Trace recorder with JSON Patch generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
from typing import Any

from eqorch.domain import Action, LogEntry, Result, State, StateDiffEntry


@dataclass(slots=True, frozen=True)
class TracePlan:
    action: Action
    result: Result
    state_diff: tuple[StateDiffEntry, ...]
    log_entry: LogEntry


class TraceRecorder:
    """Builds log entries and JSON Patch diffs for state transitions."""

    def __init__(self) -> None:
        self._plans: list[TracePlan] = []

    def record(
        self,
        *,
        action: Action,
        result: Result,
        previous_state: State,
        next_state: State,
        duration_ms: int,
        timestamp: str,
    ) -> TracePlan:
        previous_payload = _serialize_state(previous_state)
        next_payload = _serialize_state(next_state)
        state_diff = tuple(_diff_json(previous_payload, next_payload, path=""))
        log_entry = LogEntry(
            step=next_state.step,
            session_id=next_state.session_id,
            action_id=action.action_id,
            action=action,
            result=result,
            input_summary=_summarize_payload(previous_payload),
            output_summary=_summarize_payload(next_payload),
            state_diff=list(state_diff),
            duration_ms=duration_ms,
            timestamp=timestamp,
        )
        plan = TracePlan(action=action, result=result, state_diff=state_diff, log_entry=log_entry)
        self._plans.append(plan)
        return plan

    def plan(
        self,
        action: Action,
        result: Result,
        state_diff: list[StateDiffEntry] | None = None,
    ) -> TracePlan:
        state_diff = tuple(state_diff or ())
        empty_log = LogEntry(
            step=0,
            session_id="00000000-0000-4000-8000-000000000000",
            action_id=action.action_id,
            action=action,
            result=result,
            input_summary="pending",
            output_summary="pending",
            state_diff=list(state_diff),
            duration_ms=0,
            timestamp=action.issued_at,
        )
        plan = TracePlan(action=action, result=result, state_diff=state_diff, log_entry=empty_log)
        self._plans.append(plan)
        return plan

    @property
    def plans(self) -> tuple[TracePlan, ...]:
        return tuple(self._plans)


def _serialize_state(state: State) -> dict[str, Any]:
    return _normalize(asdict(state))


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    return value


def _escape_path(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _diff_json(previous: Any, current: Any, path: str) -> list[StateDiffEntry]:
    if previous == current:
        return []
    if isinstance(previous, dict) and isinstance(current, dict):
        diff: list[StateDiffEntry] = []
        previous_keys = set(previous)
        current_keys = set(current)
        for key in sorted(previous_keys - current_keys):
            diff.append(StateDiffEntry(op="remove", path=f"{path}/{_escape_path(key)}"))
        for key in sorted(current_keys - previous_keys):
            diff.append(StateDiffEntry(op="add", path=f"{path}/{_escape_path(key)}", value=current[key]))
        for key in sorted(previous_keys & current_keys):
            diff.extend(_diff_json(previous[key], current[key], f"{path}/{_escape_path(key)}"))
        return diff
    if isinstance(previous, list) and isinstance(current, list):
        return [StateDiffEntry(op="replace", path=path or "", value=current)]
    return [StateDiffEntry(op="replace", path=path or "", value=current)]


def _summarize_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    if len(text) <= 240:
        return text
    return text[:237] + "..."
