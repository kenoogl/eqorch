"""LLM gateway with provider-specific response normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import json
from uuid import uuid4

from eqorch.domain import Action, ErrorInfo
from eqorch.orchestrator import DecisionContext


class LLMProviderAdapter(Protocol):
    def decide(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class LLMGatewayError(Exception):
    """Provider failure normalized to an ErrorInfo payload."""

    def __init__(self, error: ErrorInfo) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass(slots=True, frozen=True)
class LLMGateway:
    """Normalizes provider outputs to EqOrch actions."""

    provider: str
    adapter: LLMProviderAdapter

    def decide(self, context: DecisionContext) -> list[Action]:
        request = _context_to_payload(context)
        try:
            response = self.adapter.decide(request)
            actions = _normalize_provider_response(self.provider, response)
        except Exception as exc:
            raise LLMGatewayError(_normalize_provider_failure(self.provider, exc)) from exc
        if not actions:
            raise LLMGatewayError(
                ErrorInfo(code="LLM_EMPTY_ACTIONS", message="LLMGateway must return at least one action", retryable=False)
            )
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
    elif provider == "google":
        raw_actions = _extract_google_actions(response)
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


def _extract_google_actions(response: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = response.get("candidates", [])
    if not candidates:
        raise ValueError("google response must contain candidates")
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    if not parts:
        raise ValueError("google response must contain content.parts")
    text_parts = [part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part]
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


def _normalize_provider_failure(provider: str, failure: Exception) -> ErrorInfo:
    if isinstance(failure, TimeoutError):
        return ErrorInfo(code="TIMEOUT", message=str(failure), retryable=True)
    if isinstance(failure, PermissionError):
        return ErrorInfo(code="LLM_AUTH_FAILED", message=str(failure), retryable=False)
    if isinstance(failure, ConnectionError):
        return ErrorInfo(
            code="LLM_PROVIDER_TEMPORARY_FAILURE",
            message=f"{provider} provider temporary failure: {failure}",
            retryable=True,
        )
    if isinstance(failure, ValueError):
        return ErrorInfo(code="LLM_INVALID_RESPONSE", message=str(failure), retryable=False)
    return ErrorInfo(code="LLM_DECISION_FAILED", message=str(failure), retryable=False)
