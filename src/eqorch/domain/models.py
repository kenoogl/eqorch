"""Core domain models for EqOrch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any, Literal
from uuid import UUID


ActionType = Literal[
    "call_skill",
    "call_tool",
    "run_engine",
    "ask_user",
    "update_policy",
    "switch_mode",
    "terminate",
]
ResultStatus = Literal["success", "error", "timeout", "partial"]
CandidateOrigin = Literal["LLM", "Engine", "Hybrid"]
StateMode = Literal["interactive", "batch"]
StateDiffOp = Literal["add", "remove", "replace"]
EvictionPolicy = Literal["lru", "fifo"]


def ensure_uuid4(value: str, field_name: str) -> None:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc
    if parsed.version != 4:
        raise ValueError(f"{field_name} must be a UUIDv4")


def ensure_iso8601_utc(value: str, field_name: str) -> None:
    if not value.endswith("Z"):
        raise ValueError(f"{field_name} must end with 'Z'")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 UTC timestamp") from exc


def ensure_non_empty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def ensure_json_pointer(value: str, field_name: str) -> None:
    if value == "":
        return
    if not value.startswith("/"):
        raise ValueError(f"{field_name} must be an RFC 6901 JSON Pointer")


def ensure_finite_number(value: float, field_name: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")


@dataclass(slots=True, frozen=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        ensure_non_empty(self.code, "code")
        ensure_non_empty(self.message, "message")


@dataclass(slots=True, frozen=True)
class Candidate:
    id: str
    equation: str
    score: float
    reasoning: str
    origin: CandidateOrigin
    created_at: str
    step: int

    def __post_init__(self) -> None:
        ensure_uuid4(self.id, "id")
        ensure_non_empty(self.equation, "equation")
        ensure_finite_number(self.score, "score")
        ensure_non_empty(self.reasoning, "reasoning")
        ensure_iso8601_utc(self.created_at, "created_at")
        if self.step < 0:
            raise ValueError("step must be >= 0")


@dataclass(slots=True, frozen=True)
class Evaluation:
    id: str
    candidate_id: str
    metrics: dict[str, float | dict[str, float]]
    evaluator: str
    timestamp: str

    def __post_init__(self) -> None:
        ensure_uuid4(self.id, "id")
        ensure_uuid4(self.candidate_id, "candidate_id")
        ensure_non_empty(self.evaluator, "evaluator")
        ensure_iso8601_utc(self.timestamp, "timestamp")
        for key in ("mse", "complexity"):
            if key not in self.metrics:
                raise ValueError(f"metrics must include {key}")
            ensure_finite_number(float(self.metrics[key]), f"metrics.{key}")
        extra = self.metrics.get("extra", {})
        if not isinstance(extra, dict):
            raise ValueError("metrics.extra must be a dict")
        for name, value in extra.items():
            ensure_non_empty(name, "metrics.extra key")
            ensure_finite_number(float(value), f"metrics.extra.{name}")


@dataclass(slots=True, frozen=True)
class Action:
    type: ActionType
    target: str
    parameters: dict[str, Any]
    issued_at: str
    action_id: str

    def __post_init__(self) -> None:
        ensure_non_empty(self.target, "target")
        ensure_iso8601_utc(self.issued_at, "issued_at")
        ensure_uuid4(self.action_id, "action_id")


@dataclass(slots=True, frozen=True)
class Result:
    status: ResultStatus
    payload: dict[str, Any]
    error: ErrorInfo | None

    def __post_init__(self) -> None:
        if self.status == "partial":
            if not self.payload:
                raise ValueError("partial result must include payload")
            if self.error is None:
                raise ValueError("partial result must include error")
        if self.status in {"error", "timeout"} and self.error is None:
            raise ValueError(f"{self.status} result must include error")


@dataclass(slots=True, frozen=True)
class MemoryEntry:
    key: str
    value: dict[str, Any]
    created_at: str
    last_accessed: str

    def __post_init__(self) -> None:
        ensure_non_empty(self.key, "key")
        ensure_iso8601_utc(self.created_at, "created_at")
        ensure_iso8601_utc(self.last_accessed, "last_accessed")


@dataclass(slots=True, frozen=True)
class Memory:
    entries: list[MemoryEntry]
    max_entries: int
    eviction_policy: EvictionPolicy

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("max_entries must be > 0")
        if len(self.entries) > self.max_entries:
            raise ValueError("entries exceed max_entries")


@dataclass(slots=True, frozen=True)
class StateDiffEntry:
    op: StateDiffOp
    path: str
    value: Any = None

    def __post_init__(self) -> None:
        ensure_json_pointer(self.path, "path")
        if self.op == "remove" and self.value is not None:
            raise ValueError("remove diff must not include value")


@dataclass(slots=True, frozen=True)
class PendingJob:
    job_id: str
    engine_name: str
    action_id: str
    issued_at: str
    timeout_at: str

    def __post_init__(self) -> None:
        ensure_non_empty(self.job_id, "job_id")
        ensure_non_empty(self.engine_name, "engine_name")
        ensure_uuid4(self.action_id, "action_id")
        ensure_iso8601_utc(self.issued_at, "issued_at")
        ensure_iso8601_utc(self.timeout_at, "timeout_at")


@dataclass(slots=True, frozen=True)
class LogEntry:
    step: int
    session_id: str
    action_id: str
    action: Action
    result: Result
    input_summary: str
    output_summary: str
    state_diff: list[StateDiffEntry]
    duration_ms: int
    timestamp: str

    def __post_init__(self) -> None:
        if self.step < 0:
            raise ValueError("step must be >= 0")
        ensure_uuid4(self.session_id, "session_id")
        ensure_uuid4(self.action_id, "action_id")
        ensure_iso8601_utc(self.timestamp, "timestamp")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")


@dataclass(slots=True)
class State:
    policy_context: "PolicyContext"
    workflow_memory: Memory
    candidates: list[Candidate] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    current_mode: StateMode = "interactive"
    session_id: str = ""
    step: int = 0
    pending_jobs: list[PendingJob] = field(default_factory=list)
    last_errors: dict[str, ErrorInfo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from .policy import PolicyContext

        if not isinstance(self.policy_context, PolicyContext):
            raise TypeError("policy_context must be a PolicyContext")
        ensure_uuid4(self.session_id, "session_id")
        if self.step < 0:
            raise ValueError("step must be >= 0")
        if len(self.candidates) > self.policy_context.max_candidates:
            raise ValueError("candidates exceed policy max_candidates")
        if len(self.evaluations) > self.policy_context.max_evaluations:
            raise ValueError("evaluations exceed policy max_evaluations")
