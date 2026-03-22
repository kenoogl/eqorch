"""Policy domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import ensure_non_empty


ExplorationStrategy = Literal["expand", "refine", "restart"]
Mode = Literal["interactive", "batch"]


@dataclass(slots=True, frozen=True)
class ModeRule:
    condition: str
    target_mode: Mode
    reason: str

    def __post_init__(self) -> None:
        ensure_non_empty(self.condition, "condition")
        ensure_non_empty(self.reason, "reason")


@dataclass(slots=True, frozen=True)
class TriggerThresholds:
    stagnation_threshold: int = 1
    diversity_threshold: int = 1

    def __post_init__(self) -> None:
        if self.stagnation_threshold < 0:
            raise ValueError("stagnation_threshold must be >= 0")
        if self.diversity_threshold < 0:
            raise ValueError("diversity_threshold must be >= 0")


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    max_retries: int = 3
    retry_interval_sec: int = 5
    excluded_types: tuple[str, ...] = ("ask_user", "switch_mode", "terminate")

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.retry_interval_sec < 0:
            raise ValueError("retry_interval_sec must be >= 0")
        if not self.excluded_types:
            raise ValueError("excluded_types must not be empty")


@dataclass(slots=True, frozen=True)
class PolicyContext:
    goals: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    forbidden_operations: tuple[str, ...] = ()
    exploration_strategy: ExplorationStrategy = "expand"
    mode_switch_criteria: tuple[ModeRule, ...] = ()
    mode_switch_notes: tuple[str, ...] = ()
    max_candidates: int = 100
    max_evaluations: int = 500
    max_memory_entries: int = 1000
    max_parallel_actions: int = 8
    llm_context_steps: int = 20
    triggers: TriggerThresholds = field(default_factory=TriggerThresholds)
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if not self.goals:
            raise ValueError("goals must contain at least one entry")
        for goal in self.goals:
            ensure_non_empty(goal, "goal")
        for attr in (
            "max_candidates",
            "max_evaluations",
            "max_memory_entries",
            "max_parallel_actions",
            "llm_context_steps",
        ):
            if getattr(self, attr) <= 0:
                raise ValueError(f"{attr} must be > 0")
