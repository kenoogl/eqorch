"""Research concierge orchestration service."""

from __future__ import annotations

from dataclasses import dataclass, field

from eqorch.app.error_coordinator import CoordinatedError, ErrorCoordinator
from eqorch.app.retry_policy import RetryPolicyExecutor
from eqorch.domain import Action
from eqorch.gateways.llm import LLMGateway, LLMGatewayError
from eqorch.orchestrator import DecisionContext


class DecisionSupportAdapter:
    """Optional adapter hook for critique or evaluation support."""

    def augment(self, context: DecisionContext) -> DecisionContext:
        return context


@dataclass(slots=True, frozen=True)
class ConciergeDecisionOutcome:
    actions: tuple[Action, ...]
    attempts: int
    coordinated_error: CoordinatedError | None = None


@dataclass(slots=True)
class ResearchConcierge:
    """Produces action decisions via LLM gateway and optional support adapters."""

    gateway: LLMGateway
    support_adapters: tuple[DecisionSupportAdapter, ...] = field(default_factory=tuple)
    error_coordinator: ErrorCoordinator = field(default_factory=ErrorCoordinator)
    retry_executor: RetryPolicyExecutor = field(default_factory=RetryPolicyExecutor)

    def decide(self, context: DecisionContext) -> list[Action]:
        current = context
        for adapter in self.support_adapters:
            current = adapter.augment(current)
        actions = self.gateway.decide(current)
        if not actions:
            raise ValueError("ResearchConcierge must return at least one action")
        return actions

    def decide_with_retry(self, context: DecisionContext, *, issued_at: str) -> ConciergeDecisionOutcome:
        current = context
        for adapter in self.support_adapters:
            current = adapter.augment(current)

        attempt = 0
        while True:
            try:
                actions = self.gateway.decide(current)
                if not actions:
                    raise ValueError("ResearchConcierge must return at least one action")
                return ConciergeDecisionOutcome(actions=tuple(actions), attempts=attempt + 1)
            except LLMGatewayError as exc:
                coordinated = self.error_coordinator.normalize(source="llm", failure=exc)
                decision = self.retry_executor.evaluate_llm_failure(
                    policy=current.policy_context,
                    current_mode=current.current_mode,
                    attempt=attempt,
                    error=coordinated.error,
                    issued_at=issued_at,
                )
                if decision.should_retry:
                    attempt += 1
                    continue
                fallback = ()
                if decision.fallback_action is not None:
                    fallback = (decision.fallback_action,)
                return ConciergeDecisionOutcome(
                    actions=fallback,
                    attempts=attempt + 1,
                    coordinated_error=coordinated,
                )
