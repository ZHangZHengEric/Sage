"""SAgents V2 module for agent/multi_agent/registry.py."""

from __future__ import annotations

import asyncio

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.agent.multi_agent.contracts import AgentDescriptor, AgentMode


class AgentRegistry:
    def __init__(self, agents: tuple[AgentDescriptor, ...] = ()) -> None:
        self._lock = asyncio.Lock()
        self._agents = {agent.agent_id: agent for agent in agents}
        if len(self._agents) != len(agents):
            raise ValueError("agent IDs must be unique")

    async def list(self) -> tuple[AgentDescriptor, ...]:
        async with self._lock:
            return tuple(self._agents[key] for key in sorted(self._agents))

    async def get(self, agent_id: str) -> AgentDescriptor:
        async with self._lock:
            value = self._agents.get(agent_id)
        if value is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"agent {agent_id!r} is not registered",
                    safe_to_resume=True,
                )
            )
        return value

    async def spawn(
        self,
        descriptor: AgentDescriptor,
        *,
        owner_mode: AgentMode,
    ) -> AgentDescriptor:
        if owner_mode != AgentMode.FIBRE:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.spawn_not_allowed",
                    category=ErrorCategory.POLICY_DENIED,
                    message="only Fibre mode can create dynamic agents",
                    safe_to_resume=True,
                )
            )
        if descriptor.mode == AgentMode.FLOW:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.dynamic_flow_not_allowed",
                    category=ErrorCategory.POLICY_DENIED,
                    message="dynamic agents cannot introduce undeclared flows",
                    safe_to_resume=True,
                )
            )
        value = descriptor.model_copy(update={"dynamic": True})
        async with self._lock:
            if value.agent_id in self._agents:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="agent.duplicate_id",
                        category=ErrorCategory.CONFLICT,
                        message=f"agent {value.agent_id!r} already exists",
                    )
                )
            self._agents[value.agent_id] = value
        return value
