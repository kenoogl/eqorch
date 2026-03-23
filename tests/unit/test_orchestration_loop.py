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
from eqorch.registry import ComponentConfigLoader, EngineRegistry, SkillRegistry, ToolRegistry
from eqorch.tracing import TraceRecorder


def ts() -> str:
    return "2026-03-23T00:00:00Z"


class FakeEngineTransport:
    def run(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"status": "success", "payload": {"instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"job_id": "job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int):
        return {"status": "success", "payload": {"job_id": job_id}}


class JsonActionAdapter:
    def __init__(self, actions: list[dict[str, object]]):
        self._payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(actions),
                    }
                }
            ]
        }

    def decide(self, payload):
        return self._payload


class OrchestrationLoopTest(unittest.TestCase):
    def _state(self) -> State:
        return State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )

    def _build_loop(self, *, actions: list[dict[str, object]]):
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
        dispatcher = ActionDispatcher(
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            engine_gateway=EngineGateway(
                registry=engine_registry,
                transports={"rest": FakeEngineTransport()},
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
        return loop, store

    def test_runs_basic_cycle_and_updates_state(self) -> None:
        loop, store = self._build_loop(
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
        loop, store = self._build_loop(
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


if __name__ == "__main__":
    unittest.main()
