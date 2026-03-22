"""Research concierge orchestration service."""

from __future__ import annotations

from dataclasses import dataclass, field

from eqorch.domain import Action
from eqorch.gateways.llm import LLMGateway
from eqorch.orchestrator import DecisionContext


class DecisionSupportAdapter:
    """Optional adapter hook for critique or evaluation support."""

    def augment(self, context: DecisionContext) -> DecisionContext:
        return context


@dataclass(slots=True)
class ResearchConcierge:
    """Produces action decisions via LLM gateway and optional support adapters."""

    gateway: LLMGateway
    support_adapters: tuple[DecisionSupportAdapter, ...] = field(default_factory=tuple)

    def decide(self, context: DecisionContext) -> list[Action]:
        current = context
        for adapter in self.support_adapters:
            current = adapter.augment(current)
        actions = self.gateway.decide(current)
        if not actions:
            raise ValueError("ResearchConcierge must return at least one action")
        return actions

