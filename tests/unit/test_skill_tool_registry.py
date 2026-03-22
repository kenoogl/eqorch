from __future__ import annotations

import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from uuid import uuid4

from eqorch.domain import Memory, Request, Result, State
from eqorch.domain.policy import PolicyContext
from eqorch.registry import ComponentConfigLoader, SkillRegistry, ToolRegistry


def _state() -> State:
    return State(
        policy_context=PolicyContext(goals=("goal",)),
        workflow_memory=Memory(entries=[], max_entries=10, eviction_policy="fifo"),
        session_id=str(uuid4()),
    )


class SkillToolRegistryTest(unittest.TestCase):
    def test_registers_components_from_config_and_executes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "dummy_plugins"
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
                        module: dummy_plugins.skills
                        class: ExampleSkill
                    tools:
                      - name: example_tool
                        module: dummy_plugins.tools
                        class: ExampleTool
                    """
                ).strip(),
                encoding="utf-8",
            )

            sys.path.insert(0, tmpdir)
            try:
                config = ComponentConfigLoader().load_file(config_path)
                skill_registry = SkillRegistry()
                tool_registry = ToolRegistry()
                skill_registry.register_from_config(config.skills)
                tool_registry.register_from_config(config.tools)

                skill_result = skill_registry.execute("example_skill", _state())
                tool_result = tool_registry.execute("example_tool", Request(query="find papers"))
            finally:
                sys.path.remove(tmpdir)

        self.assertEqual(skill_result.status, "success")
        self.assertEqual(skill_result.payload["step"], 0)
        self.assertEqual(tool_result.status, "success")
        self.assertEqual(tool_result.payload["query"], "find papers")

    def test_returns_not_found_error(self) -> None:
        skill_registry = SkillRegistry()
        tool_registry = ToolRegistry()

        skill_result = skill_registry.execute("missing", _state())
        tool_result = tool_registry.execute("missing", Request(query="q"))

        self.assertEqual(skill_result.error.code, "SKILL_NOT_FOUND")
        self.assertEqual(tool_result.error.code, "TOOL_NOT_FOUND")

    def test_tool_timeout_returns_timeout_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "dummy_timeout"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "tools.py").write_text(
                textwrap.dedent(
                    """
                    import time
                    from eqorch.domain import Result

                    class SlowTool:
                        def execute(self, request):
                            time.sleep(1.05)
                            return Result(status="success", payload={"ok": True}, error=None)
                    """
                ),
                encoding="utf-8",
            )
            config_path = root / "components.yaml"
            config_path.write_text(
                textwrap.dedent(
                    """
                    tools:
                      - name: slow_tool
                        module: dummy_timeout.tools
                        class: SlowTool
                    """
                ).strip(),
                encoding="utf-8",
            )

            sys.path.insert(0, tmpdir)
            try:
                config = ComponentConfigLoader().load_file(config_path)
                registry = ToolRegistry()
                registry.register_from_config(config.tools)
                result = registry.execute("slow_tool", Request(query="q", timeout_sec=1))
            finally:
                sys.path.remove(tmpdir)

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
