"""V2-native Fibre and Team Tool plugin backed by child Sessions and Runs."""

from __future__ import annotations

from typing import Any

from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentMode,
    DelegationBatch,
    DelegationTask,
)
from sagents.v2.agent.multi_agent.coordinator import MultiAgentCoordinator
from sagents.v2.contracts.common import new_id
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.tool import DecoratedToolProvider, ToolInvocation, tool


class MultiAgentToolPlugin:
    """Mode-scoped decorated Tools backed only by V2 coordination contracts."""

    descriptor = ExtensionDescriptor(
        plugin_id="sage.tool.multi-agent",
        version="2.0.0",
        name="Multi-agent Tool provider",
        description="V2-native Fibre and Team delegation tools.",
        provides=(
            CapabilityOffer(
                capability="tool.catalog", api_version="2", name="multi-agent"
            ),
            CapabilityOffer(
                capability="tool.executor", api_version="2", name="multi-agent"
            ),
        ),
        supported_scopes=frozenset({ExtensionScope.AGENT, ExtensionScope.RUN}),
        config_schema={
            "type": "object",
            "properties": {"coordinator": {}, "runtime": {}},
            "required": ["coordinator", "runtime"],
        },
        capabilities={
            "decorated_tools": True,
            "mode_scoped": True,
            "v2_native": True,
        },
        built_in=True,
    )

    def __init__(
        self,
        *,
        coordinator: MultiAgentCoordinator,
        runtime: HarnessRuntime,
    ) -> None:
        owner = (
            _FibreToolMethods(coordinator, runtime)
            if coordinator.mode == AgentMode.FIBRE
            else _TeamToolMethods(coordinator, runtime)
        )
        provider = DecoratedToolProvider(owner)
        self.catalog = provider
        self.executor = provider
        self.definitions = provider.definitions


class _DelegationMethods:
    def __init__(
        self, coordinator: MultiAgentCoordinator, runtime: HarnessRuntime
    ) -> None:
        self.coordinator = coordinator
        self.runtime = runtime

    async def _delegate(
        self,
        tasks: list[dict[str, Any]],
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        parent = await self.runtime.get_run(invocation.call.owner_run_id)
        values = tuple(
            DelegationTask(
                task_id=str(
                    value.get("task_name")
                    or f"{invocation.call.tool_call_id}_{index}"
                ),
                agent_id=value["agent_id"],
                task_name=value["task_name"],
                original_task=value["original_task"],
                content=value["content"],
                child_session_id=value.get("session_id") or None,
            )
            for index, value in enumerate(tasks, start=1)
        )
        results = await self.coordinator.delegate(
            DelegationBatch(tasks=values),
            parent_run_id=invocation.call.owner_run_id,
            parent_session_id=parent.session_id,
            context=invocation.request_context,
        )
        return {
            "results": [value.model_dump(mode="json") for value in results],
            "child_run_ids": [value.child_run_id for value in results],
        }


class _FibreToolMethods(_DelegationMethods):
    @tool(
        description=(
            "Create a new general-purpose expert sub-agent. The system_prompt "
            "defines persona and capabilities, not a one-off task."
        )
    )
    async def sys_spawn_agent(
        self,
        name: str,
        description: str,
        system_prompt: str,
        session_id: str = "",
    ) -> dict[str, Any]:
        del session_id
        descriptor = await self.coordinator.spawn(
            AgentDescriptor(
                agent_id=new_id("agent"),
                name=name,
                description=description,
                instructions=system_prompt,
                mode=AgentMode.SIMPLE,
                dynamic=True,
            )
        )
        return descriptor.model_dump(mode="json")

    @tool(description="Delegate concrete tasks to existing sub-agents concurrently.")
    async def sys_delegate_task(
        self,
        tasks: list[dict[str, Any]],
        session_id: str = "",
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        if invocation is None:  # pragma: no cover - provider invariant
            raise RuntimeError("Tool invocation was not injected")
        return await self._delegate(tasks, invocation)


class _TeamToolMethods(_DelegationMethods):
    @tool(description="Delegate concrete tasks to existing Team members concurrently.")
    async def sys_team_delegate_task(
        self,
        tasks: list[dict[str, Any]],
        session_id: str = "",
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        if invocation is None:  # pragma: no cover - provider invariant
            raise RuntimeError("Tool invocation was not injected")
        return await self._delegate(tasks, invocation)
