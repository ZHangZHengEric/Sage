# pyright: strict
"""Application-level lifecycle and protocol boundary for SAgents v2."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import EventCursor, RunHandle, RunSnapshot
from sagents.v2.interfaces.protocols.contracts import AdapterResult, ProtocolAdapter
from sagents.v2.runtime.extensions import ExtensionScopeHandle, StopReason
from sagents.v2.sagent import SAgent, SAgentRunStream


class ApplicationResource(Protocol):
    """Async lifecycle resource owned exclusively by the application root."""

    async def close(self) -> None: ...


@dataclass(frozen=True, order=True)
class ResolvedProviderBinding:
    """One inspectable capability binding with no secret configuration."""

    capability: str
    name: str
    api_version: str
    plugin_id: str | None
    scope: str
    source: str


@dataclass(frozen=True)
class ResolvedApplicationPlan:
    """Frozen final composition identity exposed by an application root."""

    package_id: str
    manifest_hash: str
    entrypoint_agent_id: str
    providers: tuple[ResolvedProviderBinding, ...]
    dependencies: tuple[tuple[str, str], ...]
    composition_hash: str


@dataclass(frozen=True)
class MaterializedAgentPorts:
    """Agent/Run ports rematerialized on a live process Application."""

    token_estimator: Any
    summarizer: Any
    context_reducer: Any
    continuation_policy: Any
    tool_selection_policy: Any
    memory_query_generator: Any | None
    workspace_initializer: Any | None
    resolved_plan: ResolvedApplicationPlan
    scope_handles: tuple[Any, ...]
    tool_catalog: Any | None = None
    tool_executor: Any | None = None


@dataclass
class InterfaceRunStream:
    """Protocol-projected view of a Native run stream."""

    native: SAgentRunStream
    results: AsyncIterator[AdapterResult]

    @property
    def handle(self) -> RunHandle:
        return self.native.handle

    async def detach(self) -> None:
        await self.native.detach()

    async def wait(self) -> RunSnapshot:
        return await self.native.wait()


class SAgentApplication:
    """Own every process resource and expose logical Agents and interfaces.

    ``SAgent`` instances intentionally do not own process resources.  This root
    is the sole close boundary for extension scopes, package/runtime services,
    and the Agents composed from them.
    """

    def __init__(
        self,
        *,
        agents: Mapping[str, SAgent],
        entrypoint_agent_id: str,
        scope_handles: tuple[ExtensionScopeHandle, ...],
        services: Mapping[str, Any],
        adapters: Mapping[str, ProtocolAdapter],
        composition_hash: str,
        resolved_plan: ResolvedApplicationPlan | None = None,
        owned_resources: tuple[ApplicationResource, ...] = (),
    ) -> None:
        if entrypoint_agent_id not in agents:
            raise ValueError(f"unknown application entrypoint {entrypoint_agent_id!r}")
        self._agents = dict(agents)
        self._entrypoint_agent_id = entrypoint_agent_id
        self._scope_handles = list(scope_handles)
        self._services = dict(services)
        self._adapters = dict(adapters)
        self.composition_hash = composition_hash
        self.resolved_plan = resolved_plan or ResolvedApplicationPlan(
            package_id="unknown",
            manifest_hash="unknown",
            entrypoint_agent_id=entrypoint_agent_id,
            providers=(),
            dependencies=(),
            composition_hash=composition_hash,
        )
        self._owned_resources = list(owned_resources)
        self._pending_agents = list(self._agents.values())
        self._composer: Any | None = None
        self._close_lock = asyncio.Lock()
        self._materialize_idle = asyncio.Condition(self._close_lock)
        self._materialize_inflight = 0
        self._closed = False
        self._closing = False

    def _attach_composer(self, composer: Any) -> None:
        self._composer = composer
        composer.application = self

    async def adopt_resource(
        self,
        resource: ApplicationResource,
        *,
        close_after_existing: bool = True,
    ) -> None:
        """Transfer one host-created resource to the Application close boundary.

        Composition helpers use this for resources they construct on behalf of
        the caller. Resources adopted with ``close_after_existing`` settle only
        after the resources already owned by the Application.
        """

        async with self._close_lock:
            self._ensure_open()
            if any(value is resource for value in self._owned_resources):
                return
            if close_after_existing:
                self._owned_resources.insert(0, resource)
            else:
                self._owned_resources.append(resource)

    async def materialize_agent(
        self,
        package: Any,
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        model: Any | None = None,
        tool_catalog: Any | None = None,
        tool_executor: Any | None = None,
        locked_configs: Mapping[str, Mapping[str, Any]] | None = None,
        cache_identities: Mapping[str, Any] | None = None,
    ) -> MaterializedAgentPorts:
        """Open Agent/Run ports from a new manifest without rebuilding the process root.

        Reuses the Builder process scope and Dispatcher. Caller owns returned
        Run-scoped ``scope_handles``.
        """

        async with self._close_lock:
            self._ensure_open()
            if self._composer is None:
                raise RuntimeError(
                    "SAgentApplication.materialize_agent requires a Builder-built application"
                )
            self._materialize_inflight += 1
        try:
            return await self._composer.materialize_agent(
                package,
                tenant_id=tenant_id,
                agent_id=agent_id,
                run_id=run_id,
                model=model,
                tool_catalog=tool_catalog,
                tool_executor=tool_executor,
                locked_configs=locked_configs,
                cache_identities=cache_identities,
            )
        finally:
            async with self._close_lock:
                self._materialize_inflight -= 1
                self._materialize_idle.notify_all()

    def entrypoint(self) -> SAgent:
        self._ensure_open()
        return self._agents[self._entrypoint_agent_id]

    def agent(self, agent_id: str) -> SAgent:
        self._ensure_open()
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"unknown application Agent {agent_id!r}") from exc

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
        agent_id: str | None = None,
    ) -> InterfaceRunStream:
        """Start a Native run and project every event with explicit loss data."""

        self._ensure_open()
        adapter = self._adapter(interface)
        native = await self.agent(agent_id or self._entrypoint_agent_id).run_stream(
            command, context
        )
        return InterfaceRunStream(
            native=native,
            results=self._project(native.events, adapter),
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
        native = self.agent(agent_id or self._entrypoint_agent_id).subscribe_events(
            cursor, context
        )
        return self._project(native, self._adapter(interface))

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
