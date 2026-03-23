from __future__ import annotations

import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from eqorch.cli import EqOrchApplication, main
from eqorch.domain import Action, LogEntry, Memory, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.app import ErrorCoordinator, PolicyContextStore, ResearchConcierge, RetryPolicyExecutor
from eqorch.gateways import BackendExecutionResult, BackendGateway, EngineGateway, EngineTransport, LLMGateway, ResultNormalizer
from eqorch.memory import PersistenceCommit, PersistentMemoryStore, SqliteConnectionFactory
from eqorch.orchestrator import ActionDispatcher, DecisionContextAssembler, LoopCycleResult, OrchestrationLoop
from eqorch.registry import EngineRegistry, SkillRegistry, ToolRegistry


class TerminateAdapter:
    def decide(self, payload):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '[{"type":"terminate","target":"system","parameters":{"reason":"done"},'
                            '"issued_at":"2026-03-23T00:00:00Z","action_id":"00000000-0000-4000-8000-000000000010"}]'
                        )
                    }
                }
            ]
        }


class GoogleTerminateAdapter:
    def decide(self, payload):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '[{"type":"terminate","target":"system","parameters":{"reason":"done"},'
                                    '"issued_at":"2026-03-23T00:00:00Z","action_id":"00000000-0000-4000-8000-000000000012"}]'
                                )
                            }
                        ]
                    }
                }
            ]
        }


class StartupThenTimeoutAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, payload):
        self.calls += 1
        if self.calls == 1:
            return TerminateAdapter().decide(payload)
        raise TimeoutError("provider unavailable")


class StartupThenAsyncTerminateAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, payload):
        self.calls += 1
        if self.calls == 1:
            return TerminateAdapter().decide(payload)
        if self.calls == 2:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '[{"type":"run_engine","target":"dummy_engine","parameters":{"instruction":"search","async":true},'
                                '"issued_at":"2026-03-23T00:00:00Z","action_id":"00000000-0000-4000-8000-000000000031"}]'
                            )
                        }
                    }
                ]
            }
        return TerminateAdapter().decide(payload)


