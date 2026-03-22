from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.domain import Action, LogEntry, Memory, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory import PersistenceCommit, PersistentMemoryStore, ReplayLoader, SqliteConnectionFactory


def _state(*, session_id: str, step: int, mode: str = "interactive") -> State:
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=session_id,
        step=step,
        current_mode=mode,
    )


def _entry(*, session_id: str, step: int, before_mode: str = "interactive", after_mode: str = "batch") -> LogEntry:
    return LogEntry(
        step=step,
        session_id=session_id,
        action_id=str(uuid4()),
        action=Action(
            type="switch_mode",
            target="system",
            parameters={"target_mode": "batch"},
            issued_at="2026-03-22T00:00:00Z",
            action_id=str(uuid4()),
        ),
        result=Result(status="success", payload={"target_mode": after_mode}, error=None),
        input_summary=f'{{"current_mode": "{before_mode}", "session_id": "{session_id}", "step": {step}}}',
        output_summary=f'{{"current_mode": "{after_mode}", "session_id": "{session_id}", "step": {step}}}',
        state_diff=[],
        duration_ms=1,
        timestamp="2026-03-22T00:00:00Z",
    )


class ReplayLoaderTest(unittest.TestCase):
    def test_loads_latest_state_for_restart(self) -> None:
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
                        state_snapshot=_state(session_id=session_id, step=2, mode="batch"),
                        state_summaries={"summary": "latest"},
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                loader = ReplayLoader(store)
                restored = loader.load_latest(session_id)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 2)
        self.assertEqual(restored.current_mode, "batch")

    def test_loads_replay_frame_with_base_state_and_trace_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=1),
                        state_summaries={"summary": "step-1"},
                        trace_entries=(_entry(session_id=session_id, step=1, after_mode="interactive"),),
                    )
                )
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=2, mode="batch"),
                        state_summaries={"summary": "step-2"},
                        trace_entries=(_entry(session_id=session_id, step=2),),
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                loader = ReplayLoader(store)
                frame = loader.load_verified_frame(session_id, step=2)
            finally:
                store.close()

        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.base_state.step, 2)
        self.assertEqual(len(frame.trace_entries), 2)
        self.assertEqual(frame.trace_entries[-1].step, 2)

    def test_verifies_output_summary_matches_replay_base_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=1),
                        state_summaries={"summary": "step-1"},
                        trace_entries=(_entry(session_id=session_id, step=1, after_mode="interactive"),),
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                loader = ReplayLoader(store)
                frame = loader.load_frame(session_id, step=1)
                assert frame is not None
                verification = loader.verify_frame(frame, expected_step=1)
            finally:
                store.close()

        self.assertEqual(verification.matched_step, 1)
        self.assertEqual(verification.trace_count, 1)
        self.assertEqual(len(verification.verified_action_ids), 1)

    def test_rejects_mismatched_output_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = str(Path(tmpdir) / "memory.db")
            session_id = str(uuid4())
            store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
            try:
                bad_entry = LogEntry(
                    step=1,
                    session_id=session_id,
                    action_id=str(uuid4()),
                    action=Action(
                        type="switch_mode",
                        target="system",
                        parameters={"target_mode": "batch"},
                        issued_at="2026-03-22T00:00:00Z",
                        action_id=str(uuid4()),
                    ),
                    result=Result(status="success", payload={"target_mode": "batch"}, error=None),
                    input_summary='{"current_mode": "interactive"}',
                    output_summary='{"current_mode": "invalid"}',
                    state_diff=[],
                    duration_ms=1,
                    timestamp="2026-03-22T00:00:00Z",
                )
                store.commit(
                    PersistenceCommit(
                        state_snapshot=_state(session_id=session_id, step=1),
                        state_summaries={"summary": "step-1"},
                        trace_entries=(bad_entry,),
                    )
                )
                self.assertTrue(store.flush(timeout=2))
                loader = ReplayLoader(store)
                frame = loader.load_frame(session_id, step=1)
                assert frame is not None
                with self.assertRaisesRegex(ValueError, "trace output summary does not match replay base state"):
                    loader.verify_frame(frame, expected_step=1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
