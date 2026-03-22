"""Retry policy evaluation for LLM failures."""

from __future__ import annotations

from dataclasses import dataclass

from eqorch.domain import Action, ErrorInfo
from eqorch.domain.policy import PolicyContext


@dataclass(slots=True, frozen=True)
class RetryDecision:
    should_retry: bool
    wait_seconds: int
    fallback_action: Action | None


class RetryPolicyExecutor:
    """Evaluates retry/fallback behavior from policy settings."""

    def evaluate_llm_failure(
        self,
        *,
        policy: PolicyContext,
        current_mode: str,
        attempt: int,
        error: ErrorInfo,
        issued_at: str,
    ) -> RetryDecision:
        if not error.retryable:
            return RetryDecision(
                should_retry=False,
                wait_seconds=0,
                fallback_action=self._fallback_action(current_mode, issued_at, error.message),
            )
        if "call_llm" in policy.retry.excluded_types:
            return RetryDecision(
                should_retry=False,
                wait_seconds=0,
                fallback_action=self._fallback_action(current_mode, issued_at, error.message),
            )
        if attempt < policy.retry.max_retries:
            return RetryDecision(
                should_retry=True,
                wait_seconds=policy.retry.retry_interval_sec,
                fallback_action=None,
            )
        return RetryDecision(
            should_retry=False,
            wait_seconds=0,
            fallback_action=self._fallback_action(current_mode, issued_at, error.message),
        )

    def _fallback_action(self, current_mode: str, issued_at: str, reason: str) -> Action:
        if current_mode == "interactive":
            return Action(
                type="ask_user",
                target="user",
                parameters={"prompt": f"LLM decision failed: {reason}", "options": ["retry", "stop"]},
                issued_at=issued_at,
                action_id="00000000-0000-4000-8000-000000000001",
            )
        return Action(
            type="terminate",
            target="system",
            parameters={"reason": f"LLM retries exhausted: {reason}"},
            issued_at=issued_at,
            action_id="00000000-0000-4000-8000-000000000002",
        )