class PendingTransport:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def run(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"status": "success", "payload": {"instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"job_id": "job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int):
        return {
            "status": "partial",
            "payload": {"job_id": job_id},
            "error": {"code": "PENDING_JOB", "message": "still running", "retryable": True},
        }

    def cancel(self, endpoint: str, job_id: str, timeout_sec: int):
        self.cancelled.append(job_id)
        return {"status": "success", "payload": {"job_id": job_id, "cancelled": True}}


class NullBackendRunner:
    def run(self, command, config):
        return BackendExecutionResult(status="success", numeric_results={"mse": 0.0}, error=None)


@dataclass(slots=True)
class FakeLoop:
    seen_modes: list[str]

    def run_cycle(self, state: State) -> LoopCycleResult:
        self.seen_modes.append(state.current_mode)
        action = Action(
            type="terminate",
            target="system",
            parameters={"reason": "done"},
            issued_at="2026-03-23T00:00:00Z",
            action_id="00000000-0000-4000-8000-000000000011",
        )
        return LoopCycleResult(
            state=state,
            actions=(action,),
            dispatches=(),
            should_continue=False,
        )


@dataclass(slots=True)
class FakeBundle:
    loop: FakeLoop
    persistent_store: PersistentMemoryStore | None = None

    def close(self) -> None:
        if self.persistent_store is not None:
            self.persistent_store.close()
        return None


class CliStartupTest(unittest.TestCase):
    def test_interactive_cli_starts_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_fixture_files(Path(tmpdir))
            seen_modes: list[str] = []
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: TerminateAdapter(),
                runtime_builder=lambda **_: FakeBundle(loop=FakeLoop(seen_modes)),
            )

            exit_code = main(
                [
                    "interactive",
                    "--policy",
                    str(paths["policy"]),
                    "--components",
                    str(paths["components"]),
                    "--provider",
                    "openai",
                    "--llm-adapter",
                    "fixtures:TerminateAdapter",
                    "--database-url",
                    "sqlite:///ignored.db",
                ],
                app=app,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_modes, ["interactive"])

    def test_batch_cli_starts_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_fixture_files(Path(tmpdir))
            seen_modes: list[str] = []
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: GoogleTerminateAdapter(),
                runtime_builder=lambda **_: FakeBundle(loop=FakeLoop(seen_modes)),
            )

            exit_code = main(
                [
                    "batch",
                    "--policy",
                    str(paths["policy"]),
                    "--components",
                    str(paths["components"]),
                    "--provider",
                    "google",
                    "--llm-adapter",
                    "fixtures:TerminateAdapter",
                    "--database-url",
                    "sqlite:///ignored.db",
                ],
                app=app,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_modes, ["batch"])

    def test_resume_cli_starts_from_committed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_fixture_files(root)
            db_path = root / "resume.sqlite3"
            store = PersistentMemoryStore(
                database_url=f"sqlite:///{db_path}",
                connection_factory=SqliteConnectionFactory(str(db_path)),
            )
            session_id = str(uuid4())
            state = State(
                policy_context=PolicyContext(goals=("find equation",)),
                workflow_memory=Memory(entries=[], max_entries=1000, eviction_policy="lru"),
                current_mode="batch",
                session_id=session_id,
                step=3,
            )
            store.commit(
                PersistenceCommit(
                    state_snapshot=state,
                    state_summaries={"step": 3, "mode": "batch"},
                    trace_entries=(
                        LogEntry(
                            step=3,
                            session_id=session_id,
                            action_id="00000000-0000-4000-8000-000000000013",
                            action=Action(
                                type="switch_mode",
                                target="system",
                                parameters={"target_mode": "batch", "reason": "resume"},
                                issued_at="2026-03-23T00:00:00Z",
                                action_id="00000000-0000-4000-8000-000000000013",
                            ),
                            result=Result(status="success", payload={"target_mode": "batch"}, error=None),
                            input_summary='{"current_mode":"interactive"}',
                            output_summary='{"current_mode":"batch","session_id":"' + session_id + '","step":3}',
                            state_diff=[],
                            duration_ms=0,
                            timestamp="2026-03-23T00:00:00Z",
                        ),
                    ),
                )
            )
            store.flush(timeout=5)
            seen_modes: list[str] = []
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: TerminateAdapter(),
                runtime_builder=lambda **_: FakeBundle(
                    loop=FakeLoop(seen_modes),
                    persistent_store=PersistentMemoryStore(
                        database_url=f"sqlite:///{db_path}",
                        connection_factory=SqliteConnectionFactory(str(db_path)),
                    ),
                ),
            )

            exit_code = main(
                [
                    "resume",
                    "--session-id",
                    session_id,
                    "--policy",
                    str(paths["policy"]),
                    "--components",
                    str(paths["components"]),
                    "--provider",
                    "openai",
                    "--llm-adapter",
                    "fixtures:TerminateAdapter",
                    "--database-url",
                    f"sqlite:///{db_path}",
                ],
                app=app,
            )
            store.close()

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_modes, ["batch"])

    def test_resume_cli_recovers_after_previous_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_fixture_files(root)
            db_path = root / "crash.sqlite3"
            store = PersistentMemoryStore(
                database_url=f"sqlite:///{db_path}",
                connection_factory=SqliteConnectionFactory(str(db_path)),
            )
            session_id = str(uuid4())
            state = State(
                policy_context=PolicyContext(goals=("find equation",)),
                workflow_memory=Memory(entries=[], max_entries=1000, eviction_policy="lru"),
                current_mode="interactive",
                session_id=session_id,
                step=2,
            )
            store.commit(
                PersistenceCommit(
                    state_snapshot=state,
                    state_summaries={"step": 2, "mode": "interactive"},
                )
            )
            store.flush(timeout=5)
            seen_modes: list[str] = []
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: TerminateAdapter(),
                runtime_builder=lambda **_: FakeBundle(
                    loop=FakeLoop(seen_modes),
                    persistent_store=PersistentMemoryStore(
                        database_url=f"sqlite:///{db_path}",
                        connection_factory=SqliteConnectionFactory(str(db_path)),
                    ),
                ),
            )

            exit_code = main(
                [
                    "resume",
                    "--session-id",
                    session_id,
                    "--policy",
                    str(paths["policy"]),
                    "--components",
                    str(paths["components"]),
                    "--provider",
                    "openai",
                    "--llm-adapter",
                    "fixtures:TerminateAdapter",
                    "--database-url",
                    f"sqlite:///{db_path}",
                ],
                app=app,
            )
            store.close()

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen_modes, ["interactive"])

    def test_interactive_retry_exhaustion_falls_back_to_ask_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_fixture_files(root, include_engine=False)
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: StartupThenTimeoutAdapter(),
                runtime_builder=_real_runtime_builder,
            )

            result = app.start_new_session(
                mode="interactive",
                policy_path=paths["policy"],
                components_path=paths["components"],
                provider="openai",
                llm_adapter="fixtures:TimeoutAdapter",
                database_url=f"sqlite:///{root / 'interactive.db'}",
                max_cycles=1,
            )

        self.assertTrue(result.started)
        self.assertEqual(result.cycles, 1)
        self.assertIn("00000000-0000-4000-8000-000000000001", result.state.last_errors)
        self.assertEqual(result.state.last_errors["00000000-0000-4000-8000-000000000001"].code, "USER_INPUT_REQUIRED")

    def test_batch_retry_exhaustion_falls_back_to_terminate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_fixture_files(root, include_engine=False)
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: StartupThenTimeoutAdapter(),
                runtime_builder=_real_runtime_builder,
            )

            result = app.start_new_session(
                mode="batch",
                policy_path=paths["policy"],
                components_path=paths["components"],
                provider="openai",
                llm_adapter="fixtures:TimeoutAdapter",
                database_url=f"sqlite:///{root / 'batch.db'}",
                max_cycles=1,
            )

        self.assertTrue(result.started)
        self.assertEqual(result.cycles, 1)
        self.assertIn("00000000-0000-4000-8000-000000000002", result.state.last_errors)
        self.assertEqual(result.state.last_errors["00000000-0000-4000-8000-000000000002"].code, "TIMEOUT")

    def test_terminate_with_pending_job_cancels_job_in_end_to_end_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_fixture_files(root, include_engine=True)
            transport = PendingTransport()
            app = EqOrchApplication(
                adapter_resolver=lambda provider, spec: StartupThenAsyncTerminateAdapter(),
                runtime_builder=lambda **kwargs: _real_runtime_builder(engine_transport=transport, **kwargs),
            )

            result = app.start_new_session(
                mode="interactive",
                policy_path=paths["policy"],
                components_path=paths["components"],
                provider="openai",
                llm_adapter="fixtures:AsyncTerminateAdapter",
                database_url=f"sqlite:///{root / 'pending.db'}",
                max_cycles=2,
            )

        self.assertTrue(result.started)
        self.assertEqual(result.cycles, 2)
        self.assertEqual(transport.cancelled, ["job-1"])
        cancelled = [entry for entry in result.state.workflow_memory.entries if entry.key.startswith("cancelled_jobs:")]
        self.assertEqual(len(cancelled), 1)


