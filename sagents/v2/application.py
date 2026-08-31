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
        owned_resources: tuple[ApplicationResource, ...] = (),
    ) -> None:
        if entrypoint_agent_id not in agents:
            raise ValueError(f"unknown application entrypoint {entrypoint_agent_id!r}")
        self._agents = dict(agents)
        self._entrypoint_agent_id = entrypoint_agent_id
        self._scope_handles = scope_handles
        self._services = dict(services)
        self._adapters = dict(adapters)
        self.composition_hash = composition_hash
        self._owned_resources = owned_resources
        self._close_lock = asyncio.Lock()
        self._closed = False

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
            raise KeyError(f"application service {capability!r} is unavailable") from exc

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
        *,
        agent_id: str | None = None,
    ) -> AsyncIterator[AdapterResult]:
        """Replay canonical RuntimeEvents through one declared protocol adapter."""

        self._ensure_open()
        native = self.agent(agent_id or self._entrypoint_agent_id).subscribe_events(cursor)
        return self._project(native, self._adapter(interface))

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            errors: list[Exception] = []
            for resource in reversed(self._owned_resources):
                try:
                    await resource.close()
                except Exception as exc:
                    errors.append(exc)
            for agent in self._agents.values():
                try:
                    await agent.close()
                except Exception as exc:
                    errors.append(exc)
            for handle in reversed(self._scope_handles):
                try:
                    await handle.close(StopReason.HOST_SHUTDOWN)
                except Exception as exc:
                    errors.append(exc)
            self._closed = True
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
