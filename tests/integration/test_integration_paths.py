from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.app import ErrorCoordinator, PolicyContextStore, ResearchConcierge, RetryPolicyExecutor
from eqorch.domain import Memory, State
from eqorch.domain.policy import PolicyContext
from eqorch.gateways import BackendExecutionResult, BackendGateway, EngineGateway, LLMGateway, ResultNormalizer
from eqorch.memory import (
    ArtifactReference,
    ArtifactStore,
    CompositeAuxiliaryPublisher,
    InMemoryVectorBackend,
    InMemoryArtifactBackend,
    KnowledgeIndex,
    PersistenceCommit,
    PersistentMemoryStore,
    ReplayLoader,
    SqliteConnectionFactory,
)
from eqorch.orchestrator import ActionDispatcher, DecisionContextAssembler, OrchestrationLoop
from eqorch.registry import ComponentConfigLoader, EngineRegistry, SkillRegistry, ToolRegistry
from eqorch.tracing import TraceRecorder


class SequencedAdapter:
    def __init__(self) -> None:
        self._calls = 0

    def decide(self, payload):
        self._calls += 1
        if self._calls == 1:
            batch = [
                {
                    "type": "run_engine",
                    "target": "rest_engine",
                    "parameters": {"instruction": "fit", "async": True},
                    "issued_at": "2026-03-23T00:00:00Z",
                    "action_id": "00000000-0000-4000-8000-000000000021",
                }
            ]
        else:
            batch = [
                {
                    "type": "terminate",
                    "target": "system",
                    "parameters": {"reason": "done"},
                    "issued_at": "2026-03-23T00:00:01Z",
                    "action_id": "00000000-0000-4000-8000-000000000022",
                }
            ]
        return {"choices": [{"message": {"content": json.dumps(batch)}}]}


