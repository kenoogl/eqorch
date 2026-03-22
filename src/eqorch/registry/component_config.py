"""Component configuration loader for skills, tools, engines, and backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


class ComponentConfigError(ValueError):
    """Raised when components.yaml is malformed."""


@dataclass(slots=True, frozen=True)
class SkillComponentConfig:
    name: str
    module: str
    class_name: str


@dataclass(slots=True, frozen=True)
class ToolComponentConfig:
    name: str
    module: str
    class_name: str


@dataclass(slots=True, frozen=True)
class EngineComponentConfig:
    name: str
    endpoint: str
    protocol: Literal["rest", "grpc"]
    proto: str | None = None
    service: str | None = None


@dataclass(slots=True, frozen=True)
class BackendComponentConfig:
    name: str
    executable: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ComponentConfig:
    skills: tuple[SkillComponentConfig, ...] = ()
    tools: tuple[ToolComponentConfig, ...] = ()
    engines: tuple[EngineComponentConfig, ...] = ()
    backends: tuple[BackendComponentConfig, ...] = ()


class ComponentConfigLoader:
    """Loads and validates component configuration from YAML."""

    def load_file(self, path: str | Path) -> ComponentConfig:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ComponentConfigError("component config must be a YAML object")
        return self._normalize(raw)

    def _normalize(self, raw: dict[str, Any]) -> ComponentConfig:
        return ComponentConfig(
            skills=tuple(self._normalize_class_components(raw.get("skills", []), "skills")),
            tools=tuple(self._normalize_class_components(raw.get("tools", []), "tools")),
            engines=tuple(self._normalize_engines(raw.get("engines", []))),
            backends=tuple(self._normalize_backends(raw.get("backends", []))),
        )

    def _normalize_class_components(
        self,
        raw_components: Any,
        field_name: str,
    ) -> list[SkillComponentConfig | ToolComponentConfig]:
        if not isinstance(raw_components, list):
            raise ComponentConfigError(f"{field_name} must be a list")

        normalized: list[SkillComponentConfig | ToolComponentConfig] = []
        seen_names: set[str] = set()
        for item in raw_components:
            component = _ensure_object(item, field_name)
            name = _required_string(component, "name", field_name)
            if name in seen_names:
                raise ComponentConfigError(f"{field_name} contains duplicated name: {name}")
            seen_names.add(name)
            module = _required_string(component, "module", field_name)
            class_name = _required_string(component, "class", field_name)
            config = SkillComponentConfig(name=name, module=module, class_name=class_name)
            if field_name == "tools":
                config = ToolComponentConfig(name=name, module=module, class_name=class_name)
            normalized.append(config)
        return normalized

    def _normalize_engines(self, raw_engines: Any) -> list[EngineComponentConfig]:
        if not isinstance(raw_engines, list):
            raise ComponentConfigError("engines must be a list")

        normalized: list[EngineComponentConfig] = []
        seen_names: set[str] = set()
        for item in raw_engines:
            engine = _ensure_object(item, "engines")
            name = _required_string(engine, "name", "engines")
            if name in seen_names:
                raise ComponentConfigError(f"engines contains duplicated name: {name}")
            seen_names.add(name)
            endpoint = _required_string(engine, "endpoint", "engines")
            protocol = _required_string(engine, "protocol", "engines")
            if protocol not in {"rest", "grpc"}:
                raise ComponentConfigError("engines protocol must be 'rest' or 'grpc'")
            proto = engine.get("proto")
            service = engine.get("service")
            if protocol == "grpc":
                if not isinstance(proto, str) or not proto.strip():
                    raise ComponentConfigError("grpc engines require proto")
                if not isinstance(service, str) or not service.strip():
                    raise ComponentConfigError("grpc engines require service")
            normalized.append(
                EngineComponentConfig(
                    name=name,
                    endpoint=endpoint,
                    protocol=protocol,
                    proto=proto,
                    service=service,
                )
            )
        return normalized

    def _normalize_backends(self, raw_backends: Any) -> list[BackendComponentConfig]:
        if not isinstance(raw_backends, list):
            raise ComponentConfigError("backends must be a list")

        normalized: list[BackendComponentConfig] = []
        seen_names: set[str] = set()
        for item in raw_backends:
            backend = _ensure_object(item, "backends")
            name = _required_string(backend, "name", "backends")
            if name in seen_names:
                raise ComponentConfigError(f"backends contains duplicated name: {name}")
            seen_names.add(name)
            executable = _required_string(backend, "executable", "backends")
            args = backend.get("args", [])
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ComponentConfigError("backends args must be a list of strings")
            env = backend.get("env", {})
            if not isinstance(env, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in env.items()
            ):
                raise ComponentConfigError("backends env must be a string map")
            normalized.append(
                BackendComponentConfig(
                    name=name,
                    executable=executable,
                    args=tuple(args),
                    env=dict(env),
                )
            )
        return normalized


def _ensure_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ComponentConfigError(f"{field_name} entries must be objects")
    return value


def _required_string(value: dict[str, Any], key: str, field_name: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ComponentConfigError(f"{field_name}.{key} must be a non-empty string")
    return item

