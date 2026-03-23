"""Auxiliary knowledge index for semantic lookup."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Protocol, TYPE_CHECKING

from eqorch.domain import Candidate, MemoryEntry, State

if TYPE_CHECKING:
    from .persistent_store import PersistenceCommit


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_:+./-]+")


class VectorIndexBackend(Protocol):
    """Backend contract for auxiliary vector-like indexes."""

    def upsert(self, documents: tuple["KnowledgeDocument", ...]) -> None:
        ...

    def search(self, query: str, *, limit: int = 5) -> tuple["KnowledgeHit", ...]:
        ...


@dataclass(slots=True, frozen=True)
class KnowledgeDocument:
    document_id: str
    source_kind: str
    session_id: str
    step: int
    text: str
    metadata: dict[str, Any]


@dataclass(slots=True, frozen=True)
class KnowledgeHit:
    document_id: str
    source_kind: str
    score: float
    text: str
    metadata: dict[str, Any]


class InMemoryVectorBackend:
    """Deterministic backend used for tests and local fallback."""

    def __init__(self) -> None:
        self._documents: dict[str, tuple[KnowledgeDocument, set[str]]] = {}

    def upsert(self, documents: tuple[KnowledgeDocument, ...]) -> None:
        for document in documents:
            self._documents[document.document_id] = (document, _tokenize(document.text))

    def search(self, query: str, *, limit: int = 5) -> tuple[KnowledgeHit, ...]:
        if limit <= 0:
            return ()
        query_tokens = _tokenize(query)
        scored: list[KnowledgeHit] = []
        for document_id, (document, tokens) in self._documents.items():
            score = _similarity(query_tokens, tokens)
            if score <= 0.0:
                continue
            scored.append(
                KnowledgeHit(
                    document_id=document_id,
                    source_kind=document.source_kind,
                    score=score,
                    text=document.text,
                    metadata=document.metadata,
                )
            )
        scored.sort(key=lambda hit: (-hit.score, hit.document_id))
        return tuple(scored[:limit])


class KnowledgeIndex:
    """Indexes candidates, reasoning, and external knowledge as an auxiliary layer."""

    def __init__(self, backend: VectorIndexBackend | None = None, *, enabled: bool = True) -> None:
        self._backend = backend or InMemoryVectorBackend()
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def publish_commit(self, batch: PersistenceCommit) -> int:
        if not self._enabled:
            return 0
        documents = self._documents_for_state(batch.state_snapshot)
        if not documents:
            return 0
        self._backend.upsert(documents)
        return len(documents)

    def search(self, query: str, *, limit: int = 5) -> tuple[KnowledgeHit, ...]:
        if not self._enabled:
            return ()
        return self._backend.search(query, limit=limit)

    def _documents_for_state(self, state: State) -> tuple[KnowledgeDocument, ...]:
        documents: list[KnowledgeDocument] = []
        for candidate in state.candidates:
            documents.append(_candidate_document(state, candidate))
        for entry in state.workflow_memory.entries:
            document = _memory_document(state, entry)
            if document is not None:
                documents.append(document)
        return tuple(documents)


def _candidate_document(state: State, candidate: Candidate) -> KnowledgeDocument:
    text = f"{candidate.equation}\n{candidate.reasoning}"
    return KnowledgeDocument(
        document_id=f"{state.session_id}:candidate:{candidate.id}",
        source_kind="candidate",
        session_id=state.session_id,
        step=state.step,
        text=text,
        metadata={
            "candidate_id": candidate.id,
            "equation": candidate.equation,
            "origin": candidate.origin,
            "step": candidate.step,
        },
    )


def _memory_document(state: State, entry: MemoryEntry) -> KnowledgeDocument | None:
    kind = str(entry.value.get("kind", "memory"))
    if kind not in {"external_knowledge", "knowledge", "memory"}:
        return None
    content = json.dumps(entry.value, ensure_ascii=True, sort_keys=True)
    return KnowledgeDocument(
        document_id=f"{state.session_id}:memory:{entry.key}",
        source_kind="external_knowledge" if kind != "memory" else "memory",
        session_id=state.session_id,
        step=state.step,
        text=content,
        metadata={"memory_key": entry.key, "kind": kind},
    )


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(text)}


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap == 0:
        return 0.0
    return overlap / math.sqrt(len(left) * len(right))


__all__ = [
    "InMemoryVectorBackend",
    "KnowledgeDocument",
    "KnowledgeHit",
    "KnowledgeIndex",
    "VectorIndexBackend",
]
