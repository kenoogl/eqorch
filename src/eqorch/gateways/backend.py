"""Backend gateway and result normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from eqorch.domain import ErrorInfo, Result
from eqorch.registry.component_config import BackendComponentConfig


@dataclass(slots=True, frozen=True)
class ExecutionCommand:
    executable: str
    args: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class BackendExecutionResult:
    status: str
    numeric_results: dict[str, float]
    error: ErrorInfo | None


class BackendRunner(Protocol):
    def run(self, command: ExecutionCommand, config: dict[str, Any]) -> BackendExecutionResult: ...


class ResultNormalizer:
    """Normalizes backend execution results to the core Result model."""

    def normalize(self, backend_result: BackendExecutionResult) -> Result:
        payload = {"numeric_results": backend_result.numeric_results}
        if backend_result.status == "success":
            return Result(status="success", payload=payload, error=None)
        if backend_result.status == "partial":
            error = backend_result.error or ErrorInfo(
                code="PARTIAL_BACKEND_RESULT",
                message="backend returned partial results",
                retryable=True,
            )
            return Result(status="partial", payload=payload, error=error)
        if backend_result.status == "timeout":
            error = backend_result.error or ErrorInfo(
                code="TIMEOUT",
                message="backend execution timed out",
                retryable=True,
            )
            return Result(status="timeout", payload=payload, error=error)
        error = backend_result.error or ErrorInfo(
            code="BACKEND_ERROR",
            message="backend execution failed",
            retryable=False,
        )
        return Result(status="error", payload=payload, error=error)


class BackendGateway:
    """Dispatches named backend executions and normalizes their output."""

    def __init__(
        self,
        backends: tuple[BackendComponentConfig, ...],
        runners: dict[str, BackendRunner],
        normalizer: ResultNormalizer | None = None,
    ) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._runners = runners
        self._normalizer = normalizer or ResultNormalizer()

    def run(self, backend_name: str, config: dict[str, Any] | None = None) -> Result:
        config = config or {}
        backend = self._backends.get(backend_name)
        if backend is None:
            return Result(
                status="error",
                payload={},
                error=ErrorInfo(code="BACKEND_NOT_FOUND", message=f"backend not found: {backend_name}", retryable=False),
            )
        runner = self._runners[backend.name]
        execution = ExecutionCommand(executable=backend.executable, args=backend.args)
        backend_result = runner.run(execution, config)
        return self._normalizer.normalize(backend_result)

