from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.app import ErrorCoordinator
from eqorch.domain import LogEntry, Memory, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory import InMemoryVectorBackend, KnowledgeIndex, PersistenceCommit, PersistentMemoryStore, SqliteConnectionFactory


def _state(*, session_id: str, step: int) -> State:
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=session_id,
        step=step,
    )


class PersistentMemoryStoreTest(unittest.TestCase):
    def test_commits_canonical_state_and_loads_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=1),
                        state_summaries={"summary": "first"},
                    )
                )
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=2),
                        state_summaries={"summary": "latest"},
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                restored = store.load_latest(session_id)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 2)
        self.assertEqual(restored.session_id, session_id)

    def test_load_replay_base_returns_snapshot_for_requested_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                for step in (1, 2, 3):
                    store.commit(
                        PersistenceCommit(
                            state_snapshot=_state(session_id=session_id, step=step),
                            state_summaries={"summary": f"step-{step}"},
                        )
                    )
                self.assertTrue(store.flush(timeout=2))
                restored = store.load_replay_base(session_id, step=2)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 2)

    def test_commit_returns_versions_and_enqueues_auxiliary_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            knowledge_index = KnowledgeIndex(InMemoryVectorBackend())
            store = PersistentMemoryStore(
                database_path,
                connection_factory=SqliteConnectionFactory(database_path),
                auxiliary_publisher=knowledge_index.publish_commit,
            )
            try:
                result = store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=4),
                        state_summaries={"summary": "canonical"},
                        trace_entries=(
                            LogEntry(
                                step=4,
                                session_id=session_id,
                                action_id=str(uuid4()),
                                action=_action(),
                                result=Result(status="success", payload={"ok": True}, error=None),
                                input_summary="{}",
                                output_summary="{}",
                                state_diff=[],
                                duration_ms=1,
                                timestamp="2026-03-22T00:00:00Z",
                            ),
                        ),
                    )
                )
                self.assertTrue(store.flush(timeout=2))
            finally:
                store.close()

        self.assertTrue(result.committed)
        self.assertEqual(result.workflow_version, f"{session_id}:4")
        self.assertEqual(result.trace_version, f"{session_id}:4")
        self.assertTrue(result.auxiliary_enqueued)
        self.assertGreaterEqual(len(knowledge_index.search("canonical", limit=5)), 0)

    def test_trace_store_loads_entries_and_exports_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            export_path = str(Path(tmpdir) / "trace.jsonl")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                entry = LogEntry(
                    step=3,
                    session_id=session_id,
                    action_id=str(uuid4()),
                    action=_action(),
                    result=Result(status="success", payload={"ok": True}, error=None),
                    input_summary='{"before": 1}',
                    output_summary='{"after": 2}',
                    state_diff=[],
                    duration_ms=5,
                    timestamp="2026-03-22T00:00:00Z",
                )
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=3),
                        state_summaries={"summary": "trace"},
                        trace_entries=(entry,),
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                trace_store = store.trace_store
                loaded = trace_store.load_entries(session_id)
                exported = trace_store.export_jsonl(export_path, session_id=session_id)
                lines = Path(exported).read_text(encoding="utf-8").strip().splitlines()
            finally:
                store.close()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].action_id, entry.action_id)
        self.assertEqual(len(lines), 1)
        self.assertIn(entry.action_id, lines[0])

    def test_notifies_after_retry_exhaustion_on_canonical_failure(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(
                database_path,
                connection_factory=SqliteConnectionFactory(database_path),
                error_coordinator=ErrorCoordinator(),
                max_retries=1,
                notification_callback=notifications.append,
            )
            try:
                def always_fail(batch):
                    raise RuntimeError("disk full")

                store._persist_commit = always_fail  # type: ignore[method-assign]
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=1),
                        state_summaries={"summary": "fail"},
                    )
                )
                self.assertTrue(store.flush(timeout=2))
            finally:
                store.close()

        self.assertEqual(len(notifications), 1)
        self.assertTrue(notifications[0].should_stop)
        self.assertIn("disk full", notifications[0].message)


def _action():
    from eqorch.domain import Action

    return Action(
        type="terminate",
        target="system",
        parameters={"reason": "done"},
        issued_at="2026-03-22T00:00:00Z",
        action_id=str(uuid4()),
    )


if __name__ == "__main__":
    unittest.main()
