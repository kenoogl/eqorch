from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.domain import Memory, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory import (
    ArtifactReference,
    ArtifactStore,
    InMemoryArtifactBackend,
    LocalArtifactBackend,
    PersistenceCommit,
)


def _state(*, session_id: str, step: int) -> State:
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=session_id,
        step=step,
    )


class ArtifactStoreTest(unittest.TestCase):
    def test_publishes_auxiliary_artifact_manifests(self) -> None:
        backend = InMemoryArtifactBackend()
        store = ArtifactStore(backend)
        session_id = str(uuid4())

        stored = store.publish_commit(
            PersistenceCommit(
                state_snapshot=_state(session_id=session_id, step=4),
                state_summaries={"summary": "artifact"},
                auxiliary_artifacts=(
                    ArtifactReference(uri="s3://raw/log.txt", kind="raw_log"),
                    ArtifactReference(uri="s3://reports/result.json", kind="report"),
                ),
            )
        )

        self.assertEqual(stored, 2)
        manifests = store.list_manifests()
        self.assertEqual(len(manifests), 2)
        self.assertEqual(manifests[0].source_uri, "s3://raw/log.txt")
        objects = backend.list_objects()
        self.assertEqual(len(objects), 2)
        payload = json.loads(objects[0].payload.decode("utf-8"))
        self.assertEqual(payload["session_id"], session_id)
        self.assertIn("source_uri", payload)

    def test_local_backend_writes_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = LocalArtifactBackend(tmpdir)
            store = ArtifactStore(backend)
            session_id = str(uuid4())

            stored = store.publish_commit(
                PersistenceCommit(
                    state_snapshot=_state(session_id=session_id, step=1),
                    state_summaries={"summary": "local"},
                    auxiliary_artifacts=(ArtifactReference(uri="file:///tmp/report.txt", kind="report"),),
                )
            )

            self.assertEqual(stored, 1)
            manifests = store.list_manifests()
            self.assertEqual(len(manifests), 1)
            stored_path = Path(manifests[0].stored_uri.removeprefix("file://"))
            self.assertTrue(stored_path.exists())

    def test_disabled_store_is_noop(self) -> None:
        backend = InMemoryArtifactBackend()
        store = ArtifactStore(backend, enabled=False)

        stored = store.publish_commit(
            PersistenceCommit(
                state_snapshot=_state(session_id=str(uuid4()), step=1),
                state_summaries={"summary": "disabled"},
                auxiliary_artifacts=(ArtifactReference(uri="s3://unused", kind="report"),),
            )
        )

        self.assertEqual(stored, 0)
        self.assertEqual(store.list_manifests(), ())
        self.assertEqual(backend.list_objects(), ())


if __name__ == "__main__":
    unittest.main()
