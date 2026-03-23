from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.app import ErrorCoordinator, PolicyContextStore
from eqorch.app.research_concierge import ResearchConcierge
from eqorch.domain import Memory, State
from eqorch.domain.policy import PolicyContext
from eqorch.gateways import BackendGateway, EngineGateway, LLMGateway
from eqorch.memory import PersistentMemoryStore, SqliteConnectionFactory
from eqorch.orchestrator import ActionDispatcher, DecisionContextAssembler, OrchestrationLoop
from eqorch.orchestrator.action_dispatcher import DispatchRecord
from eqorch.registry import ComponentConfigLoader, EngineRegistry, SkillRegistry, ToolRegistry
from eqorch.tracing import TraceRecorder


def ts() -> str:
    return "2026-03-23T00:00:00Z"


class FakeEngineTransport:
    def __init__(self) -> None:
        self._poll_results: list[dict[str, object]] = []
        self.cancelled_job_ids: list[str] = []

    def run(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"status": "success", "payload": {"instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"job_id": "job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int):
        if self._poll_results:
            return self._poll_results.pop(0)
        return {"status": "success", "payload": {"job_id": job_id}}

    def queue_poll_result(self, payload: dict[str, object]) -> None:
        self._poll_results.append(payload)

    def cancel(self, endpoint: str, job_id: str, timeout_sec: int):
        self.cancelled_job_ids.append(job_id)
        return {"status": "success", "payload": {"job_id": job_id, "cancelled": True}}


class JsonActionAdapter:
    def __init__(self, actions: list[list[dict[str, object]]] | list[dict[str, object]]):
        if actions and isinstance(actions[0], dict):  # type: ignore[index]
            actions = [actions]  # type: ignore[assignment]
        self._payloads = [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(batch),
                        }
                    }
                ]
            }
            for batch in actions  # type: ignore[arg-type]
        ]

    def decide(self, payload):
        if len(self._payloads) == 1:
            return self._payloads[0]
        return self._payloads.pop(0)