def _write_fixture_files(root: Path, *, include_engine: bool = False) -> dict[str, Path]:
    package_root = root / "fixtures"
    package_root.mkdir()
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "skill_impl.py").write_text(
        textwrap.dedent(
            """
            from eqorch.domain import Result

            class DummySkill:
                def execute(self, request):
                    return Result(status="success", payload={"ok": True}, error=None)
            """
        ).strip(),
        encoding="utf-8",
    )
    (package_root / "tool_impl.py").write_text(
        textwrap.dedent(
            """
            from eqorch.domain import Result

            class DummyTool:
                def execute(self, request):
                    return Result(status="success", payload={"ok": True}, error=None)
            """
        ).strip(),
        encoding="utf-8",
    )
    policy_path = root / "policy.yaml"
    policy_path.write_text("goals:\n  - find equation\n", encoding="utf-8")
    components_path = root / "components.yaml"
    parts = [
        textwrap.dedent(
            """
            skills:
              - name: dummy_skill
                module: fixtures.skill_impl
                class: DummySkill
            tools:
              - name: dummy_tool
                module: fixtures.tool_impl
                class: DummyTool
            """
        ).strip()
    ]
    if include_engine:
        parts.append(
            textwrap.dedent(
                """
                engines:
                  - name: dummy_engine
                    endpoint: http://localhost:8080/engine
                    protocol: rest
                """
            ).strip()
        )
    else:
        parts.append("engines: []")
    parts.append("backends: []")
    components_path.write_text("\n".join(parts), encoding="utf-8")
    import sys

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return {"policy": policy_path, "components": components_path}


def _real_runtime_builder(*, provider, adapter, database_url, components, policy_store, engine_transport=None, **_):
    skill_registry = SkillRegistry()
    skill_registry.register_from_config(components.skills)
    tool_registry = ToolRegistry()
    tool_registry.register_from_config(components.tools)
    engine_registry = EngineRegistry()
    engine_registry.register_from_config(components.engines)
    transport = engine_transport or PendingTransport()
    engine_gateway = EngineGateway(engine_registry, transports={"rest": transport, "grpc": transport})
    backend_gateway = BackendGateway(
        components.backends,
        runners={backend.name: NullBackendRunner() for backend in components.backends},
        normalizer=ResultNormalizer(),
    )
    error_coordinator = ErrorCoordinator()
    trace_recorder = __import__("eqorch.tracing", fromlist=["TraceRecorder"]).TraceRecorder()
    database_path = database_url.removeprefix("sqlite:///")
    persistent_store = PersistentMemoryStore(
        database_url=database_url,
        connection_factory=SqliteConnectionFactory(database_path),
    )
    dispatcher = ActionDispatcher(
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        engine_gateway=engine_gateway,
        backend_gateway=backend_gateway,
        policy_store=policy_store,
        error_coordinator=error_coordinator,
        trace_recorder=trace_recorder,
    )
    concierge = ResearchConcierge(
        gateway=LLMGateway(provider=provider, adapter=adapter),
        error_coordinator=error_coordinator,
        retry_executor=RetryPolicyExecutor(),
    )
    loop = OrchestrationLoop(
        context_assembler=DecisionContextAssembler(),
        concierge=concierge,
        dispatcher=dispatcher,
        trace_recorder=trace_recorder,
        persistent_store=persistent_store,
        error_coordinator=error_coordinator,
    )
    return FakeBundle(loop=loop, persistent_store=persistent_store)


if __name__ == "__main__":
    unittest.main()
