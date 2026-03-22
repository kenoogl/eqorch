from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from eqorch.registry import ComponentConfigError, ComponentConfigLoader


class ComponentConfigLoaderTest(unittest.TestCase):
    def test_loads_components_yaml(self) -> None:
        content = textwrap.dedent(
            """
            skills:
              - name: physics_constraint_checker
                module: eqorch.skills.physics
                class: PhysicsConstraintChecker
            tools:
              - name: arxiv_search
                module: eqorch.tools.arxiv
                class: ArxivSearchTool
            engines:
              - name: symbolic_regression
                endpoint: http://localhost:8080/engine
                protocol: rest
              - name: grpc_regression
                endpoint: dns:///engine
                protocol: grpc
                proto: path/to/engine.proto
                service: EngineService
            backends:
              - name: julia_runner
                executable: julia
                args: ["--project", "run.jl"]
                env:
                  JULIA_NUM_THREADS: "4"
            """
        ).strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "components.yaml"
            path.write_text(content, encoding="utf-8")
            config = ComponentConfigLoader().load_file(path)

        self.assertEqual(config.skills[0].name, "physics_constraint_checker")
        self.assertEqual(config.tools[0].class_name, "ArxivSearchTool")
        self.assertEqual(config.engines[1].protocol, "grpc")
        self.assertEqual(config.backends[0].env["JULIA_NUM_THREADS"], "4")

    def test_rejects_invalid_rest_or_grpc_contract(self) -> None:
        content = textwrap.dedent(
            """
            engines:
              - name: broken_grpc
                endpoint: dns:///engine
                protocol: grpc
            """
        ).strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "components.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ComponentConfigError, "grpc engines require proto"):
                ComponentConfigLoader().load_file(path)

    def test_rejects_duplicate_component_names(self) -> None:
        content = textwrap.dedent(
            """
            skills:
              - name: duplicated
                module: eqorch.skills.one
                class: A
              - name: duplicated
                module: eqorch.skills.two
                class: B
            """
        ).strip()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "components.yaml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ComponentConfigError, "duplicated name"):
                ComponentConfigLoader().load_file(path)


if __name__ == "__main__":
    unittest.main()
