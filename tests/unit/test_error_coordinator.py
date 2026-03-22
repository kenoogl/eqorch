from __future__ import annotations

import unittest

from eqorch.app import ErrorCoordinator
from eqorch.domain import ErrorInfo
from eqorch.gateways import LLMGatewayError


class ErrorCoordinatorTest(unittest.TestCase):
    def test_normalizes_external_failure(self) -> None:
        coordinator = ErrorCoordinator()

        coordinated = coordinator.normalize(source="external", failure={"code": "ENGINE_FAILED", "message": "bad", "retryable": False})

        self.assertEqual(coordinated.error.code, "ENGINE_FAILED")
        self.assertEqual(coordinated.category, "user_visible")
        self.assertTrue(coordinated.should_record_last_error)
        self.assertTrue(coordinated.should_notify_user)
        self.assertFalse(coordinated.should_stop)

    def test_normalizes_llm_timeout_as_recoverable(self) -> None:
        coordinator = ErrorCoordinator()

        coordinated = coordinator.normalize(source="llm", failure=TimeoutError("timed out"))

        self.assertEqual(coordinated.error.code, "TIMEOUT")
        self.assertEqual(coordinated.category, "recoverable")
        self.assertFalse(coordinated.should_notify_user)
        self.assertFalse(coordinated.should_stop)

    def test_marks_non_retryable_persistence_failure_as_fatal(self) -> None:
        coordinator = ErrorCoordinator()

        coordinated = coordinator.normalize(source="persistence", failure={"code": "DB_DOWN", "message": "disk full", "retryable": False})

        self.assertEqual(coordinated.category, "persistence_fatal")
        self.assertTrue(coordinated.should_notify_user)
        self.assertTrue(coordinated.should_stop)

    def test_uses_error_info_from_gateway_error(self) -> None:
        coordinator = ErrorCoordinator()

        coordinated = coordinator.normalize(
            source="llm",
            failure=LLMGatewayError(
                ErrorInfo(code="LLM_AUTH_FAILED", message="bad credentials", retryable=False)
            ),
        )

        self.assertEqual(coordinated.error.code, "LLM_AUTH_FAILED")
        self.assertEqual(coordinated.category, "user_visible")


if __name__ == "__main__":
    unittest.main()
