# pyright: strict
"""Application-level lifecycle and protocol boundary for SAgents v2."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar, TypedDict, Unpack, NotRequired
from pathlib import Path

from sagents.v2.composition.inputs import PackageInput, RuntimeInput
from sagents.v2.model.catalog import ModelCatalogInput, ModelCatalogConfig
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.composition.loaded_agents import LoadedAgent, LoadedAgents, ApplicationEntrypoint, StartupRecoveryIssue

from sagents.v2.composition.contracts import (
    ApplicationResource as ApplicationResource,
)
from sagents.v2.composition.contracts import (
    ResolvedApplicationPlan as ResolvedApplicationPlan,
)
from sagents.v2.composition.contracts import (
    ResolvedProviderBinding as ResolvedProviderBinding,
)
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.runtime_skills import RuntimeSkillAuthorization
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import EventCursor, RunHandle, RunSnapshot
from sagents.v2.interfaces.protocols.contracts import AdapterResult, ProtocolAdapter
from sagents.v2.runtime.extensions import ExtensionScopeHandle, StopReason
from sagents.v2.sagent import SAgent, SAgentRunStream

class _CompositionPorts(TypedDict):
    agents: Mapping[str, SAgent]
    entrypoint_agent_id: str | None
    scope_handles: tuple[ExtensionScopeHandle, ...]
    services: Mapping[str, Any]
    adapters: Mapping[str, ProtocolAdapter]
    composition_hash: str
    resolved_plan: NotRequired[ResolvedApplicationPlan | None]
    owned_resources: NotRequired[tuple[ApplicationResource, ...]]
    resource_readiness: NotRequired[dict[str, Any] | None]


T = TypeVar("T")

@dataclass
class InterfaceRunStream:
    """Protocol-projected view of a Native run stream."""

    native: SAgentRunStream
    results: AsyncIterator[AdapterResult]

    @property
    def handle(self) -> RunHandle:
        return self.native.handle

    async def detach(self) -> None:
        try:
            closer = getattr(self.results, "aclose", None)
            if closer is not None:
                await closer()
        finally:
            await self.native.detach()

    async def wait(self) -> RunSnapshot:
        return await self.native.wait()


class SAgentApplication:
    """Own every process resource and expose logical Agents and interfaces.

    ``SAgent`` instances intentionally do not own process resources.  This root
    is the sole close boundary for extension scopes, package/runtime services,
    and the Agents composed from them.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("SAgentApplication is created by SAgentBuilder; use build(), load_agent() and entrypoint()")

    @classmethod
    def _from_composition(cls, **ports: Unpack[_CompositionPorts]) -> SAgentApplication:
        """Internal SDK assembly; host integrations use SAgentBuilder."""
        instance = cls.__new__(cls)
        instance._initialize(**ports)
        return instance

    def _initialize(
        self,
        *,
        agents: Mapping[str, SAgent],
        entrypoint_agent_id: str | None,
        scope_handles: tuple[ExtensionScopeHandle, ...],
        services: Mapping[str, Any],
        adapters: Mapping[str, ProtocolAdapter],
        composition_hash: str,
        resolved_plan: ResolvedApplicationPlan | None = None,
        owned_resources: tuple[ApplicationResource, ...] = (),
        resource_readiness: dict[str, Any] | None = None,
    ) -> None:
        if entrypoint_agent_id is not None and entrypoint_agent_id not in agents:
            raise ValueError(f"unknown application entrypoint {entrypoint_agent_id!r}")
        self._loaded_agents: LoadedAgents | None = None
        self._agents = dict(agents)
        self._entrypoint_agent_id = entrypoint_agent_id
        self._scope_handles = list(scope_handles)
        self._services = dict(services)
        self._adapters = dict(adapters)
        self.resource_readiness = resource_readiness
        self.composition_hash = composition_hash
        self.resolved_plan = resolved_plan or ResolvedApplicationPlan(
            package_id="unknown",
            manifest_hash="unknown",
            entrypoint_agent_id=entrypoint_agent_id or "",
            providers=(),
            dependencies=(),
            composition_hash=composition_hash,
        )
        self._owned_resources = list(owned_resources)
        self._pending_agents = list(self._agents.values())
        self._close_lock = asyncio.Lock()
        self._materialize_idle = asyncio.Condition(self._close_lock)
        self._materialize_inflight = 0
        self._closed = False
        self._closing = False



    def _retain_scope(self, scope: ExtensionScopeHandle) -> None:
        """Register a scope created by an in-flight assembly operation.

        Close waits for assembly to settle, so registration is valid while
        closing, but never after the application has closed.
        """
        if self._closed:
            raise RuntimeError("SAgentApplication is closed")
        if self._closing and not self._materialize_inflight:
            raise RuntimeError("SAgentApplication is closing")
        if all(scope is not existing for existing in self._scope_handles):
            self._scope_handles.append(scope)

    @asynccontextmanager
    async def _assembly_operation(self):
        async with self._close_lock:
            self._ensure_open()
            self._materialize_inflight += 1
        try:
            yield
        finally:
            async with self._close_lock:
                self._materialize_inflight -= 1
                self._materialize_idle.notify_all()

    @property
    def models(self):
        """A detached snapshot of the App catalog, never a mutable registry."""
        self._ensure_open()
        if self._loaded_agents is None:
            raise RuntimeError("model management requires an App built by SAgentBuilder")
        return self._loaded_agents.models.model_copy(deep=True)

    async def update_models(self, models: ModelCatalogInput | None = None, *, models_config_text: str | None = None) -> ModelCatalogConfig:
        """Publish a validated catalog for subsequent loads; keep old revisions."""
        from sagents.v2.model.catalog import model_catalog_input
        if self._loaded_agents is None:
            raise RuntimeError("model management requires an App built by SAgentBuilder")
        selected = model_catalog_input(models, config_text=models_config_text)
        async with self._assembly_operation(), self._loaded_agents.lock:
            self._loaded_agents.models = selected
            self._loaded_agents.model_resolver.models = selected
        return self.models

    @property
    def runtime_configuration(self):
        """A detached copy of the selections used for new Agent revisions."""
        if self._loaded_agents is None:
            raise RuntimeError("runtime configuration requires a Builder-built App")
        return self._loaded_agents.runtime.model_copy(deep=True)

    async def initialize_workspace(self, path: str | Path) -> Any:
        """Initialize a product workspace through the currently selected capability."""
        if self._loaded_agents is None:
            raise RuntimeError("workspace initialization requires a Builder-built App")
        async with self._assembly_operation():
            return await self._loaded_agents.initialize_workspace(path)

    async def update_runtime(self, runtime: RuntimeInput) -> RuntimeConfig:
        """Select capabilities for subsequently loaded revisions; keep accepted Runs frozen.

        An App keeps one authoritative store and execution queue. Changing those
        process identities requires a new App rather than splitting its Run index.
        """
        from sagents.v2.composition.inputs import runtime_input
        from sagents.v2.composition.defaults import effective_runtime
        selected = runtime_input(runtime)
        if selected is None:
            raise ValueError("runtime configuration is required")
        selected = effective_runtime(selected)
        if self._loaded_agents is None:
            raise RuntimeError("runtime updates require a Builder-built App")
        async with self._assembly_operation(), self._loaded_agents.lock:
            previous = self._loaded_agents.runtime
            self._loaded_agents.validate_runtime(selected)
            if previous.state_root != selected.state_root:
                raise ValueError("state_root is an App identity; create a new App to change it")
            for capability in ("session.store", "derived-state.store", "execution.scheduler", "execution.job-runtime"):
                if previous.selections(capability) != selected.selections(capability):
                    raise ValueError(f"{capability} is an App identity; create a new App to change it")
            if (previous.plugin_trust_policy != selected.plugin_trust_policy
                    or previous.deployment_profile != selected.deployment_profile):
                raise ValueError("security profile is an App identity; create a new App to change it")
            self._loaded_agents.set_runtime(selected)
        return selected.model_copy(deep=True)

    async def update_runtime_skill_authorizations(
        self, authorizations: Sequence[RuntimeSkillAuthorization | dict[str, Any]],
    ) -> tuple[RuntimeSkillAuthorization, ...]:
        """Replace the App-wide runtime Skill ceiling without rebuilding.

        The new set applies to every later admission, child delegation and
        execution or resume, including Runs already accepted. A loop that is
        currently executing keeps the Skills it has already loaded.
        """
        if self._loaded_agents is None:
            raise RuntimeError("runtime updates require a Builder-built App")
        grants = tuple(RuntimeSkillAuthorization.model_validate(value) for value in authorizations)
        async with self._assembly_operation(), self._loaded_agents.lock:
            runtime = self._loaded_agents.runtime
            self._loaded_agents.set_runtime(
                runtime.model_copy(update={"runtime_skill_authorizations": grants}))
        return grants

    async def update_model(self, model_id: str, config: ModelRoute | dict[str, Any]) -> ModelCatalogConfig:
        """Add or replace one model atomically; credentials live in App config."""
        from sagents.v2.model.catalog import ModelCatalogConfig
        from sagents.v2.package.manifest.models import ModelRoute
        if self._loaded_agents is None:
            raise RuntimeError("model management requires an App built by SAgentBuilder")
        async with self._assembly_operation(), self._loaded_agents.lock:
            catalog = self._loaded_agents.models
            selected = ModelCatalogConfig(
                models={**catalog.models, model_id: ModelRoute.model_validate(config)},
                credentials=catalog.credentials,
            ).model_copy(deep=True)
            self._loaded_agents.models = selected
            self._loaded_agents.model_resolver.models = selected
        return self.models






    @property
    def recovery_issues(self) -> tuple[StartupRecoveryIssue, ...]:
        """Host-level startup recovery issues from the latest restoration pass."""
        self._ensure_open()
        return self._loaded_agents.recovery_issues if self._loaded_agents is not None else ()

    async def load_agent(
        self,
        package: PackageInput | None = None,
        *,
        config_text: str | None = None,
        base_path: str | Path | None = None,
        subagents: dict[str, LoadedAgent] | None = None,
        runtime: RuntimeInput | None = None,
        models: ModelCatalogInput | None = None,
    ) -> LoadedAgent:
        """Load a Package with an optional detached runtime/model snapshot.

        Per-load selections never mutate App defaults. Process store, scheduler
        and security identities remain fixed for the lifetime of the App.
        """
        if self._loaded_agents is None:
            raise RuntimeError("load_agent requires build() without a Package")
        async with self._assembly_operation():
            agent = await self._loaded_agents.load(
                package, config_text=config_text, base_path=base_path, subagents=subagents,
                runtime=runtime, models=models,
            )
            await self._loaded_agents.restore_pending()
            return agent

    async def update_agent(
        self,
        *,
        agent: LoadedAgent,
        package: PackageInput | None = None,
        config_text: str | None = None,
        base_path: str | Path | None = None,
        subagents: dict[str, LoadedAgent] | None = None,
        runtime: RuntimeInput | None = None,
        models: ModelCatalogInput | None = None,
    ) -> LoadedAgent:
        """Publish a revision from independent selections using compare-and-swap.

        Existing handles keep their admitted configuration, including after idle
        resources are released and rebuilt from their immutable revision archive.
        """
        if self._loaded_agents is None:
            raise RuntimeError("update_agent requires build() without a Package")
        return await self._loaded_agents.load(
            package,
            config_text=config_text,
            base_path=base_path,
            previous=agent,
            subagents=subagents,
            runtime=runtime, models=models,
        )

    async def agent_for_run(self, run_id: str, context: RequestContext) -> LoadedAgent:
        """Authorize a durable Run and retrieve its exact loaded revision."""
        if self._loaded_agents is None:
            raise RuntimeError("agent_for_run requires build() without a Package")
        async with self._assembly_operation():
            return await self._loaded_agents.for_run(run_id, context)

    async def execution_configuration(self, run_id: str, context: RequestContext):
        """Return the authorized Run's durable, accepted execution snapshot."""
        command = await self.service("session.access").get_start_command(run_id, context)
        snapshot = command.config.execution_snapshot
        # Frozen wire models can still contain mutable dictionaries. Never expose
        # references owned by an in-memory store through an inspection endpoint.
        return snapshot.model_copy(deep=True) if snapshot is not None else None

    async def run_configuration(self, run_id: str, context: RequestContext):
        """Inspect the authorized Run's original Agent and plugin configuration."""
        if self._loaded_agents is None:
            raise RuntimeError("run configuration requires a Builder-built App")
        return await self._loaded_agents.run_configuration(run_id, context)

    async def execution_diagnostics(self, run_id: str, context: RequestContext):
        """Last acquired sandbox facts; an absent record does not imply execution."""
        run = await self.service("session.access").get_run(run_id, context)
        from copy import deepcopy

        facts = await self.service("derived-state.store").get_derived_state(
            run.session_id, "execution.binding", run_id,
        )
        return deepcopy(facts)

    @property
    def loaded_agents(self) -> tuple[LoadedAgent, ...]:
        self._ensure_open()
        return (
            tuple(self._loaded_agents.current.values()) if self._loaded_agents else ()
        )

    def entrypoint(self) -> ApplicationEntrypoint | SAgent:
        self._ensure_open()
        if self._loaded_agents is not None:
            return self._loaded_agents.entrypoint
        assert self._entrypoint_agent_id is not None
        return self._agents[self._entrypoint_agent_id]

    def agent(self, agent_id: str) -> SAgent:
        self._ensure_open()
        if self._loaded_agents is not None:
            for handle in self.loaded_agents:
                if handle.id == agent_id:
                    return self._loaded_agents.exported(handle)
            if self._loaded_agents.root is not None:
                return self._loaded_agents.root.agent(agent_id)
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown application Agent {agent_id!r}") from exc

    @property
    def runtime(self) -> RuntimePort:
        """Shared control runtime; Agent selection belongs to the run entrypoint."""
        self._ensure_open()
        if self._loaded_agents is not None:
            if self._loaded_agents.root is None:
                return self.service("runtime.kernel")
            return self._loaded_agents.root.runtime
        assert self._entrypoint_agent_id is not None
        return self._agents[self._entrypoint_agent_id].runtime

    def service(self, capability: str) -> Any:
        self._ensure_open()
        try:
            return self._services[capability]
        except KeyError as exc:
            raise KeyError(
                f"application service {capability!r} is unavailable"
            ) from exc

    @property
    def services(self) -> Mapping[str, Any]:
        return dict(self._services)

    async def run_interface(
        self,
        interface: str,
        command: StartRun,
        context: RequestContext,
        *,
        agent: LoadedAgent,
    ) -> InterfaceRunStream:
        """Start a Native run and project every event with explicit loss data."""

        self._ensure_open()
        if self._loaded_agents is None:
            adapter = self._adapter(interface)
        else:
            agent = await self._loaded_agents.restored(agent)
            self._loaded_agents.implementation(agent)  # Validate this App owns the handle.
            adapter = self._loaded_agents.adapter(agent, interface) or self._adapters.get(interface)
            if adapter is None:
                raise KeyError(f"interface {interface!r} is not declared for this Agent or App")
        entrypoint = self.entrypoint()
        native = (
            await entrypoint.run_stream(command, context, agent=agent)
            if isinstance(entrypoint, ApplicationEntrypoint)
            else await entrypoint.run_stream(command, context)
        )
        if self._loaded_agents is not None:
            catalog = self._loaded_agents
            async def project_revision() -> AsyncIterator[AdapterResult]:
                async with catalog.pin(agent) as current:
                    selected = catalog.adapter(current, interface) or self._adapters.get(interface)
                    if selected is None:
                        raise KeyError(f"interface {interface!r} is not declared for this Agent or App")
                    async for result in self._project(native.events, selected):
                        yield result
            results = project_revision()
        else:
            results = self._project(native.events, adapter)
        return InterfaceRunStream(
            native=native,
            results=results,
        )

    def subscribe_interface(
        self,
        interface: str,
        cursor: EventCursor,
        context: RequestContext,
        *,
        agent_id: str | None = None,
    ) -> AsyncIterator[AdapterResult]:
        """Replay canonical RuntimeEvents through one declared protocol adapter."""

        self._ensure_open()
        if self._loaded_agents is None:
            native = self.agent(agent_id or self.resolved_plan.entrypoint_agent_id).subscribe_events(cursor, context)
            return self._project(native, self._adapter(interface))

        catalog = self._loaded_agents
        async def replay() -> AsyncIterator[AdapterResult]:
            agent = await self.agent_for_run(cursor.run_id, context)
            async with catalog.pin(agent) as agent:
                implementation = catalog.implementation(agent)
                adapter = catalog.adapter(agent, interface) or self._adapters.get(interface)
                if adapter is None:
                    raise KeyError(f"interface {interface!r} is not declared for this Run's Agent or App")
                async for event in self._project(implementation.subscribe_events(cursor, context), adapter):
                    yield event
        return replay()

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            while self._materialize_inflight:
                await self._materialize_idle.wait()
            errors: list[Exception] = []
            pending_resources = list(reversed(self._owned_resources))
            for index, resource in enumerate(pending_resources):
                try:
                    await resource.close()
                except Exception as exc:
                    errors.append(exc)
                    self._owned_resources = list(reversed(pending_resources[index:]))
                    break
            else:
                self._owned_resources = []
            if not self._owned_resources:
                for index, agent in enumerate(self._pending_agents):
                    try:
                        await agent.close()
                    except Exception as exc:
                        errors.append(exc)
                        self._pending_agents = self._pending_agents[index:]
                        break
                else:
                    self._pending_agents = []
            if not self._owned_resources and not self._pending_agents:
                pending_handles = list(reversed(self._scope_handles))
                for index, handle in enumerate(pending_handles):
                    try:
                        await handle.close(StopReason.HOST_SHUTDOWN)
                    except Exception as exc:
                        errors.append(exc)
                        self._scope_handles = list(reversed(pending_handles[index:]))
                        break
                else:
                    self._scope_handles = []
            self._closed = not (
                self._owned_resources or self._pending_agents or self._scope_handles
            )
            if errors:
                raise RuntimeError(
                    f"{len(errors)} application scope(s) failed to close"
                ) from errors[0]

    def _adapter(self, name: str) -> ProtocolAdapter:
        if self._loaded_agents is not None and self._loaded_agents.root is not None:
            return self._loaded_agents.root._adapter(name)
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise KeyError(f"interface {name!r} is not declared") from exc

    @staticmethod
    async def _project(
        events: AsyncIterator[RuntimeEvent], adapter: ProtocolAdapter
    ) -> AsyncIterator[AdapterResult]:
        async for event in events:
            # AdapterResult validates the no-silent-drop invariant at creation.
            yield adapter.translate(event)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SAgentApplication is closed")
        if self._closing:
            raise RuntimeError("SAgentApplication is closing")
