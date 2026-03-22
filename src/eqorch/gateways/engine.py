"""Engine gateway and pending job management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eqorch.domain import ErrorInfo, PendingJob, Result
from eqorch.registry.engine_registry import EngineRegistry


class EngineTransport(Protocol):
    def run(self, endpoint: str, instruction: str, timeout_sec: int) -> dict[str, Any]: ...

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int) -> dict[str, Any]: ...

    def poll(self, endpoint: str, job_id: str, timeout_sec: int) -> dict[str, Any]: ...


class PendingJobManager:
    """Tracks async engine jobs by job id."""

    def __init__(self) -> None:
        self._jobs: dict[str, PendingJob] = {}

    def register(self, pending_job: PendingJob) -> None:
        self._jobs[pending_job.job_id] = pending_job

    def remove(self, job_id: str) -> PendingJob | None:
        return self._jobs.pop(job_id, None)

    def get(self, job_id: str) -> PendingJob | None:
        return self._jobs.get(job_id)

    def all(self) -> tuple[PendingJob, ...]:
        return tuple(self._jobs.values())


@dataclass(slots=True, frozen=True)
class EngineDispatchResult:
    result: Result
    pending_job: PendingJob | None = None


class EngineGateway:
    """Dispatches engine calls through protocol-specific transports."""

    def __init__(
        self,
        registry: EngineRegistry,
        transports: dict[str, EngineTransport],
        pending_jobs: PendingJobManager | None = None,
    ) -> None:
        self._registry = registry
        self._transports = transports
        self._pending_jobs = pending_jobs or PendingJobManager()

    @property
    def pending_jobs(self) -> PendingJobManager:
        return self._pending_jobs

    def execute(
        self,
        engine_name: str,
        instruction: str,
        *,
        action_id: str,
        issued_at: str,
        timeout_at: str,
        timeout_sec: int = 3600,
        async_mode: bool = False,
    ) -> EngineDispatchResult:
        try:
            engine = self._registry.get(engine_name)
        except KeyError:
            return EngineDispatchResult(
                result=Result(
                    status="error",
                    payload={},
                    error=ErrorInfo(code="ENGINE_NOT_FOUND", message=f"engine not found: {engine_name}", retryable=False),
                )
            )
        transport = self._transports[engine.protocol]
        if async_mode:
            payload = transport.run_async(engine.endpoint, instruction, timeout_sec)
            job_id = str(payload["job_id"])
            pending = PendingJob(
                job_id=job_id,
                engine_name=engine.name,
                action_id=action_id,
                issued_at=issued_at,
                timeout_at=timeout_at,
            )
            self._pending_jobs.register(pending)
            return EngineDispatchResult(
                result=Result(status="partial", payload={"job_id": job_id}, error=_partial_error("async job accepted")),
                pending_job=pending,
            )
        payload = transport.run(engine.endpoint, instruction, timeout_sec)
        return EngineDispatchResult(result=_normalize_transport_payload(payload))

    def poll(self, job_id: str, timeout_sec: int = 3600) -> Result:
        pending = self._pending_jobs.get(job_id)
        if pending is None:
            return Result(
                status="error",
                payload={},
                error=ErrorInfo(code="JOB_NOT_FOUND", message=f"job not found: {job_id}", retryable=False),
            )
        engine = self._registry.get(pending.engine_name)
        transport = self._transports[engine.protocol]
        payload = transport.poll(engine.endpoint, job_id, timeout_sec)
        result = _normalize_transport_payload(payload)
        if result.status != "partial":
            self._pending_jobs.remove(job_id)
        return result


def _partial_error(message: str) -> ErrorInfo:
    return ErrorInfo(code="PENDING_JOB", message=message, retryable=True)


def _normalize_transport_payload(payload: dict[str, Any]) -> Result:
    status = payload.get("status")
    error_payload = payload.get("error")
    error = None
    if error_payload is not None:
        error = ErrorInfo(
            code=error_payload["code"],
            message=error_payload["message"],
            retryable=bool(error_payload["retryable"]),
        )
    return Result(status=status, payload=dict(payload.get("payload", {})), error=error)

