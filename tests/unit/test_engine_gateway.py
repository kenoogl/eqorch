from __future__ import annotations

import unittest
from uuid import uuid4

from eqorch.gateways import EngineGateway, PendingJobManager
from eqorch.registry import ComponentConfigLoader, EngineRegistry


def _ts() -> str:
    return "2026-03-22T00:00:00Z"


class FakeRestTransport:
    def run(self, endpoint: str, instruction: str, timeout_sec: int) -> dict:
        return {"status": "success", "payload": {"endpoint": endpoint, "instruction": instruction}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int) -> dict:
        return {"job_id": "rest-job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int) -> dict:
        return {"status": "success", "payload": {"job_id": job_id, "protocol": "rest"}}


class FakeGrpcTransport:
    def run(self, endpoint: str, instruction: str, timeout_sec: int) -> dict:
        return {"status": "success", "payload": {"endpoint": endpoint, "instruction": instruction, "protocol": "grpc"}}

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int) -> dict:
        return {"job_id": "grpc-job-1"}

    def poll(self, endpoint: str, job_id: str, timeout_sec: int) -> dict:
        return {
            "status": "partial",
            "payload": {"job_id": job_id},
            "error": {"code": "PENDING_JOB", "message": "still running", "retryable": True},
        }


class EngineGatewayTest(unittest.TestCase):
    def test_dispatches_rest_and_grpc_by_protocol(self) -> None:
        loader = ComponentConfigLoader()
        config = loader._normalize(
            {
                "engines": [
                    {"name": "rest_engine", "endpoint": "http://localhost:8080/engine", "protocol": "rest"},
                    {
                        "name": "grpc_engine",
                        "endpoint": "dns:///engine",
                        "protocol": "grpc",
                        "proto": "path/to/engine.proto",
                        "service": "EngineService",
                    },
                ]
            }
        )
        registry = EngineRegistry()
        registry.register_from_config(config.engines)
        gateway = EngineGateway(
            registry=registry,
            transports={"rest": FakeRestTransport(), "grpc": FakeGrpcTransport()},
        )

        rest_result = gateway.execute(
            "rest_engine",
            "run rest",
            action_id=str(uuid4()),
            issued_at=_ts(),
            timeout_at=_ts(),
        )
        grpc_result = gateway.execute(
            "grpc_engine",
            "run grpc",
            action_id=str(uuid4()),
            issued_at=_ts(),
            timeout_at=_ts(),
        )

        self.assertEqual(rest_result.result.payload["endpoint"], "http://localhost:8080/engine")
        self.assertEqual(grpc_result.result.payload["protocol"], "grpc")

    def test_registers_async_job_and_polls(self) -> None:
        loader = ComponentConfigLoader()
        config = loader._normalize(
            {"engines": [{"name": "rest_engine", "endpoint": "http://localhost:8080/engine", "protocol": "rest"}]}
        )
        registry = EngineRegistry()
        registry.register_from_config(config.engines)
        manager = PendingJobManager()
        gateway = EngineGateway(
            registry=registry,
            transports={"rest": FakeRestTransport()},
            pending_jobs=manager,
        )

        dispatch = gateway.execute(
            "rest_engine",
            "run async",
            action_id=str(uuid4()),
            issued_at=_ts(),
            timeout_at=_ts(),
            async_mode=True,
        )
        polled = gateway.poll("rest-job-1")

        self.assertEqual(dispatch.result.status, "partial")
        self.assertIsNotNone(dispatch.pending_job)
        self.assertEqual(polled.status, "success")
        self.assertIsNone(manager.get("rest-job-1"))

    def test_pending_job_remains_for_partial_poll(self) -> None:
        loader = ComponentConfigLoader()
        config = loader._normalize(
            {
                "engines": [
                    {
                        "name": "grpc_engine",
                        "endpoint": "dns:///engine",
                        "protocol": "grpc",
                        "proto": "path/to/engine.proto",
                        "service": "EngineService",
                    }
                ]
            }
        )
        registry = EngineRegistry()
        registry.register_from_config(config.engines)
        manager = PendingJobManager()
        gateway = EngineGateway(
            registry=registry,
            transports={"grpc": FakeGrpcTransport()},
            pending_jobs=manager,
        )

        gateway.execute(
            "grpc_engine",
            "run async",
            action_id=str(uuid4()),
            issued_at=_ts(),
            timeout_at=_ts(),
            async_mode=True,
        )
        result = gateway.poll("grpc-job-1")

        self.assertEqual(result.status, "partial")
        self.assertIsNotNone(manager.get("grpc-job-1"))

