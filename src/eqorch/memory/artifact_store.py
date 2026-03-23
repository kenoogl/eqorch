"""Auxiliary artifact storage for large payload references."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .persistent_store import ArtifactReference, PersistenceCommit


class ArtifactBackend(Protocol):
    """Backend contract for object-storage-like artifact persistence."""

    def put_object(self, key: str, payload: bytes, *, content_type: str) -> str:
        ...


@dataclass(slots=True, frozen=True)
class StoredArtifact:
    key: str
    uri: str
    content_type: str
    payload: bytes


class InMemoryArtifactBackend:
    """Deterministic backend used for tests and local fallback."""

    def __init__(self, *, uri_prefix: str = "memory://artifacts") -> None:
        self._uri_prefix = uri_prefix.rstrip("/")
        self._objects: dict[str, StoredArtifact] = {}

    def put_object(self, key: str, payload: bytes, *, content_type: str) -> str:
        uri = f"{self._uri_prefix}/{key}"
        self._objects[key] = StoredArtifact(key=key, uri=uri, content_type=content_type, payload=payload)
        return uri

    def list_objects(self) -> tuple[StoredArtifact, ...]:
        return tuple(self._objects[key] for key in sorted(self._objects))


class LocalArtifactBackend:
    """Filesystem-backed object store used as a local stand-in for object storage."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def put_object(self, key: str, payload: bytes, *, content_type: str) -> str:
        del content_type
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path.as_uri()


@dataclass(slots=True, frozen=True)
class ArtifactManifest:
    source_uri: str
    stored_uri: str
    kind: str
    session_id: str
    step: int


class ArtifactStore:
    """Stores artifact references as auxiliary manifests in object storage."""

    def __init__(self, backend: ArtifactBackend | None = None, *, enabled: bool = True) -> None:
        self._backend = backend or InMemoryArtifactBackend()
        self._enabled = enabled
        self._manifests: list[ArtifactManifest] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def publish_commit(self, batch: PersistenceCommit) -> int:
        if not self._enabled or not batch.auxiliary_artifacts:
            return 0

        count = 0
        for index, reference in enumerate(batch.auxiliary_artifacts):
            manifest = self._store_reference(batch, reference, index=index)
            self._manifests.append(manifest)
            count += 1
        return count

    def list_manifests(self) -> tuple[ArtifactManifest, ...]:
        return tuple(self._manifests)

    def _store_reference(self, batch: PersistenceCommit, reference: ArtifactReference, *, index: int) -> ArtifactManifest:
        key = f"{batch.state_snapshot.session_id}/{batch.state_snapshot.step}/{index:03d}-{reference.kind}.json"
        envelope = {
            "session_id": batch.state_snapshot.session_id,
            "step": batch.state_snapshot.step,
            "kind": reference.kind,
            "source_uri": reference.uri,
            "state_summaries": _normalize(batch.state_summaries),
        }
        stored_uri = self._backend.put_object(
            key,
            json.dumps(envelope, ensure_ascii=True, sort_keys=True).encode("utf-8"),
            content_type="application/json",
        )
        return ArtifactManifest(
            source_uri=reference.uri,
            stored_uri=stored_uri,
            kind=reference.kind,
            session_id=batch.state_snapshot.session_id,
            step=batch.state_snapshot.step,
        )


class CompositeAuxiliaryPublisher:
    """Invokes multiple auxiliary publishers in order."""

    def __init__(self, *publishers) -> None:
        self._publishers = tuple(publisher for publisher in publishers if publisher is not None)

    def __call__(self, batch: PersistenceCommit) -> None:
        for publisher in self._publishers:
            publisher(batch)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    return value


__all__ = [
    "ArtifactBackend",
    "ArtifactManifest",
    "ArtifactStore",
    "CompositeAuxiliaryPublisher",
    "InMemoryArtifactBackend",
    "LocalArtifactBackend",
    "StoredArtifact",
]
