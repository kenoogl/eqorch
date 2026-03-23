from __future__ import annotations

import os
import unittest
from uuid import uuid4

from eqorch.domain import Action, LogEntry, Memory, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory import PersistenceCommit, PersistentMemoryStore, PostgresConnectionFactory, ReplayLoader


def _database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _state(*, session_id: str, step: int) -> State:
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
        session_id=session_id,
        step=step,
    )


@unittest.skipUnless(_database_url(), "TEST_DATABASE_URL is required for PostgreSQL integration tests")
class PostgresPersistenceIntegrationTest(unittest.TestCase):
    def test_commits_workflow_trace_and_replay_with_real_postgres(self) -> None:
        session_id = str(uuid4())
        store = PersistentMemoryStore(
            _database_url() or "",
            connection_factory=PostgresConnectionFactory(_database_url() or ""),
        )
        try:
            store.commit(
                PersistenceCommit(
                    state_snapshot=_state(session_id=session_id, step=1),
                    state_summaries={"summary": "first"},
                    trace_entries=(
                        LogEntry(
                            step=1,
                            session_id=session_id,
                            action_id=str(uuid4()),
                            action=Action(
                                type="terminate",
                                target="system",
                                parameters={"reason": "done"},
                                issued_at="2026-03-23T00:00:00Z",
                                action_id=str(uuid4()),
                            ),
                            result=Result(status="success", payload={"ok": True}, error=None),
                            input_summary='{"state":"before"}',
                            output_summary='{"session_id":"%s","step":1}' % session_id,
                            state_diff=[],
                            duration_ms=1,
                            timestamp="2026-03-23T00:00:00Z",
                        ),
                    ),
                )
            )
            self.assertTrue(store.flush(timeout=5))
            latest = store.load_latest(session_id)
            replay = ReplayLoader(store).load_verified_frame(session_id)
        finally:
            store.close()

        self.assertIsNotNone(latest)
        self.assertEqual(latest.step, 1)
        self.assertIsNotNone(replay)
        self.assertEqual(replay.base_state.session_id, session_id)
        self.assertEqual(len(replay.trace_entries), 1)


if __name__ == "__main__":
    unittest.main()
