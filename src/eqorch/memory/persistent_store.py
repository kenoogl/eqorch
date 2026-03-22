"""Persistent memory facade and canonical workflow store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import queue
import sqlite3
from threading import Event, Lock, Thread
from typing import Any, Callable

from eqorch.app import ErrorCoordinator
from eqorch.domain import (
    Action,
    Candidate,
    ErrorInfo,
    Evaluation,
    LogEntry,
    Memory,
    MemoryEntry,
    PendingJob,
    Result,
    State,
    StateDiffEntry,
)
from eqorch.domain.policy import ModeRule, PolicyContext, RetryPolicy, TriggerThresholds


@dataclass(slots=True, frozen=True)
class ArtifactReference:
    uri: str
    kind: str


@dataclass(slots=True, frozen=True)
class PersistenceCommit:
    state_snapshot: State
    state_summaries: dict[str, Any]
    trace_entries: tuple[LogEntry, ...] = ()
    auxiliary_artifacts: tuple[ArtifactReference, ...] = ()


@dataclass(slots=True, frozen=True)
class PersistenceCommitResult:
    committed: bool
    workflow_version: str
    trace_version: str
    auxiliary_enqueued: bool


@dataclass(slots=True, frozen=True)
class PersistenceNotification:
    level: str
    message: str
    should_stop: bool


@dataclass(slots=True, frozen=True)
class _PersistenceJob:
    batch: PersistenceCommit
    result: PersistenceCommitResult


class WorkflowStore:
    """Canonical structured state store."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._init_schema()

    def commit_state(self, snapshot: State, summaries: dict[str, Any]) -> str:
        state_json = json.dumps(_serialize_state(snapshot), ensure_ascii=True, sort_keys=True)
        summaries_json = json.dumps(_normalize_value(summaries), ensure_ascii=True, sort_keys=True)
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO workflow_snapshots (session_id, step, state_json, summaries_json)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot.session_id, snapshot.step, state_json, summaries_json),
            )
            connection.commit()
        return f"{snapshot.session_id}:{snapshot.step}"

    def load_latest(self, session_id: str) -> State | None:
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT state_json
                FROM workflow_snapshots
                WHERE session_id = ?
                ORDER BY step DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _deserialize_state(json.loads(row[0]))

    def load_replay_base(self, session_id: str, step: int | None = None) -> State | None:
        query = """
            SELECT state_json
            FROM workflow_snapshots
            WHERE session_id = ?
        """
        params: list[Any] = [session_id]
        if step is not None:
            query += " AND step <= ?"
            params.append(step)
        query += " ORDER BY step DESC LIMIT 1"
        with sqlite3.connect(self._database_path) as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        return _deserialize_state(json.loads(row[0]))

    def _init_schema(self) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    summaries_json TEXT NOT NULL
                )
                """
            )
            connection.commit()


class TraceStore:
    """Canonical trace store inside the source-of-truth database."""

    def __init__(self, database_path: str) -> None:
        self._database_path = database_path
        self._init_schema()

    def append_entries(self, session_id: str, entries: tuple[LogEntry, ...]) -> str:
        if not entries:
            latest_step = 0
        else:
            latest_step = max(entry.step for entry in entries)
        with sqlite3.connect(self._database_path) as connection:
            for entry in entries:
                connection.execute(
                    """
                    INSERT INTO trace_entries (session_id, step, action_id, entry_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        entry.step,
                        entry.action_id,
                        json.dumps(_normalize_value(asdict(entry)), ensure_ascii=True, sort_keys=True),
                    ),
                )
            connection.commit()
        return f"{session_id}:{latest_step}"

    def load_entries(self, session_id: str, *, up_to_step: int | None = None) -> tuple[LogEntry, ...]:
        query = """
            SELECT entry_json
            FROM trace_entries
            WHERE session_id = ?
        """
        params: list[Any] = [session_id]
        if up_to_step is not None:
            query += " AND step <= ?"
            params.append(up_to_step)
        query += " ORDER BY step ASC, id ASC"
        with sqlite3.connect(self._database_path) as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return tuple(_deserialize_log_entry(json.loads(row[0])) for row in rows)

    def export_jsonl(self, path: str, *, session_id: str | None = None) -> str:
        query = """
            SELECT entry_json
            FROM trace_entries
        """
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY step ASC, id ASC"
        with sqlite3.connect(self._database_path) as connection:
            rows = connection.execute(query, params).fetchall()
        with open(path, "w", encoding="utf-8") as handle:
            for (entry_json,) in rows:
                handle.write(entry_json)
                handle.write("\n")
        return path

    def _init_schema(self) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    action_id TEXT NOT NULL,
                    entry_json TEXT NOT NULL
                )
                """
            )
            connection.commit()


class PersistentMemoryStore:
    """Facade that coordinates canonical workflow and trace persistence."""

    def __init__(
        self,
        database_path: str,
        *,
        workflow_store: WorkflowStore | None = None,
        trace_store: TraceStore | None = None,
        error_coordinator: ErrorCoordinator | None = None,
        max_retries: int = 3,
        notification_callback: Callable[[PersistenceNotification], None] | None = None,
    ) -> None:
        self._database_path = database_path
        self._workflow_store = workflow_store or WorkflowStore(database_path)
        self._trace_store = trace_store or TraceStore(database_path)
        self._error_coordinator = error_coordinator or ErrorCoordinator()
        self._max_retries = max_retries
        self._notification_callback = notification_callback
        self._notifications: list[PersistenceNotification] = []
        self._queue: queue.Queue[_PersistenceJob | None] = queue.Queue()
        self._idle = Event()
        self._idle.set()
        self._lock = Lock()
        self._worker = Thread(target=self._worker_loop, name="persistent-memory-store", daemon=True)
        self._worker.start()

    @property
    def notifications(self) -> tuple[PersistenceNotification, ...]:
        return tuple(self._notifications)

    @property
    def trace_store(self) -> TraceStore:
        return self._trace_store

    def commit(self, batch: PersistenceCommit) -> PersistenceCommitResult:
        result = PersistenceCommitResult(
            committed=True,
            workflow_version=f"{batch.state_snapshot.session_id}:{batch.state_snapshot.step}",
            trace_version=f"{batch.state_snapshot.session_id}:{batch.state_snapshot.step}",
            auxiliary_enqueued=bool(batch.auxiliary_artifacts),
        )
        self._idle.clear()
        self._queue.put(_PersistenceJob(batch=batch, result=result))
        return result

    def load_latest(self, session_id: str) -> State | None:
        return self._workflow_store.load_latest(session_id)

    def load_replay_base(self, session_id: str, step: int | None = None) -> State | None:
        return self._workflow_store.load_replay_base(session_id, step)

    def flush(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout=timeout)

    def close(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=2)

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._idle.set()
                self._queue.task_done()
                return
            try:
                self._process_job(job)
            finally:
                self._queue.task_done()
                if self._queue.unfinished_tasks == 0:
                    self._idle.set()

    def _process_job(self, job: _PersistenceJob) -> None:
        attempts = 0
        while True:
            try:
                self._persist_commit(job.batch)
                return
            except Exception as exc:  # pragma: no cover - exercised through test doubles
                attempts += 1
                if attempts <= self._max_retries:
                    continue
                coordinated = self._error_coordinator.normalize(source="persistence", failure=exc)
                notification = PersistenceNotification(
                    level="error",
                    message=coordinated.error.message,
                    should_stop=coordinated.should_stop,
                )
                self._notifications.append(notification)
                if self._notification_callback is not None:
                    self._notification_callback(notification)
                return

    def _persist_commit(self, batch: PersistenceCommit) -> None:
        with self._lock:
            self._workflow_store.commit_state(batch.state_snapshot, batch.state_summaries)
            self._trace_store.append_entries(batch.state_snapshot.session_id, batch.trace_entries)


def _serialize_state(state: State) -> dict[str, Any]:
    return _normalize_value(asdict(state))


def _normalize_value(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize_value(asdict(value))
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _deserialize_state(raw: dict[str, Any]) -> State:
    policy = _deserialize_policy_context(raw["policy_context"])
    workflow_memory = _deserialize_memory(raw["workflow_memory"])
    return State(
        policy_context=policy,
        workflow_memory=workflow_memory,
        candidates=[_deserialize_candidate(item) for item in raw.get("candidates", [])],
        evaluations=[_deserialize_evaluation(item) for item in raw.get("evaluations", [])],
        current_mode=raw["current_mode"],
        session_id=raw["session_id"],
        step=raw["step"],
        pending_jobs=[_deserialize_pending_job(item) for item in raw.get("pending_jobs", [])],
        last_errors={key: _deserialize_error_info(item) for key, item in raw.get("last_errors", {}).items()},
    )


def _deserialize_policy_context(raw: dict[str, Any]) -> PolicyContext:
    return PolicyContext(
        goals=tuple(raw["goals"]),
        constraints=tuple(raw.get("constraints", [])),
        forbidden_operations=tuple(raw.get("forbidden_operations", [])),
        exploration_strategy=raw.get("exploration_strategy", "expand"),
        mode_switch_criteria=tuple(
            ModeRule(
                condition=rule["condition"],
                target_mode=rule["target_mode"],
                reason=rule["reason"],
            )
            for rule in raw.get("mode_switch_criteria", [])
        ),
        mode_switch_notes=tuple(raw.get("mode_switch_notes", [])),
        max_candidates=raw.get("max_candidates", 100),
        max_evaluations=raw.get("max_evaluations", 500),
        max_memory_entries=raw.get("max_memory_entries", 1000),
        max_parallel_actions=raw.get("max_parallel_actions", 8),
        llm_context_steps=raw.get("llm_context_steps", 20),
        triggers=TriggerThresholds(**raw.get("triggers", {})),
        retry=RetryPolicy(
            max_retries=raw.get("retry", {}).get("max_retries", 3),
            retry_interval_sec=raw.get("retry", {}).get("retry_interval_sec", 5),
            excluded_types=tuple(raw.get("retry", {}).get("excluded_types", ("ask_user", "switch_mode", "terminate"))),
        ),
    )


def _deserialize_memory(raw: dict[str, Any]) -> Memory:
    return Memory(
        entries=[_deserialize_memory_entry(item) for item in raw.get("entries", [])],
        max_entries=raw["max_entries"],
        eviction_policy=raw["eviction_policy"],
    )


def _deserialize_memory_entry(raw: dict[str, Any]) -> MemoryEntry:
    return MemoryEntry(
        key=raw["key"],
        value=raw["value"],
        created_at=raw["created_at"],
        last_accessed=raw["last_accessed"],
    )


def _deserialize_candidate(raw: dict[str, Any]) -> Candidate:
    return Candidate(
        id=raw["id"],
        equation=raw["equation"],
        score=raw["score"],
        reasoning=raw["reasoning"],
        origin=raw["origin"],
        created_at=raw["created_at"],
        step=raw["step"],
    )


def _deserialize_evaluation(raw: dict[str, Any]) -> Evaluation:
    return Evaluation(
        id=raw["id"],
        candidate_id=raw["candidate_id"],
        metrics=raw["metrics"],
        evaluator=raw["evaluator"],
        timestamp=raw["timestamp"],
    )


def _deserialize_error_info(raw: dict[str, Any]) -> ErrorInfo:
    return ErrorInfo(code=raw["code"], message=raw["message"], retryable=raw["retryable"])


def _deserialize_pending_job(raw: dict[str, Any]) -> PendingJob:
    return PendingJob(
        job_id=raw["job_id"],
        engine_name=raw["engine_name"],
        action_id=raw["action_id"],
        issued_at=raw["issued_at"],
        timeout_at=raw["timeout_at"],
    )


def _deserialize_log_entry(raw: dict[str, Any]) -> LogEntry:
    return LogEntry(
        step=raw["step"],
        session_id=raw["session_id"],
        action_id=raw["action_id"],
        action=Action(
            type=raw["action"]["type"],
            target=raw["action"]["target"],
            parameters=raw["action"]["parameters"],
            issued_at=raw["action"]["issued_at"],
            action_id=raw["action"]["action_id"],
        ),
        result=Result(
            status=raw["result"]["status"],
            payload=raw["result"]["payload"],
            error=_deserialize_error_info(raw["result"]["error"]) if raw["result"]["error"] is not None else None,
        ),
        input_summary=raw["input_summary"],
        output_summary=raw["output_summary"],
        state_diff=[
            StateDiffEntry(op=entry["op"], path=entry["path"], value=entry.get("value"))
            for entry in raw.get("state_diff", [])
        ],
        duration_ms=raw["duration_ms"],
        timestamp=raw["timestamp"],
    )


__all__ = [
    "ArtifactReference",
    "PersistenceCommit",
    "PersistenceCommitResult",
    "PersistenceNotification",
    "PersistentMemoryStore",
    "TraceStore",
    "WorkflowStore",
]
