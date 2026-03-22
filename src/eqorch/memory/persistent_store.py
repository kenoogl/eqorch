"""Persistent memory store backed by SQLite and JSON Lines."""

from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import sqlite3
from threading import Event, Lock, Thread
from typing import Any, Callable

from eqorch.app import ErrorCoordinator


@dataclass(slots=True, frozen=True)
class PersistenceNotification:
    level: str
    message: str
    should_stop: bool


@dataclass(slots=True, frozen=True)
class PersistenceJob:
    kind: str
    payload: dict[str, Any]


class PersistentMemoryStore:
    """Asynchronously persists workflow snapshots and trace records."""

    def __init__(
        self,
        sqlite_path: str,
        *,
        jsonl_path: str | None = None,
        error_coordinator: ErrorCoordinator | None = None,
        max_retries: int = 3,
        notification_callback: Callable[[PersistenceNotification], None] | None = None,
    ) -> None:
        self._sqlite_path = sqlite_path
        self._jsonl_path = jsonl_path
        self._error_coordinator = error_coordinator or ErrorCoordinator()
        self._max_retries = max_retries
        self._notification_callback = notification_callback
        self._notifications: list[PersistenceNotification] = []
        self._queue: queue.Queue[PersistenceJob | None] = queue.Queue()
        self._idle = Event()
        self._idle.set()
        self._lock = Lock()
        self._init_db()
        self._worker = Thread(target=self._worker_loop, name="persistent-memory-store", daemon=True)
        self._worker.start()

    @property
    def notifications(self) -> tuple[PersistenceNotification, ...]:
        return tuple(self._notifications)

    def enqueue_snapshot(self, *, session_id: str, step: int, snapshot: dict[str, Any]) -> None:
        self._enqueue(PersistenceJob(kind="snapshot", payload={"session_id": session_id, "step": step, "snapshot": snapshot}))

    def enqueue_trace(self, *, session_id: str, step: int, trace: dict[str, Any]) -> None:
        self._enqueue(PersistenceJob(kind="trace", payload={"session_id": session_id, "step": step, "trace": trace}))

    def flush(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout=timeout)

    def close(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=2)

    def load_latest_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._sqlite_path) as connection:
            row = connection.execute(
                """
                SELECT snapshot_json
                FROM snapshots
                WHERE session_id = ?
                ORDER BY step DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def export_jsonl(self, path: str | None = None) -> str:
        output_path = path or self._jsonl_path
        if output_path is None:
            raise ValueError("jsonl output path is not configured")
        with sqlite3.connect(self._sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT kind, session_id, step, payload_json
                FROM jsonl_events
                ORDER BY id ASC
                """
            ).fetchall()
        with open(output_path, "w", encoding="utf-8") as handle:
            for kind, session_id, step, payload_json in rows:
                record = {
                    "kind": kind,
                    "session_id": session_id,
                    "step": step,
                    "payload": json.loads(payload_json),
                }
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        return output_path

    def _enqueue(self, job: PersistenceJob) -> None:
        self._idle.clear()
        self._queue.put(job)

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

    def _process_job(self, job: PersistenceJob) -> None:
        attempts = 0
        while True:
            try:
                self._persist_job(job)
                return
            except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
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

    def _persist_job(self, job: PersistenceJob) -> None:
        payload_json = json.dumps(job.payload, ensure_ascii=True)
        with self._lock, sqlite3.connect(self._sqlite_path) as connection:
            if job.kind == "snapshot":
                connection.execute(
                    """
                    INSERT INTO snapshots (session_id, step, snapshot_json)
                    VALUES (?, ?, ?)
                    """,
                    (job.payload["session_id"], job.payload["step"], json.dumps(job.payload["snapshot"], ensure_ascii=True)),
                )
            connection.execute(
                """
                INSERT INTO jsonl_events (kind, session_id, step, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (job.kind, job.payload["session_id"], job.payload["step"], payload_json),
            )
            connection.commit()

    def _init_db(self) -> None:
        with sqlite3.connect(self._sqlite_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jsonl_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

