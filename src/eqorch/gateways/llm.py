"""LLM gateway with provider-specific response normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import json
from uuid import uuid4

from eqorch.domain import Action
from eqorch.orchestrator import DecisionContext


class LLMProviderAdapter(Protocol):
    def decide(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(slots=True, frozen=True)
class LLMGateway:
    """Normalizes OpenAI-compatible and Anthropic-compatible outputs to Actions."""

    provider: str
    adapter: LLMProviderAdapter

    def decide(self, context: DecisionContext) -> list[Action]:
        request = _context_to_payload(context)
        response = self.adapter.decide(request)
        actions = _normalize_provider_response(self.provider, response)
        if not actions:
            raise ValueError("LLMGateway must return at least one action")
        return actions


def _context_to_payload(context: DecisionContext) -> dict[str, Any]:
    return {
        "session_id": context.session_id,
        "step": context.step,
        "current_mode": context.current_mode,
        "candidate_count": context.candidate_count,
        "evaluation_count": context.evaluation_count,
        "pending_jobs": [
            {"job_id": job.job_id, "engine_name": job.engine_name, "timeout_at": job.timeout_at}
            for job in context.pending_jobs
        ],
        "last_errors": {
            key: {"code": error.code, "message": error.message, "retryable": error.retryable}
            for key, error in context.last_errors.items()
        },
        "workflow_memory_summary": list(context.workflow_memory_summary),
        "candidate_summary": list(context.candidate_summary),
        "evaluation_summary": list(context.evaluation_summary),
    }


def _normalize_provider_response(provider: str, response: dict[str, Any]) -> list[Action]:
    if provider == "openai":
        raw_actions = _extract_openai_actions(response)
    elif provider == "anthropic":
        raw_actions = _extract_anthropic_actions(response)
    else:
        raise ValueError(f"unsupported provider: {provider}")
    return [_raw_action_to_action(raw_action) for raw_action in raw_actions]


def _extract_openai_actions(response: dict[str, Any]) -> list[dict[str, Any]]:
    choices = response.get("choices", [])
    if not choices:
        raise ValueError("openai response must contain choices")
    message = choices[0].get("message", {})
    content = message.get("content", "[]")
    if isinstance(content, list):
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    else:
        text = str(content)
    return _parse_actions_json(text)


def _extract_anthropic_actions(response: dict[str, Any]) -> list[dict[str, Any]]:
    content = response.get("content", [])
    if not content:
        raise ValueError("anthropic response must contain content")
    text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
    return _parse_actions_json("".join(text_parts))


def _parse_actions_json(text: str) -> list[dict[str, Any]]:
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("LLM response must decode to an action list")
    return [item for item in parsed if isinstance(item, dict)]


def _raw_action_to_action(raw_action: dict[str, Any]) -> Action:
    parameters = raw_action.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("action parameters must be an object")
    return Action(
        type=raw_action["type"],
        target=raw_action["target"],
        parameters=parameters,
        issued_at=raw_action.get("issued_at", "2026-03-22T00:00:00Z"),
        action_id=raw_action.get("action_id", str(uuid4())),
    )

