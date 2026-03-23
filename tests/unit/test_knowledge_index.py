from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.domain import Candidate, Memory, MemoryEntry, State
from eqorch.domain.policy import PolicyContext
from eqorch.memory.knowledge_index import InMemoryVectorBackend, KnowledgeIndex
from eqorch.memory.persistent_store import PersistenceCommit


def _state() -> State:
    candidate = Candidate(
        id=str(uuid4()),
        equation="x + y",
        score=0.9,
        reasoning="linear relation between x and y",
        origin="LLM",
        created_at="2026-03-23T00:00:00Z",
        step=1,
    )
    memory_entry = MemoryEntry(
        key="paper:1",
        value={"kind": "external_knowledge", "title": "Linear models", "summary": "x and y remain linear"},
        created_at="2026-03-23T00:00:00Z",
        last_accessed="2026-03-23T00:00:00Z",
    )
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[memory_entry], max_entries=10, eviction_policy="lru"),
        candidates=[candidate],
        session_id=str(uuid4()),
        step=1,
    )


class KnowledgeIndexTest(unittest.TestCase):
    def test_publish_commit_indexes_candidates_and_external_knowledge(self) -> None:
        index = KnowledgeIndex(InMemoryVectorBackend())
        state = _state()

        indexed = index.publish_commit(
            PersistenceCommit(
                state_snapshot=state,
                state_summaries={"summary": "state"},
            )
        )
        hits = index.search("linear x y", limit=5)

        self.assertEqual(indexed, 2)
        self.assertGreaterEqual(len(hits), 2)
        self.assertEqual(hits[0].source_kind, "candidate")
        self.assertIn("candidate_id", hits[0].metadata)

    def test_disabled_index_is_noop(self) -> None:
        index = KnowledgeIndex(InMemoryVectorBackend(), enabled=False)

        indexed = index.publish_commit(
            PersistenceCommit(
                state_snapshot=_state(),
                state_summaries={"summary": "state"},
            )
        )

        self.assertEqual(indexed, 0)
        self.assertEqual(index.search("linear"), ())


if __name__ == "__main__":
    unittest.main()
