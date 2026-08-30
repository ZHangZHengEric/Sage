"""Session-scoped projection of Fibre agents created by ``sys_spawn_agent``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sagents.v2.agent.multi_agent.contracts import AgentDescriptor
from sagents.v2.contracts.items import (
    ItemStatus,
    JsonBlock,
    ToolCallItemData,
    ToolResultItemData,
)
from sagents.v2.runtime.session.contracts import SessionStore


@dataclass
class _RosterLockEntry:
    lock: asyncio.Lock
    users: int = 0


class SessionDynamicAgentRoster:
    """Rebuild dynamic Fibre members from one Session's canonical event log.

    The successful ``sys_spawn_agent`` Tool result is the durable fact. Derived
    state is only a sequence-bound cache, so deleting or corrupting it never
    loses the roster and deleting the Session removes the roster automatically.
    """

    NAMESPACE = "multi_agent"
    KEY = "dynamic_agent_roster_v1"
    SCHEMA_VERSION = 2

    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store
        self._locks: dict[str, _RosterLockEntry] = {}
        self._locks_guard = asyncio.Lock()

    async def load(self, session_id: str) -> tuple[AgentDescriptor, ...]:
        async with self._session_lock(session_id):
            session = await self.session_store.get_session(session_id)
            cached = await self._cached(session_id)
            if (
                cached is not None
                and cached.get("through_sequence") == session.last_sequence
            ):
                agents = self._validated_agents(cached.get("agents"))
                if agents is not None:
                    return agents

            through_sequence = int(cached.get("through_sequence", 0)) if cached else 0
            agents = self._validated_agents(cached.get("agents")) if cached else ()
            pending_calls = self._validated_call_ids(
                cached.get("pending_spawn_call_ids") if cached else None
            )
            if agents is None or pending_calls is None:
                through_sequence = 0
                agents = ()
                pending_calls = frozenset()
            events = await self.session_store.read_session_events(
                session_id, after_sequence=through_sequence
            )
            agents, pending_calls = self._project(
                events,
                initial_agents=agents,
                initial_spawn_calls=pending_calls,
            )
            await self.session_store.put_derived_state(
                session_id,
                self.NAMESPACE,
                self.KEY,
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "through_sequence": session.last_sequence,
                    "agents": [value.model_dump(mode="json") for value in agents],
                    "pending_spawn_call_ids": sorted(pending_calls),
                },
            )
            return agents

    async def _cached(self, session_id: str) -> dict[str, Any] | None:
        try:
            value = await self.session_store.get_derived_state(
                session_id, self.NAMESPACE, self.KEY
            )
        except Exception:
            # Derived state is explicitly rebuildable. A broken projection must
            # not make the canonical Session unusable.
            try:
                await self.session_store.delete_derived_state(
                    session_id, self.NAMESPACE, self.KEY
                )
            except Exception:
                pass
            return None
        if not isinstance(value, dict):
            return None
        if value.get("schema_version") != self.SCHEMA_VERSION:
            return None
        return value

    @staticmethod
    def _validated_agents(value: Any) -> tuple[AgentDescriptor, ...] | None:
        if not isinstance(value, list):
            return None
        try:
            agents = tuple(AgentDescriptor.model_validate(item) for item in value)
        except (TypeError, ValueError):
            return None
        if any(not agent.dynamic for agent in agents):
            return None
        if len({agent.agent_id for agent in agents}) != len(agents):
            return None
        return tuple(sorted(agents, key=lambda agent: agent.agent_id))

    @staticmethod
    def _validated_call_ids(value: Any) -> frozenset[str] | None:
        if value is None:
            return frozenset()
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return None
        return frozenset(value)

    @classmethod
    def _project(
        cls,
        events,
        *,
        initial_agents: tuple[AgentDescriptor, ...] = (),
        initial_spawn_calls: frozenset[str] = frozenset(),
    ) -> tuple[tuple[AgentDescriptor, ...], frozenset[str]]:
        spawn_calls: set[str] = set(initial_spawn_calls)
        agents: dict[str, AgentDescriptor] = {
            value.agent_id: value for value in initial_agents
        }
        for event in events:
            data = getattr(event, "data", None)
            item = getattr(data, "item", None)
            if item is None or item.status != ItemStatus.COMPLETED:
                continue
            if isinstance(item.data, ToolCallItemData):
                if item.data.tool_name == "sys_spawn_agent":
                    spawn_calls.add(item.data.tool_call_id)
                continue
            if not isinstance(item.data, ToolResultItemData):
                continue
            if item.data.tool_call_id not in spawn_calls or item.data.error is not None:
                continue
            descriptor = cls._descriptor_from_blocks(item.data.content)
            if descriptor is not None:
                agents[descriptor.agent_id] = descriptor
            spawn_calls.discard(item.data.tool_call_id)
        return (
            tuple(agents[key] for key in sorted(agents)),
            frozenset(spawn_calls),
        )

    @staticmethod
    def _descriptor_from_blocks(blocks) -> AgentDescriptor | None:
        for block in blocks:
            if not isinstance(block, JsonBlock) or not isinstance(block.value, dict):
                continue
            try:
                descriptor = AgentDescriptor.model_validate(block.value)
            except (TypeError, ValueError):
                continue
            if descriptor.dynamic:
                return descriptor
        return None

    @asynccontextmanager
    async def _session_lock(self, session_id: str):
        async with self._locks_guard:
            entry = self._locks.get(session_id)
            if entry is None:
                entry = _RosterLockEntry(asyncio.Lock())
                self._locks[session_id] = entry
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._locks.get(session_id) is entry:
                    self._locks.pop(session_id, None)
