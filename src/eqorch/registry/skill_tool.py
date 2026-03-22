"""Skill and tool registry implementations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from importlib import import_module
from typing import Any, Protocol

from eqorch.domain import ErrorInfo, Request, Result, SkillRequest
from .component_config import SkillComponentConfig, ToolComponentConfig


class SkillContract(Protocol):
    def execute(self, request: SkillRequest) -> Result: ...


class ToolContract(Protocol):
    def execute(self, request: Request) -> Result: ...


class SkillRegistry:
    """Resolves and executes configured skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillContract] = {}

    def register_from_config(self, configs: tuple[SkillComponentConfig, ...]) -> None:
        for config in configs:
            self._skills[config.name] = _load_component(
                module_name=config.module,
                class_name=config.class_name,
                expected_method="execute",
            )

    def get(self, name: str) -> SkillContract:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError("SKILL_NOT_FOUND") from exc

    def execute(self, name: str, request: SkillRequest) -> Result:
        try:
            skill = self.get(name)
        except KeyError:
            return Result(
                status="error",
                payload={},
                error=ErrorInfo(code="SKILL_NOT_FOUND", message=f"skill not found: {name}", retryable=False),
            )
        timeout_sec = request.timeout_sec or 60
        return _run_with_timeout(lambda: skill.execute(request), timeout_sec)


class ToolRegistry:
    """Resolves and executes configured tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolContract] = {}

    def register_from_config(self, configs: tuple[ToolComponentConfig, ...]) -> None:
        for config in configs:
            self._tools[config.name] = _load_component(
                module_name=config.module,
                class_name=config.class_name,
                expected_method="execute",
            )

    def get(self, name: str) -> ToolContract:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError("TOOL_NOT_FOUND") from exc

    def execute(self, name: str, request: Request) -> Result:
        timeout_sec = request.timeout_sec or 30
        try:
            tool = self.get(name)
        except KeyError:
            return Result(
                status="error",
                payload={},
                error=ErrorInfo(code="TOOL_NOT_FOUND", message=f"tool not found: {name}", retryable=False),
            )
        return _run_with_timeout(lambda: tool.execute(request), timeout_sec)


def _load_component(module_name: str, class_name: str, expected_method: str) -> Any:
    module = import_module(module_name)
    component_class = getattr(module, class_name)
    instance = component_class()
    if not hasattr(instance, expected_method):
        raise TypeError(f"{module_name}.{class_name} must define {expected_method}")
    return instance


def _run_with_timeout(callback: Any, timeout_sec: int) -> Result:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callback)
        try:
            result = future.result(timeout=timeout_sec)
        except FutureTimeoutError:
            return Result(
                status="timeout",
                payload={},
                error=ErrorInfo(code="TIMEOUT", message="component execution timed out", retryable=True),
            )
    if not isinstance(result, Result):
        raise TypeError("component must return Result")
    return result
