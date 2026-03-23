"""Performance and extensibility verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from time import perf_counter, process_time
from typing import Any, Callable, Mapping, Sequence


@dataclass(slots=True, frozen=True)
class PerformanceSample:
    cycle_wall_ms: float
    cpu_process_ms: float
    postgres_write_ms: float
    vector_write_ms: float = 0.0
    object_transfer_ms: float = 0.0
    parallel_actions: int = 1


@dataclass(slots=True, frozen=True)
class PerformanceScenario:
    iterations: int = 1000
    warmup: int = 100
    candidate_count: int = 1000
    equation_length: int = 256
    metric_count: int = 3

    def __post_init__(self) -> None:
        if self.iterations <= 0:
            raise ValueError("iterations must be > 0")
        if self.warmup < 0 or self.warmup >= self.iterations:
            raise ValueError("warmup must be >= 0 and < iterations")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be > 0")
        if self.equation_length <= 0:
            raise ValueError("equation_length must be > 0")
        if self.metric_count <= 0:
            raise ValueError("metric_count must be > 0")


@dataclass(slots=True, frozen=True)
class PerformanceReport:
    iterations: int
    warmup: int
    measured_iterations: int
    p99_cycle_ms: float
    avg_cpu_percent: float
    max_parallel_actions: int
    postgres_write_p99_ms: float
    vector_write_p99_ms: float
    object_transfer_p99_ms: float


class PerformanceBudget:
    """Measures repeated cycle performance under a fixed scenario."""

    def benchmark(
        self,
        sampler: Callable[[], PerformanceSample | Mapping[str, Any]],
        *,
        scenario: PerformanceScenario | None = None,
    ) -> PerformanceReport:
        scenario = scenario or PerformanceScenario()
        samples: list[PerformanceSample] = []
        for _ in range(scenario.iterations):
            started = perf_counter()
            cpu_started = process_time()
            sample = sampler()
            cpu_elapsed_ms = (process_time() - cpu_started) * 1000.0
            wall_elapsed_ms = (perf_counter() - started) * 1000.0
            normalized = self._normalize_sample(sample, wall_elapsed_ms=wall_elapsed_ms, cpu_elapsed_ms=cpu_elapsed_ms)
            samples.append(normalized)

        measured = samples[scenario.warmup :]
        cycle_values = [sample.cycle_wall_ms for sample in measured]
        cpu_values = [sample.cpu_process_ms for sample in measured]
        postgres_values = [sample.postgres_write_ms for sample in measured]
        vector_values = [sample.vector_write_ms for sample in measured]
        object_values = [sample.object_transfer_ms for sample in measured]
        parallel_values = [sample.parallel_actions for sample in measured]

        cpu_percent = 0.0
        total_wall = sum(cycle_values)
        if total_wall > 0:
            cpu_percent = min(100.0, (sum(cpu_values) / total_wall) * 100.0)

        return PerformanceReport(
            iterations=scenario.iterations,
            warmup=scenario.warmup,
            measured_iterations=len(measured),
            p99_cycle_ms=_percentile(cycle_values, 0.99),
            avg_cpu_percent=cpu_percent,
            max_parallel_actions=max(parallel_values, default=0),
            postgres_write_p99_ms=_percentile(postgres_values, 0.99),
            vector_write_p99_ms=_percentile(vector_values, 0.99),
            object_transfer_p99_ms=_percentile(object_values, 0.99),
        )

    def _normalize_sample(
        self,
        sample: PerformanceSample | Mapping[str, Any],
        *,
        wall_elapsed_ms: float,
        cpu_elapsed_ms: float,
    ) -> PerformanceSample:
        if isinstance(sample, PerformanceSample):
            return PerformanceSample(
                cycle_wall_ms=sample.cycle_wall_ms or wall_elapsed_ms,
                cpu_process_ms=sample.cpu_process_ms or cpu_elapsed_ms,
                postgres_write_ms=sample.postgres_write_ms,
                vector_write_ms=sample.vector_write_ms,
                object_transfer_ms=sample.object_transfer_ms,
                parallel_actions=sample.parallel_actions,
            )
        return PerformanceSample(
            cycle_wall_ms=float(sample.get("cycle_wall_ms", wall_elapsed_ms)),
            cpu_process_ms=float(sample.get("cpu_process_ms", cpu_elapsed_ms)),
            postgres_write_ms=float(sample.get("postgres_write_ms", 0.0)),
            vector_write_ms=float(sample.get("vector_write_ms", 0.0)),
            object_transfer_ms=float(sample.get("object_transfer_ms", 0.0)),
            parallel_actions=int(sample.get("parallel_actions", 1)),
        )


@dataclass(slots=True, frozen=True)
class ExtensionBoundaryReport:
    new_skill_names: tuple[str, ...]
    new_tool_names: tuple[str, ...]
    new_engine_names: tuple[str, ...]
    unchanged_core_modules: bool


class LayerBoundaryRules:
    """Checks that extensibility goes through registries and policy limits."""

    def verify_registry_extensions(
        self,
        *,
        before_skill_names: Sequence[str],
        after_skill_names: Sequence[str],
        before_tool_names: Sequence[str],
        after_tool_names: Sequence[str],
        before_engine_names: Sequence[str],
        after_engine_names: Sequence[str],
        touched_core_modules: Sequence[str] = (),
    ) -> ExtensionBoundaryReport:
        forbidden_touches = {
            "eqorch.orchestrator.loop",
            "eqorch.orchestrator.action_dispatcher",
            "eqorch.app.research_concierge",
        }
        return ExtensionBoundaryReport(
            new_skill_names=_new_names(before_skill_names, after_skill_names),
            new_tool_names=_new_names(before_tool_names, after_tool_names),
            new_engine_names=_new_names(before_engine_names, after_engine_names),
            unchanged_core_modules=not any(module in forbidden_touches for module in touched_core_modules),
        )

    def validate_parallel_limit(self, *, requested_actions: int, max_parallel_actions: int) -> bool:
        if max_parallel_actions <= 0:
            raise ValueError("max_parallel_actions must be > 0")
        return requested_actions <= max_parallel_actions


def _new_names(before: Sequence[str], after: Sequence[str]) -> tuple[str, ...]:
    before_set = set(before)
    return tuple(sorted(name for name in after if name not in before_set))


def _percentile(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * ratio) - 1))
    return ordered[index]


__all__ = [
    "ExtensionBoundaryReport",
    "LayerBoundaryRules",
    "PerformanceBudget",
    "PerformanceReport",
    "PerformanceSample",
    "PerformanceScenario",
]
