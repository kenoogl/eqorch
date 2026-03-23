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
from eqorch.memory import PersistenceCommit, PersistentMemoryStore, SqliteConnectionFactory
from eqorch.orchestrator import LoopCycleResult


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


def _write_fixture_files(root: Path) -> dict[str, Path]:
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
    components_path.write_text(
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
            engines: []
            backends: []
            """
        ).strip(),
        encoding="utf-8",
    )
    import sys

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return {"policy": policy_path, "components": components_path}


if __name__ == "__main__":
    unittest.main()
