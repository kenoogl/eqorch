from __future__ import annotations

import unittest

from eqorch.app import LayerBoundaryRules, PerformanceBudget, PerformanceSample, PerformanceScenario


class PerformanceBudgetTest(unittest.TestCase):
    def test_benchmark_uses_warmup_and_computes_p99_and_cpu(self) -> None:
        budget = PerformanceBudget()
        counter = {"value": 0}

        def sampler():
            counter["value"] += 1
            index = counter["value"]
            if index <= 100:
                return PerformanceSample(
                    cycle_wall_ms=1.0,
                    cpu_process_ms=0.2,
                    postgres_write_ms=0.1,
                    parallel_actions=1,
                )
            return PerformanceSample(
                cycle_wall_ms=10.0 + (index % 7),
                cpu_process_ms=2.5,
                postgres_write_ms=1.0 + (index % 3),
                vector_write_ms=0.5,
                object_transfer_ms=0.25,
                parallel_actions=4,
            )

        report = budget.benchmark(sampler, scenario=PerformanceScenario(iterations=1000, warmup=100))

        self.assertEqual(report.measured_iterations, 900)
        self.assertGreaterEqual(report.p99_cycle_ms, 16.0)
        self.assertGreater(report.avg_cpu_percent, 0.0)
        self.assertEqual(report.max_parallel_actions, 4)
        self.assertGreater(report.postgres_write_p99_ms, 0.0)
        self.assertGreater(report.vector_write_p99_ms, 0.0)
        self.assertGreater(report.object_transfer_p99_ms, 0.0)

    def test_benchmark_accepts_mapping_samples(self) -> None:
        budget = PerformanceBudget()
        report = budget.benchmark(
            lambda: {
                "cycle_wall_ms": 8.0,
                "cpu_process_ms": 1.0,
                "postgres_write_ms": 0.5,
                "parallel_actions": 2,
            },
            scenario=PerformanceScenario(iterations=10, warmup=2),
        )

        self.assertEqual(report.measured_iterations, 8)
        self.assertEqual(report.max_parallel_actions, 2)
        self.assertEqual(report.postgres_write_p99_ms, 0.5)


class LayerBoundaryRulesTest(unittest.TestCase):
    def test_reports_new_registry_entries_without_core_touch(self) -> None:
        rules = LayerBoundaryRules()

        report = rules.verify_registry_extensions(
            before_skill_names=("skill_a",),
            after_skill_names=("skill_a", "skill_b"),
            before_tool_names=("tool_a",),
            after_tool_names=("tool_a", "tool_b"),
            before_engine_names=("engine_a",),
            after_engine_names=("engine_a", "engine_b"),
            touched_core_modules=("eqorch.registry.skill_tool",),
        )

        self.assertEqual(report.new_skill_names, ("skill_b",))
        self.assertEqual(report.new_tool_names, ("tool_b",))
        self.assertEqual(report.new_engine_names, ("engine_b",))
        self.assertTrue(report.unchanged_core_modules)

    def test_detects_forbidden_core_touch_and_parallel_limit(self) -> None:
        rules = LayerBoundaryRules()

        report = rules.verify_registry_extensions(
            before_skill_names=(),
            after_skill_names=("skill_a",),
            before_tool_names=(),
            after_tool_names=(),
            before_engine_names=(),
            after_engine_names=(),
            touched_core_modules=("eqorch.orchestrator.loop",),
        )

        self.assertFalse(report.unchanged_core_modules)
        self.assertTrue(rules.validate_parallel_limit(requested_actions=8, max_parallel_actions=8))
        self.assertFalse(rules.validate_parallel_limit(requested_actions=9, max_parallel_actions=8))


if __name__ == "__main__":
    unittest.main()