class StubTransport:
    def __init__(self, protocol: str) -> None:
        self.protocol = protocol

    def run(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"status": "success", "payload": {"protocol": self.protocol, "instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"job_id": f"{self.protocol}-job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int):
        return {
            "status": "success",
            "payload": {"protocol": self.protocol, "job_id": job_id, "numeric_results": {"score": 1.0}},
        }

    def cancel(self, endpoint: str, job_id: str, timeout_sec: int):
        return {"status": "success", "payload": {"job_id": job_id}}


class StubBackendRunner:
    def run(self, command, config):
        return BackendExecutionResult(status="success", numeric_results={"mse": 0.1}, error=None)


class FailingArtifactBackend:
    def put_object(self, key: str, payload: bytes, *, content_type: str) -> str:
        del key, payload, content_type
        raise RuntimeError("artifact store unavailable")


class IntegrationPathsTest(unittest.TestCase):
    def test_components_async_poll_and_replay_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path, policy_path = _write_fixture_environment(root)
            database_path = root / "integration.db"
            policy_store = PolicyContextStore()
            policy = policy_store.load_file(policy_path)
            config = ComponentConfigLoader().load_file(config_path)

            skill_registry = SkillRegistry()
            skill_registry.register_from_config(config.skills)
            tool_registry = ToolRegistry()
            tool_registry.register_from_config(config.tools)
            engine_registry = EngineRegistry()
            engine_registry.register_from_config(config.engines)
            transports = {"rest": StubTransport("rest"), "grpc": StubTransport("grpc")}
            engine_gateway = EngineGateway(engine_registry, transports)
            backend_gateway = BackendGateway(
                config.backends,
                runners={backend.name: StubBackendRunner() for backend in config.backends},
                normalizer=ResultNormalizer(),
            )
            persistent_store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
            )
            trace_recorder = TraceRecorder()
            error_coordinator = ErrorCoordinator()
            dispatcher = ActionDispatcher(
                skill_registry=skill_registry,
                tool_registry=tool_registry,
                engine_gateway=engine_gateway,
                backend_gateway=backend_gateway,
                policy_store=policy_store,
                error_coordinator=error_coordinator,
                trace_recorder=trace_recorder,
            )
            loop = OrchestrationLoop(
                context_assembler=DecisionContextAssembler(),
                concierge=ResearchConcierge(
                    gateway=LLMGateway(provider="openai", adapter=SequencedAdapter()),
                    error_coordinator=error_coordinator,
                    retry_executor=RetryPolicyExecutor(),
                ),
                dispatcher=dispatcher,
                trace_recorder=trace_recorder,
                persistent_store=persistent_store,
                error_coordinator=error_coordinator,
            )
            try:
                state = State(
                    policy_context=policy,
                    workflow_memory=Memory(entries=[], max_entries=policy.max_memory_entries, eviction_policy="lru"),
                    session_id=str(uuid4()),
                    current_mode="interactive",
                )
                first = loop.run_cycle(state, issued_at="2026-03-23T00:00:00Z")
                second = loop.run_cycle(first.state, issued_at="2026-03-23T00:00:01Z")
                self.assertTrue(persistent_store.flush(timeout=5))
                replay = ReplayLoader(persistent_store).load_verified_frame(second.state.session_id)
            finally:
                persistent_store.close()

        self.assertEqual(len(first.state.pending_jobs), 1)
        self.assertFalse(second.should_continue)
        self.assertIsNotNone(replay)
        self.assertEqual(replay.base_state.session_id, second.state.session_id)
        self.assertGreaterEqual(len(replay.trace_entries), 2)

    def test_persistence_failure_notifies_and_requests_stop(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "fail.db"
            store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
                error_coordinator=ErrorCoordinator(),
                max_retries=1,
                notification_callback=notifications.append,
            )
            try:
                store._persist_commit = lambda batch: (_ for _ in ()).throw(RuntimeError("disk full"))  # type: ignore[method-assign]
                store.commit(
                    PersistenceCommit(
                        state_snapshot=State(
                            policy_context=PolicyContext(goals=("goal",)),
                            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
                            session_id=str(uuid4()),
                        ),
                        state_summaries={"step": 0},
                    )
                )
                self.assertTrue(store.flush(timeout=5))
            finally:
                store.close()

        self.assertEqual(len(notifications), 1)
        self.assertTrue(notifications[0].should_stop)

    def test_auxiliary_failure_does_not_break_canonical_reproducibility(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "aux.db"
            session_id = str(uuid4())
            artifact_store = ArtifactStore(FailingArtifactBackend())
            store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
                notification_callback=notifications.append,
                auxiliary_publisher=artifact_store.publish_commit,
            )
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=State(
                            policy_context=PolicyContext(goals=("goal",)),
                            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
                            session_id=session_id,
                            step=1,
                        ),
                        state_summaries={"step": 1},
                        auxiliary_artifacts=(ArtifactReference(uri="s3://artifact", kind="report"),),
                    )
                )
                self.assertTrue(store.flush(timeout=5))
                restored = store.load_latest(session_id)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 1)
        self.assertEqual(len(notifications), 1)
        self.assertFalse(notifications[0].should_stop)

    def test_knowledge_index_indexes_candidates_and_auxiliary_failure_is_non_fatal(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "knowledge.db"
            session_id = str(uuid4())
            state = State(
                policy_context=PolicyContext(goals=("goal",)),
                workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
                session_id=session_id,
                step=2,
                candidates=[],
            )
            from eqorch.domain import Candidate

            state.candidates.append(
                Candidate(
                    id=str(uuid4()),
                    equation="x + y",
                    score=0.8,
                    reasoning="linear relation discovered from prior fits",
                    origin="Engine",
                    created_at="2026-03-23T00:00:00Z",
                    step=2,
                )
            )
            index = KnowledgeIndex(InMemoryVectorBackend())
            store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
                notification_callback=notifications.append,
                auxiliary_publisher=index.publish_commit,
            )
            try:
                store.commit(PersistenceCommit(state_snapshot=state, state_summaries={"step": 2}))
                self.assertTrue(store.flush(timeout=5))
                restored = store.load_latest(session_id)
                hits = index.search("linear relation", limit=3)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 2)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].source_kind, "candidate")

    def test_artifact_store_persists_auxiliary_references_without_affecting_canonical_state(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "artifact.db"
            artifact_store = ArtifactStore(InMemoryArtifactBackend())
            session_id = str(uuid4())
            store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
                notification_callback=notifications.append,
                auxiliary_publisher=artifact_store.publish_commit,
            )
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=State(
                            policy_context=PolicyContext(goals=("goal",)),
                            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
                            session_id=session_id,
                            step=3,
                        ),
                        state_summaries={"step": 3},
                        auxiliary_artifacts=(
                            ArtifactReference(uri="file:///tmp/raw.log", kind="raw_log"),
                            ArtifactReference(uri="file:///tmp/result.json", kind="report"),
                        ),
                    )
                )
                self.assertTrue(store.flush(timeout=5))
                restored = store.load_latest(session_id)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 3)
        self.assertEqual(len(artifact_store.list_manifests()), 2)
        self.assertEqual(notifications, [])

    def test_knowledge_index_failure_does_not_break_canonical_reproducibility(self) -> None:
        notifications = []
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "knowledge-fail.db"
            session_id = str(uuid4())
            store = PersistentMemoryStore(
                str(database_path),
                connection_factory=SqliteConnectionFactory(str(database_path)),
                notification_callback=notifications.append,
                auxiliary_publisher=lambda batch: (_ for _ in ()).throw(RuntimeError("knowledge index unavailable")),
            )
            try:
                store.commit(
                    PersistenceCommit(
                        state_snapshot=State(
                            policy_context=PolicyContext(goals=("goal",)),
                            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="lru"),
                            session_id=session_id,
                            step=1,
                        ),
                        state_summaries={"step": 1},
                    )
                )
                self.assertTrue(store.flush(timeout=5))
                restored = store.load_latest(session_id)
            finally:
                store.close()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 1)
        self.assertEqual(len(notifications), 1)
        self.assertFalse(notifications[0].should_stop)


def _write_fixture_environment(root: Path) -> tuple[Path, Path]:
    fixture_root = root / "integration_fixtures"
    fixture_root.mkdir()
    (fixture_root / "__init__.py").write_text("", encoding="utf-8")
    (fixture_root / "skill_impl.py").write_text(
        "from eqorch.domain import Result\n\nclass DummySkill:\n    def execute(self, request):\n        return Result(status='success', payload={'skill': True}, error=None)\n",
        encoding="utf-8",
    )
    (fixture_root / "tool_impl.py").write_text(
        "from eqorch.domain import Result\n\nclass DummyTool:\n    def execute(self, request):\n        return Result(status='success', payload={'tool': True}, error=None)\n",
        encoding="utf-8",
    )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    config_path = root / "components.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            skills:
              - name: dummy_skill
                module: integration_fixtures.skill_impl
                class: DummySkill
            tools:
              - name: dummy_tool
                module: integration_fixtures.tool_impl
                class: DummyTool
            engines:
              - name: rest_engine
                endpoint: http://localhost:8080/run
                protocol: rest
              - name: grpc_engine
                endpoint: dns:///engine
                protocol: grpc
                proto: path/to/engine.proto
                service: EngineService
            backends:
              - name: julia_runner
                executable: julia
                args: ["run.jl"]
            """
        ).strip(),
        encoding="utf-8",
    )
    policy_path = root / "policy.yaml"
    policy_path.write_text("goals:\n  - find equation\n", encoding="utf-8")
    return config_path, policy_path


if __name__ == "__main__":
    unittest.main()
