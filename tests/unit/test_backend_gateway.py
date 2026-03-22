from __future__ import annotations

import unittest

from eqorch.domain import ErrorInfo
from eqorch.gateways import BackendExecutionResult, BackendGateway
from eqorch.registry.component_config import BackendComponentConfig


class FakeBackendRunner:
    def __init__(self, result: BackendExecutionResult) -> None:
        self._result = result

    def run(self, command, config):
        return self._result


class BackendGatewayTest(unittest.TestCase):
    def test_normalizes_success_and_partial_results(self) -> None:
        backends = (
            BackendComponentConfig(name="julia", executable="julia", args=("--project", "run.jl")),
            BackendComponentConfig(name="partial", executable="julia", args=("--project", "partial.jl")),
        )
        gateway = BackendGateway(
            backends=backends,
            runners={
                "julia": FakeBackendRunner(
                    BackendExecutionResult(status="success", numeric_results={"mse": 0.1}, error=None)
                ),
                "partial": FakeBackendRunner(
                    BackendExecutionResult(
                        status="partial",
                        numeric_results={"mse": 0.2},
                        error=ErrorInfo(code="PARTIAL", message="partial", retryable=True),
                    )
                ),
            },
        )

        success = gateway.run("julia")
        partial = gateway.run("partial")

        self.assertEqual(success.status, "success")
        self.assertEqual(success.payload["numeric_results"]["mse"], 0.1)
        self.assertEqual(partial.status, "partial")
        self.assertEqual(partial.error.code, "PARTIAL")

    def test_returns_missing_backend_error(self) -> None:
        gateway = BackendGateway(backends=(), runners={})

        result = gateway.run("missing")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, "BACKEND_NOT_FOUND")

    def test_normalizes_timeout(self) -> None:
        gateway = BackendGateway(
            backends=(BackendComponentConfig(name="julia", executable="julia"),),
            runners={
                "julia": FakeBackendRunner(
                    BackendExecutionResult(status="timeout", numeric_results={}, error=None)
                )
            },
        )

        result = gateway.run("julia")

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error.code, "TIMEOUT")


if __name__ == "__main__":
    unittest.main()
