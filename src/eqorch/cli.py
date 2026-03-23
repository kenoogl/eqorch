"""CLI entry points for EqOrch."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from eqorch.app import ErrorCoordinator, PolicyContextStore, ResearchConcierge, RetryPolicyExecutor
from eqorch.app.runtime_checks import RuntimeCheckResult, RuntimeEnvironmentChecks
from eqorch.domain import Memory, Result, State
from eqorch.gateways import (
    BackendExecutionResult,
    BackendGateway,
    BackendRunner,
    EngineGateway,
    EngineTransport,
    LLMGateway,
    LLMProviderAdapter,
    PendingJobManager,
    ResultNormalizer,
)
from eqorch.memory import PersistentMemoryStore, SqliteConnectionFactory
from eqorch.orchestrator import ActionDispatcher, DecisionContextAssembler, LoopCycleResult, OrchestrationLoop
from eqorch.registry import ComponentConfig, ComponentConfigLoader, EngineRegistry, SkillRegistry, ToolRegistry
from eqorch.tracing import TraceRecorder


class RuntimeBundle(Protocol):
    loop: OrchestrationLoop

    def close(self) -> None: ...


@dataclass(slots=True, frozen=True)
class StartupResult:
    started: bool
    state: State | None
    cycles: int
    reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class _DefaultRuntimeBundle:
    loop: OrchestrationLoop
    persistent_store: PersistentMemoryStore

    def close(self) -> None:
        self.persistent_store.close()


class _UnavailableEngineTransport:
    def run(self, endpoint: str, instruction: str, timeout_sec: int) -> dict[str, Any]:
        raise ConnectionError(f"engine transport unavailable for {endpoint}")

    def run_async(self, endpoint: str, instruction: str, timeout_sec: int) -> dict[str, Any]:
        raise ConnectionError(f"engine transport unavailable for {endpoint}")

    def poll(self, endpoint: str, job_id: str, timeout_sec: int) -> dict[str, Any]:
        raise ConnectionError(f"engine transport unavailable for {endpoint}")

    def cancel(self, endpoint: str, job_id: str, timeout_sec: int) -> dict[str, Any]:
        raise ConnectionError(f"engine transport unavailable for {endpoint}")


class _UnavailableBackendRunner:
    def run(self, command, config):
        return BackendExecutionResult(
            status="error",
            numeric_results={},
            error=None,
        )


def _default_adapter_resolver(provider: str, adapter_spec: str) -> LLMProviderAdapter:
    module_name, _, class_name = adapter_spec.partition(":")
    if not module_name or not class_name:
        raise ValueError("llm adapter must be specified as module:Class")
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    adapter = adapter_class()
    if not hasattr(adapter, "decide"):
        raise TypeError(f"{provider} adapter must implement decide")
    return adapter


@dataclass(slots=True)
class EqOrchApplication:
    """Bootstraps a new interactive or batch session."""

    adapter_resolver: Callable[[str, str], LLMProviderAdapter] = _default_adapter_resolver
    runtime_checks: RuntimeEnvironmentChecks = field(default_factory=RuntimeEnvironmentChecks)
    component_loader: ComponentConfigLoader = field(default_factory=ComponentConfigLoader)
    policy_store_factory: Callable[[], PolicyContextStore] = PolicyContextStore
    runtime_builder: Callable[..., RuntimeBundle] | None = None

    def start_new_session(
        self,
        *,
        mode: str,
        policy_path: str | Path,
        components_path: str | Path,
        provider: str,
        llm_adapter: str,
        database_url: str,
        max_cycles: int = 1,
        session_id: str | None = None,
    ) -> StartupResult:
        adapter = self.adapter_resolver(provider, llm_adapter)
        gateway = LLMGateway(provider=provider, adapter=adapter)
        startup = self.runtime_checks.validate_startup(
            policy_path=policy_path,
            components_path=components_path,
            llm_gateway=gateway,
            component_bootstrap=self._bootstrap_components,
        )
        if not startup.ok or startup.policy is None or startup.components is None:
            return StartupResult(started=False, state=None, cycles=0, reasons=startup.reasons)

        policy_store = self.policy_store_factory()
        policy = policy_store.load_file(policy_path)
        bundle = self._build_runtime(
            provider=provider,
            adapter=adapter,
            database_url=database_url,
            components=startup.components,
            policy_store=policy_store,
        )
        try:
            state = State(
                policy_context=policy,
                workflow_memory=Memory(entries=[], max_entries=policy.max_memory_entries, eviction_policy="lru"),
                current_mode=mode,
                session_id=session_id or str(uuid4()),
            )
            return self._run_session(bundle.loop, state, max_cycles=max_cycles)
        finally:
            bundle.close()

    def _bootstrap_components(self, components: ComponentConfig) -> None:
        skill_registry = SkillRegistry()
        tool_registry = ToolRegistry()
        skill_registry.register_from_config(components.skills)
        tool_registry.register_from_config(components.tools)
        engine_registry = EngineRegistry()
        engine_registry.register_from_config(components.engines)
        BackendGateway(
            components.backends,
            runners={backend.name: _UnavailableBackendRunner() for backend in components.backends},
            normalizer=ResultNormalizer(),
        )

    def _build_runtime(
        self,
        *,
        provider: str,
        adapter: LLMProviderAdapter,
        database_url: str,
        components: ComponentConfig,
        policy_store: PolicyContextStore,
    ) -> RuntimeBundle:
        if self.runtime_builder is not None:
            return self.runtime_builder(
                provider=provider,
                adapter=adapter,
                database_url=database_url,
                components=components,
                policy_store=policy_store,
            )

        skill_registry = SkillRegistry()
        skill_registry.register_from_config(components.skills)
        tool_registry = ToolRegistry()
        tool_registry.register_from_config(components.tools)
        engine_registry = EngineRegistry()
        engine_registry.register_from_config(components.engines)
        transports: dict[str, EngineTransport] = {
            "rest": _UnavailableEngineTransport(),
            "grpc": _UnavailableEngineTransport(),
        }
        engine_gateway = EngineGateway(
            engine_registry,
            transports,
            pending_jobs=PendingJobManager(),
        )
        backend_gateway = BackendGateway(
            components.backends,
            runners={backend.name: _UnavailableBackendRunner() for backend in components.backends},
            normalizer=ResultNormalizer(),
        )
        error_coordinator = ErrorCoordinator()
        trace_recorder = TraceRecorder()
        persistent_store = PersistentMemoryStore(database_url=database_url)
        dispatcher = ActionDispatcher(
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            engine_gateway=engine_gateway,
            backend_gateway=backend_gateway,
            policy_store=policy_store,
            error_coordinator=error_coordinator,
            trace_recorder=trace_recorder,
        )
        concierge = ResearchConcierge(
            gateway=LLMGateway(provider=provider, adapter=adapter),
            error_coordinator=error_coordinator,
            retry_executor=RetryPolicyExecutor(),
        )
        loop = OrchestrationLoop(
            context_assembler=DecisionContextAssembler(),
            concierge=concierge,
            dispatcher=dispatcher,
            trace_recorder=trace_recorder,
            persistent_store=persistent_store,
            error_coordinator=error_coordinator,
        )
        return _DefaultRuntimeBundle(loop=loop, persistent_store=persistent_store)

    def _run_session(self, loop: OrchestrationLoop, state: State, *, max_cycles: int) -> StartupResult:
        current = state
        cycles = 0
        while cycles < max_cycles:
            result = loop.run_cycle(current)
            cycles += 1
            current = result.state
            if not result.should_continue or any(action.type == "ask_user" for action in result.actions):
                break
        return StartupResult(started=True, state=current, cycles=cycles, reasons=())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eqorch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, mode in (("interactive", "interactive"), ("batch", "batch")):
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(mode=mode)
        subparser.add_argument("--policy", required=True)
        subparser.add_argument("--components", required=True)
        subparser.add_argument("--provider", required=True, choices=("openai", "anthropic", "google"))
        subparser.add_argument("--llm-adapter", required=True)
        subparser.add_argument("--database-url", required=True)
        subparser.add_argument("--max-cycles", type=int, default=1)
        subparser.add_argument("--session-id")
    return parser


def main(argv: list[str] | None = None, *, app: EqOrchApplication | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = app or EqOrchApplication()
    result = app.start_new_session(
        mode=args.mode,
        policy_path=args.policy,
        components_path=args.components,
        provider=args.provider,
        llm_adapter=args.llm_adapter,
        database_url=args.database_url,
        max_cycles=args.max_cycles,
        session_id=args.session_id,
    )
    if not result.started:
        for reason in result.reasons:
            print(reason)
        return 1
    print(f"started session {result.state.session_id} in {args.mode} mode; cycles={result.cycles}")
    return 0


__all__ = ["EqOrchApplication", "RuntimeBundle", "StartupResult", "build_parser", "main"]
