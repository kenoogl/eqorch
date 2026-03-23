"""Startup validation for policy, components, and LLM connectivity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import uuid4

from eqorch.domain import Memory, PolicyContext, State
from eqorch.gateways import LLMGateway, LLMGatewayError
from eqorch.orchestrator import DecisionContextAssembler
from eqorch.registry import ComponentConfig, ComponentConfigLoader

from .policy_store import PolicyContextStore


@dataclass(slots=True, frozen=True)
class RuntimeCheckResult:
    ok: bool
    reasons: tuple[str, ...] = ()
    policy: PolicyContext | None = None
    components: ComponentConfig | None = None


@dataclass(slots=True)
class RuntimeEnvironmentChecks:
    """Validates runtime prerequisites before starting the orchestration loop."""

    policy_store_factory: Callable[[], PolicyContextStore] = PolicyContextStore
    component_loader: ComponentConfigLoader = field(default_factory=ComponentConfigLoader)
    context_assembler: DecisionContextAssembler = field(default_factory=DecisionContextAssembler)

    def validate_startup(
        self,
        *,
        policy_path: str | Path,
        components_path: str | Path,
        llm_gateway: LLMGateway,
        component_bootstrap: Callable[[ComponentConfig], None] | None = None,
    ) -> RuntimeCheckResult:
        reasons: list[str] = []
        policy: PolicyContext | None = None
        components: ComponentConfig | None = None

        try:
            store = self.policy_store_factory()
            policy = store.load_file(policy_path)
        except Exception as exc:
            reasons.append(f"invalid policy: {exc}")

        try:
            components = self.component_loader.load_file(components_path)
        except Exception as exc:
            reasons.append(f"invalid components config: {exc}")

        if components is not None and component_bootstrap is not None:
            try:
                component_bootstrap(components)
            except Exception as exc:
                reasons.append(f"invalid component bootstrap: {exc}")

        llm_policy = policy or PolicyContext(goals=("startup validation",))
        try:
            llm_gateway.decide(self._build_context(llm_policy))
        except LLMGatewayError as exc:
            reasons.append(f"llm connectivity failed: {exc.error.code}: {exc.error.message}")
        except Exception as exc:  # pragma: no cover - defensive
            reasons.append(f"llm connectivity failed: {exc}")

        return RuntimeCheckResult(
            ok=not reasons,
            reasons=tuple(reasons),
            policy=policy,
            components=components,
        )

    def _build_context(self, policy: PolicyContext):
        state = State(
            policy_context=policy,
            workflow_memory=Memory(entries=[], max_entries=policy.max_memory_entries, eviction_policy="lru"),
            session_id=str(uuid4()),
            current_mode="interactive",
        )
        return self.context_assembler.assemble(state)


__all__ = ["RuntimeCheckResult", "RuntimeEnvironmentChecks"]
