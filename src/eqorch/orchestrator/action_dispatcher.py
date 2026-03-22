"""Action validation and dispatch planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eqorch.app import ErrorCoordinator, PolicyContextStore
from eqorch.domain import Action, ErrorInfo, Request, Result, State
from eqorch.gateways import BackendGateway, EngineGateway
from eqorch.registry import SkillRegistry, ToolRegistry
from eqorch.tracing import TracePlan, TraceRecorder


DEFAULT_TIMEOUTS = {
    "call_skill": 60,
    "call_tool": 30,
    "run_engine": 3600,
}
SINGLETON_ACTIONS = {"ask_user", "terminate"}
ALLOWED_TYPES = {
    "call_skill",
    "call_tool",
    "run_engine",
    "ask_user",
    "update_policy",
    "switch_mode",
    "terminate",
}
ALLOWED_PARAMETERS = {
    "call_skill": {"input", "timeout_sec"},
    "call_tool": {"query", "context", "timeout_sec"},
    "run_engine": {"instruction", "timeout_sec", "async"},
    "ask_user": {"prompt", "options"},
    "update_policy": {"patch"},
    "switch_mode": {"target_mode", "reason"},
    "terminate": {"reason"},
}
REQUIRED_PARAMETERS = {
    "call_skill": {"input"},
    "call_tool": {"query"},
    "run_engine": {"instruction"},
    "ask_user": {"prompt"},
    "update_policy": {"patch"},
    "switch_mode": {"target_mode"},
    "terminate": set(),
}


@dataclass(slots=True, frozen=True)
class DispatchRecord:
    action: Action
    result: Result
    trace_plan: TracePlan


class ActionDispatcher:
    """Validates and dispatches actions to execution boundaries."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        tool_registry: ToolRegistry,
        engine_gateway: EngineGateway,
        backend_gateway: BackendGateway | None,
        policy_store: PolicyContextStore,
        error_coordinator: ErrorCoordinator,
        trace_recorder: TraceRecorder,
    ) -> None:
        self._skill_registry = skill_registry
        self._tool_registry = tool_registry
        self._engine_gateway = engine_gateway
        self._backend_gateway = backend_gateway
        self._policy_store = policy_store
        self._error_coordinator = error_coordinator
        self._trace_recorder = trace_recorder

    def dispatch(self, actions: list[Action], state: State) -> list[DispatchRecord]:
        self._validate_batch(actions)
        records: list[DispatchRecord] = []
        for action in actions:
            result = self._dispatch_one(action, state)
            trace_plan = self._trace_recorder.plan(action, result, [])
            records.append(DispatchRecord(action=action, result=result, trace_plan=trace_plan))
        return records

    def _dispatch_one(self, action: Action, state: State) -> Result:
        self._validate_action(action)
        params = dict(action.parameters)
        if action.type == "call_skill":
            timeout = int(params.get("timeout_sec", DEFAULT_TIMEOUTS["call_skill"]))
            return self._skill_registry.execute(action.target, state, timeout_sec=timeout)
        if action.type == "call_tool":
            timeout = int(params.get("timeout_sec", DEFAULT_TIMEOUTS["call_tool"]))
            request = Request(
                query=str(params["query"]),
                context=params.get("context"),
                timeout_sec=timeout,
            )
            return self._tool_registry.execute(action.target, request)
        if action.type == "run_engine":
            timeout = int(params.get("timeout_sec", DEFAULT_TIMEOUTS["run_engine"]))
            dispatch = self._engine_gateway.execute(
                action.target,
                str(params["instruction"]),
                action_id=action.action_id,
                issued_at=action.issued_at,
                timeout_at=action.issued_at,
                timeout_sec=timeout,
                async_mode=bool(params.get("async", False)),
            )
            return dispatch.result
        if action.type == "ask_user":
            return Result(status="partial", payload={"prompt": params["prompt"], "options": params.get("options", [])}, error=ErrorInfo(code="USER_INPUT_REQUIRED", message="awaiting user input", retryable=False))
        if action.type == "update_policy":
            self._policy_store.apply_patch(params["patch"], source="update_policy")
            return Result(status="success", payload={"policy_update": "staged"}, error=None)
        if action.type == "switch_mode":
            target_mode = str(params["target_mode"])
            reason = str(params.get("reason", "mode switched"))
            state.current_mode = target_mode
            return Result(status="success", payload={"target_mode": target_mode, "reason": reason}, error=None)
        if action.type == "terminate":
            return Result(status="success", payload={"terminate": True, "reason": params.get("reason")}, error=None)
        raise ValueError(f"unsupported action type: {action.type}")

    def _validate_batch(self, actions: list[Action]) -> None:
        if not actions:
            raise ValueError("action batch must not be empty")
        singleton_count = sum(1 for action in actions if action.type in SINGLETON_ACTIONS)
        if singleton_count:
            if len(actions) != 1:
                raise ValueError("ask_user and terminate must run alone")

    def _validate_action(self, action: Action) -> None:
        if action.type not in ALLOWED_TYPES:
            raise ValueError(f"unsupported action type: {action.type}")
        parameters = action.parameters
        allowed = ALLOWED_PARAMETERS[action.type]
        required = REQUIRED_PARAMETERS[action.type]
        unknown = set(parameters) - allowed
        missing = required - set(parameters)
        if unknown:
            raise ValueError(f"unknown parameters for {action.type}: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing parameters for {action.type}: {sorted(missing)}")
        if action.type == "switch_mode" and parameters["target_mode"] not in {"interactive", "batch"}:
            raise ValueError("switch_mode.target_mode must be interactive or batch")

