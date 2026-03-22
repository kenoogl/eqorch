from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eqorch.app import ErrorCoordinator
from eqorch.memory import PersistentMemoryStore


class PersistentMemoryStoreTest(unittest.TestCase):
    def test_persists_snapshots_to_sqlite_and_restores_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "memory.sqlite")
            store = PersistentMemoryStore(sqlite_path)
            try:
                store.enqueue_snapshot(session_id="session-1", step=1, snapshot={"step": 1})
                store.enqueue_snapshot(session_id="session-1", step=2, snapshot={"step": 2, "state": "latest"})
                self.assertTrue(store.flush(timeout=2))
                restored = store.load_latest_snapshot("session-1")
            finally:
                store.close()

        self.assertEqual(restored["step"], 2)
        self.assertEqual(restored["state"], "latest")

    def test_exports_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "memory.sqlite")
            jsonl_path = str(Path(tmpdir) / "trace.jsonl")
            store = PersistentMemoryStore(sqlite_path, jsonl_path=jsonl_path)
            try:
                store.enqueue_trace(session_id="session-1", step=3, trace={"action": "call_tool"})
                self.assertTrue(store.flush(timeout=2))
                exported = store.export_jsonl()
            finally:
                store.close()

            lines = Path(exported).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["kind"], "trace")
        self.assertEqual(record["payload"]["trace"]["action"], "call_tool")

    def test_notifies_after_retry_exhaustion(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "memory.sqlite")
            store = PersistentMemoryStore(
                sqlite_path,
                error_coordinator=ErrorCoordinator(),
                max_retries=1,
                notification_callback=notifications.append,
            )
            try:
                def always_fail(job):
                    raise RuntimeError("disk full")

                store._persist_job = always_fail  # type: ignore[method-assign]
                store.enqueue_snapshot(session_id="session-1", step=1, snapshot={"step": 1})
                self.assertTrue(store.flush(timeout=2))
            finally:
                store.close()

        self.assertEqual(len(notifications), 1)
        self.assertTrue(notifications[0].should_stop)
        self.assertIn("disk full", notifications[0].message)


if __name__ == "__main__":
    unittest.main()
