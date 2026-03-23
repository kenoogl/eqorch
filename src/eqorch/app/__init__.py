"""Application services for EqOrch."""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "CoordinatedError",
    "DecisionSupportAdapter",
    "ErrorCoordinator",
    "ExtensionBoundaryReport",
    "LayerBoundaryRules",
    "PerformanceBudget",
    "PerformanceReport",
    "PerformanceSample",
    "PerformanceScenario",
    "PolicyContextStore",
    "PolicyLoadError",
    "PolicyRevision",
    "ResearchConcierge",
    "RetryDecision",
    "RetryPolicyExecutor",
    "RuntimeCheckResult",
    "RuntimeEnvironmentChecks",
]


_EXPORTS = {
    "CoordinatedError": ("eqorch.app.error_coordinator", "CoordinatedError"),
    "ErrorCoordinator": ("eqorch.app.error_coordinator", "ErrorCoordinator"),
    "ExtensionBoundaryReport": ("eqorch.app.performance_budget", "ExtensionBoundaryReport"),
    "LayerBoundaryRules": ("eqorch.app.performance_budget", "LayerBoundaryRules"),
    "PerformanceBudget": ("eqorch.app.performance_budget", "PerformanceBudget"),
    "PerformanceReport": ("eqorch.app.performance_budget", "PerformanceReport"),
    "PerformanceSample": ("eqorch.app.performance_budget", "PerformanceSample"),
    "PerformanceScenario": ("eqorch.app.performance_budget", "PerformanceScenario"),
    "PolicyContextStore": ("eqorch.app.policy_store", "PolicyContextStore"),
    "PolicyLoadError": ("eqorch.app.policy_store", "PolicyLoadError"),
    "PolicyRevision": ("eqorch.app.policy_store", "PolicyRevision"),
    "DecisionSupportAdapter": ("eqorch.app.research_concierge", "DecisionSupportAdapter"),
    "ResearchConcierge": ("eqorch.app.research_concierge", "ResearchConcierge"),
    "RetryDecision": ("eqorch.app.retry_policy", "RetryDecision"),
    "RetryPolicyExecutor": ("eqorch.app.retry_policy", "RetryPolicyExecutor"),
    "RuntimeCheckResult": ("eqorch.app.runtime_checks", "RuntimeCheckResult"),
    "RuntimeEnvironmentChecks": ("eqorch.app.runtime_checks", "RuntimeEnvironmentChecks"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
