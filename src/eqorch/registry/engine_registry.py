"""Engine registry implementation."""

from __future__ import annotations

from .component_config import EngineComponentConfig


class EngineRegistry:
    """Resolves configured engine endpoints."""

    def __init__(self) -> None:
        self._engines: dict[str, EngineComponentConfig] = {}

    def register_from_config(self, configs: tuple[EngineComponentConfig, ...]) -> None:
        for config in configs:
            self._engines[config.name] = config

    def get(self, name: str) -> EngineComponentConfig:
        try:
            return self._engines[name]
        except KeyError as exc:
            raise KeyError("ENGINE_NOT_FOUND") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._engines))

