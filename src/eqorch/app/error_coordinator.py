"""Error normalization and routing decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eqorch.domain import ErrorInfo


@dataclass(slots=True, frozen=True)
class CoordinatedError:
    error: ErrorInfo
    category: str
    should_record_last_error: bool
    should_notify_user: bool
    should_stop: bool


class ErrorCoordinator:
    """Normalizes failures across component boundaries."""

    def normalize(
        self,
        *,
        source: str,
        failure: Exception | str | dict[str, Any],
    ) -> CoordinatedError:
        error = self._to_error_info(source, failure)
        category = self._categorize(source, error)
        return CoordinatedError(
            error=error,
            category=category,
            should_record_last_error=True,
            should_notify_user=category in {"persistence_fatal", "user_visible"},
            should_stop=category == "persistence_fatal",
        )

    def _to_error_info(self, source: str, failure: Exception | str | dict[str, Any]) -> ErrorInfo:
        if isinstance(failure, ErrorInfo):
            return failure
        if isinstance(failure, dict):
            return ErrorInfo(
                code=str(failure["code"]),
                message=str(failure["message"]),
                retryable=bool(failure.get("retryable", False)),
            )
        if isinstance(failure, Exception):
            code = _exception_code(source, failure)
            return ErrorInfo(code=code, message=str(failure), retryable=_is_retryable_exception(failure))
        return ErrorInfo(code=_default_code(source), message=str(failure), retryable=False)

    def _categorize(self, source: str, error: ErrorInfo) -> str:
        if source == "persistence" and not error.retryable:
            return "persistence_fatal"
        if source in {"llm", "external", "backend", "engine"}:
            return "recoverable" if error.retryable else "user_visible"
        if source == "state":
            return "state_failure"
        return "user_visible"


def _default_code(source: str) -> str:
    return {
        "external": "EXTERNAL_EXECUTION_FAILED",
        "llm": "LLM_DECISION_FAILED",
        "persistence": "PERSISTENCE_FAILED",
        "state": "STATE_APPLY_FAILED",
        "backend": "BACKEND_FAILED",
        "engine": "ENGINE_FAILED",
    }.get(source, "UNSPECIFIED_ERROR")


def _exception_code(source: str, failure: Exception) -> str:
    if isinstance(failure, TimeoutError):
        return "TIMEOUT"
    return _default_code(source)


def _is_retryable_exception(failure: Exception) -> bool:
    return isinstance(failure, TimeoutError)

