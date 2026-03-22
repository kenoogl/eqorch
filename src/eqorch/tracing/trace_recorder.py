"""Minimal trace recorder stub for action planning."""

from __future__ import annotations

from dataclasses import dataclass

from eqorch.domain import Action, Result, StateDiffEntry


@dataclass(slots=True, frozen=True)
class TracePlan:
    action: Action
    result: Result
    state_diff: tuple[StateDiffEntry, ...]


class TraceRecorder:
    """Collects trace plans until persistence is implemented."""

    def __init__(self) -> None:
        self._plans: list[TracePlan] = []

    def plan(self, action: Action, result: Result, state_diff: list[StateDiffEntry] | None = None) -> TracePlan:
        plan = TracePlan(action=action, result=result, state_diff=tuple(state_diff or ()))
        self._plans.append(plan)
        return plan

    @property
    def plans(self) -> tuple[TracePlan, ...]:
        return tuple(self._plans)