class OrchestrationLoopTest(unittest.TestCase):
    def _state(self) -> State:
        return State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )

    def _build_loop(self, *, actions: list[list[dict[str, object]]] | list[dict[str, object]]):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        package = root / "loop_plugins"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "skills.py").write_text(
            textwrap.dedent(
                """
                from eqorch.domain import Result

                class ExampleSkill:
                    def execute(self, request):
                        return Result(status="success", payload={"input": request.input}, error=None)
                """
            ),
            encoding="utf-8",
        )
        (package / "tools.py").write_text(
            textwrap.dedent(
                """
                from eqorch.domain import Result

                class ExampleTool:
                    def execute(self, request):
                        return Result(status="success", payload={"query": request.query}, error=None)
                """
            ),
            encoding="utf-8",
        )
        config_path = root / "components.yaml"
        config_path.write_text(
            textwrap.dedent(
                """
                skills:
                  - name: example_skill
                    module: loop_plugins.skills
                    class: ExampleSkill
                tools:
                  - name: example_tool
                    module: loop_plugins.tools
                    class: ExampleTool
                engines:
                  - name: symbolic_regression
                    endpoint: http://localhost:8080/engine
                    protocol: rest
                """
            ).strip(),
            encoding="utf-8",
        )

        import sys

        sys.path.insert(0, tempdir.name)
        self.addCleanup(lambda: sys.path.remove(tempdir.name))

        config = ComponentConfigLoader().load_file(config_path)
        skill_registry = SkillRegistry()
        tool_registry = ToolRegistry()
        engine_registry = EngineRegistry()
        skill_registry.register_from_config(config.skills)
        tool_registry.register_from_config(config.tools)
        engine_registry.register_from_config(config.engines)
        trace_recorder = TraceRecorder()
        transport = FakeEngineTransport()
        dispatcher = ActionDispatcher(
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            engine_gateway=EngineGateway(
                registry=engine_registry,
                transports={"rest": transport},
            ),
            backend_gateway=BackendGateway(backends=(), runners={}),
            policy_store=PolicyContextStore(initial_policy=PolicyContext(goals=("goal",))),
            error_coordinator=ErrorCoordinator(),
            trace_recorder=trace_recorder,
        )
        database_path = str(root / "memory.db")
        store = PersistentMemoryStore(database_path, connection_factory=SqliteConnectionFactory(database_path))
        self.addCleanup(store.close)
        concierge = ResearchConcierge(gateway=LLMGateway(provider="openai", adapter=JsonActionAdapter(actions)))
        loop = OrchestrationLoop(
            context_assembler=DecisionContextAssembler(),
            concierge=concierge,
            dispatcher=dispatcher,
            trace_recorder=trace_recorder,
            persistent_store=store,
            error_coordinator=ErrorCoordinator(),
        )
        return loop, store, transport

    def _build_faulty_loop(self):
        loop, store, _ = self._build_loop(
            actions=[
                {
                    "type": "switch_mode",
                    "target": "system",
                    "parameters": {"target_mode": "batch", "reason": "scheduled"},
                }
            ]
        )

        class FaultyDispatcher:
            def _validate_batch(self, actions):
                return None

            def dispatch(self, actions, state):
                state.current_mode = "batch"
                raise RuntimeError("state apply failed")

            def list_pending_jobs(self):
                return ()

            def poll_pending_job(self, job_id, timeout_sec=3600):
                raise AssertionError("not used")

            def cancel_pending_job(self, job_id, timeout_sec=3600):
                raise AssertionError("not used")

        loop._dispatcher = FaultyDispatcher()  # type: ignore[assignment, attr-defined]
        return loop, store

    def test_runs_basic_cycle_and_updates_state(self) -> None:
        loop, store, _ = self._build_loop(
            actions=[
                {
                    "type": "switch_mode",
                    "target": "system",
                    "parameters": {"target_mode": "batch", "reason": "scheduled"},
                }
            ]
        )
        state = self._state()

        result = loop.run_cycle(state, issued_at=ts())

        self.assertTrue(result.should_continue)
        self.assertEqual(result.state.step, 1)
        self.assertEqual(result.state.current_mode, "batch")
        self.assertTrue(store.flush(timeout=2))
        restored = store.load_latest(state.session_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 1)
        self.assertEqual(restored.current_mode, "batch")

    def test_terminate_action_exits_normally(self) -> None:
        loop, store, _ = self._build_loop(
            actions=[
                {
                    "type": "terminate",
                    "target": "system",
                    "parameters": {"reason": "done"},
                }
            ]
        )
        state = self._state()

        result = loop.run_cycle(state, issued_at=ts())

        self.assertFalse(result.should_continue)
        self.assertEqual(result.actions[0].type, "terminate")
        self.assertTrue(store.flush(timeout=2))
        entries = store.trace_store.load_entries(state.session_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action.type, "terminate")

    def test_registers_async_job_and_polls_completion(self) -> None:
        loop, store, transport = self._build_loop(
            actions=[
                [
                    {
                        "type": "run_engine",
                        "target": "symbolic_regression",
                        "parameters": {"instruction": "search", "async": True},
                    }
                ],
                [
                    {
                        "type": "switch_mode",
                        "target": "system",
                        "parameters": {"target_mode": "batch", "reason": "polled"},
                    }
                ],
            ]
        )
        state = self._state()
        first = loop.run_cycle(state, issued_at=ts())
        transport.queue_poll_result({"status": "success", "payload": {"job_id": "job-1", "score": 0.1}})

        second = loop.run_cycle(first.state, issued_at=ts())

        self.assertEqual(len(first.state.pending_jobs), 1)
        self.assertEqual(first.state.pending_jobs[0].job_id, "job-1")
        self.assertEqual(second.state.pending_jobs, [])
        keys = [entry.key for entry in second.state.workflow_memory.entries]
        self.assertIn("pending_job:job-1", keys)
        self.assertEqual(second.state.current_mode, "batch")
        self.assertTrue(store.flush(timeout=2))

    def test_partial_poll_keeps_pending_job(self) -> None:
        loop, _, transport = self._build_loop(
            actions=[
                [
                    {
                        "type": "run_engine",
                        "target": "symbolic_regression",
                        "parameters": {"instruction": "search", "async": True},
                    }
                ],
                [
                    {
                        "type": "switch_mode",
                        "target": "system",
                        "parameters": {"target_mode": "interactive", "reason": "still waiting"},
                    }
                ],
            ]
        )
        state = self._state()
        first = loop.run_cycle(state, issued_at=ts())
        transport.queue_poll_result(
            {
                "status": "partial",
                "payload": {"job_id": "job-1"},
                "error": {"code": "PENDING_JOB", "message": "still running", "retryable": True},
            }
        )

        second = loop.run_cycle(first.state, issued_at=ts())

        self.assertEqual(len(second.state.pending_jobs), 1)
        self.assertEqual(second.state.pending_jobs[0].job_id, "job-1")

    def test_terminate_cancels_pending_jobs_and_persists_final_state(self) -> None:
        loop, store, transport = self._build_loop(
            actions=[
                [
                    {
                        "type": "run_engine",
                        "target": "symbolic_regression",
                        "parameters": {"instruction": "search", "async": True},
                    }
                ],
                [
                    {
                        "type": "terminate",
                        "target": "system",
                        "parameters": {"reason": "stop"},
                    }
                ],
            ]
        )
        state = self._state()
        first = loop.run_cycle(state, issued_at=ts())
        transport.queue_poll_result(
            {
                "status": "partial",
                "payload": {"job_id": "job-1"},
                "error": {"code": "PENDING_JOB", "message": "still running", "retryable": True},
            }
        )

        second = loop.run_cycle(first.state, issued_at=ts())

        self.assertFalse(second.should_continue)
        self.assertEqual(transport.cancelled_job_ids, ["job-1"])
        self.assertEqual(second.state.pending_jobs, [])
        cancel_keys = [entry.key for entry in second.state.workflow_memory.entries]
        self.assertIn("cancelled_jobs:2", cancel_keys)
        self.assertTrue(store.flush(timeout=2))
        restored = store.load_latest(state.session_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.step, 2)
        self.assertEqual(restored.pending_jobs, [])

    def test_rolls_back_partial_apply_failure_and_records_last_error(self) -> None:
        loop, store = self._build_faulty_loop()
        state = self._state()

        result = loop.run_cycle(state, issued_at=ts())

        self.assertTrue(result.should_continue)
        self.assertEqual(result.state.current_mode, "interactive")
        self.assertEqual(result.state.step, 1)
        self.assertEqual(len(result.state.last_errors), 1)
        error = next(iter(result.state.last_errors.values()))
        self.assertEqual(error.code, "STATE_APPLY_FAILED")
        self.assertTrue(store.flush(timeout=2))
        restored = store.load_latest(state.session_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.current_mode, "interactive")


if __name__ == "__main__":
    unittest.main()
