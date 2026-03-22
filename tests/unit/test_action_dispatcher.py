from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.app import ErrorCoordinator, PolicyContextStore
from eqorch.domain import Action, Memory, State
from eqorch.domain.policy import PolicyContext
from eqorch.gateways import BackendGateway, EngineGateway
from eqorch.orchestrator.action_dispatcher import ActionDispatcher
from eqorch.registry import ComponentConfigLoader, EngineRegistry, SkillRegistry, ToolRegistry
from eqorch.tracing import TraceRecorder


def ts() -> str:
    return "2026-03-22T00:00:00Z"


class FakeEngineTransport:
    def run(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"status": "success", "payload": {"instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int):
        return {"job_id": "job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int):
        return {"status": "success", "payload": {"job_id": job_id}}


class DispatcherTest(unittest.TestCase):
    def _state(self) -> State:
        return State(
            policy_context=PolicyContext(goals=("goal",)),
            workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
            session_id=str(uuid4()),
        )

    def _dispatcher(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "dispatch_plugins"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "skills.py").write_text(
                textwrap.dedent(
                    """
                    from eqorch.domain import Result

                    class ExampleSkill:
                        def execute(self, state):
                            return Result(status="success", payload={"step": state.step}, error=None)
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
                        module: dispatch_plugins.skills
                        class: ExampleSkill
                    tools:
                      - name: example_tool
                        module: dispatch_plugins.tools
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

            sys.path.insert(0, tmpdir)
            try:
                config = ComponentConfigLoader().load_file(config_path)
                skill_registry = SkillRegistry()
                tool_registry = ToolRegistry()
                engine_registry = EngineRegistry()
                skill_registry.register_from_config(config.skills)
                tool_registry.register_from_config(config.tools)
                engine_registry.register_from_config(config.engines)
                return ActionDispatcher(
                    skill_registry=skill_registry,
                    tool_registry=tool_registry,
                    engine_gateway=EngineGateway(
                        registry=engine_registry,
                        transports={"rest": FakeEngineTransport()},
                    ),
                    backend_gateway=BackendGateway(backends=(), runners={}),
                    policy_store=PolicyContextStore(initial_policy=PolicyContext(goals=("goal",))),
                    error_coordinator=ErrorCoordinator(),
                    trace_recorder=TraceRecorder(),
                )
            finally:
                sys.path.remove(tmpdir)

    def test_validates_singleton_constraints(self) -> None:
        dispatcher = self._dispatcher()
        state = self._state()
        actions = [
            Action(type="terminate", target="system", parameters={}, issued_at=ts(), action_id=str(uuid4())),
            Action(type="call_tool", target="example_tool", parameters={"query": "q"}, issued_at=ts(), action_id=str(uuid4())),
        ]

        with self.assertRaisesRegex(ValueError, "must run alone"):
            dispatcher.dispatch(actions, state)

    def test_rejects_unknown_parameters(self) -> None:
        dispatcher = self._dispatcher()
        state = self._state()
        actions = [
            Action(
                type="call_tool",
                target="example_tool",
                parameters={"query": "q", "bogus": True},
                issued_at=ts(),
                action_id=str(uuid4()),
            )
        ]

        with self.assertRaisesRegex(ValueError, "unknown parameters"):
            dispatcher.dispatch(actions, state)

    def test_updates_mode_and_stages_policy_update(self) -> None:
        dispatcher = self._dispatcher()
        state = self._state()
        actions = [
            Action(
                type="switch_mode",
                target="system",
                parameters={"target_mode": "batch", "reason": "scheduled"},
                issued_at=ts(),
                action_id=str(uuid4()),
            ),
            Action(
                type="update_policy",
                target="policy",
                parameters={"patch": {"max_candidates": 5}},
                issued_at=ts(),
                action_id=str(uuid4()),
            ),
        ]

        records = dispatcher.dispatch([actions[0]], state)
        self.assertEqual(records[0].result.payload["target_mode"], "batch")
        self.assertEqual(state.current_mode, "batch")

        update_records = dispatcher.dispatch([actions[1]], state)
        self.assertEqual(update_records[0].result.payload["policy_update"], "staged")


if __name__ == "__main__":
    unittest.main()
