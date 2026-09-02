"""V2-native Fibre and Team Tool plugin backed by child Sessions and Runs."""

from __future__ import annotations

from typing import Any

from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    AgentInvocationMode,
    AgentMode,
    DelegationBatch,
    DelegationTask,
)
from sagents.v2.agent.multi_agent.coordinator import MultiAgentCoordinator
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.contracts.items import JsonBlock
from sagents.v2.tool import (
    DecoratedToolProvider,
    ToolExecutionResult,
    ToolInvocation,
    tool,
)


_DELEGATION_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "description": (
                "Concrete tasks to run concurrently. Use one object per sub-agent task."
            ),
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Exact target agent ID returned by sys_spawn_agent or "
                            "listed in multi_agent_mode."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Detailed concrete task for the child agent.",
                    },
                    "task_name": {
                        "type": "string",
                        "description": (
                            "Optional short task name. A stable name is generated when omitted."
                        ),
                    },
                    "original_task": {
                        "type": "string",
                        "description": (
                            "Optional original user request for additional context. "
                            "Defaults to content when omitted."
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Optional existing child session ID to continue. Omit for a new task; "
                            "never pass the current parent session ID."
                        ),
                    },
                },
                "required": ["agent_id", "content"],
                "additionalProperties": False,
            },
        },
        "session_id": {
            "type": "string",
            "default": "",
            "description": "Current parent session ID; normally injected by the runtime.",
        },
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


class MultiAgentToolPlugin:
    """Mode-scoped decorated Tools backed only by V2 coordination contracts."""

    plugin_id = "sage.tool.multi-agent"
    name = "Multi-agent Tool provider"
    description = "V2-native Fibre and Team delegation tools."
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
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
        runtime: RuntimePort,
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
        self, coordinator: MultiAgentCoordinator, runtime: RuntimePort
    ) -> None:
        self.coordinator = coordinator
        self.runtime = runtime

    async def _assert_delegation_allowed(self, invocation: ToolInvocation):
        command = await self.runtime.session_store.get_start_command(
            invocation.call.owner_run_id
        )
        if (
            self.coordinator.mode == AgentMode.FIBRE
            and command.invocation_mode == AgentInvocationMode.DELEGATION.value
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.nested_delegation_not_allowed",
                    category=ErrorCategory.POLICY_DENIED,
                    message=(
                        "delegated Fibre child agents are leaf workers and cannot "
                        "spawn or delegate further agents; use a human-configured "
                        "Team hierarchy when nested delegation is required"
                    ),
                    safe_to_resume=True,
                )
            )
        return command

    async def _delegate(
        self,
        tasks: list[dict[str, Any]],
        invocation: ToolInvocation,
    ) -> dict[str, Any] | ToolExecutionResult:
        await self._assert_delegation_allowed(invocation)
        parent = await self.runtime.get_run(invocation.call.owner_run_id)
        values = tuple(
            DelegationTask(
                task_id=f"{invocation.call.tool_call_id[:180]}_{index}",
                agent_id=value["agent_id"],
                task_name=str(value.get("task_name") or f"Delegated task {index}"),
                original_task=str(value.get("original_task") or value["content"]),
                content=value["content"],
                parent_tool_call_id=invocation.call.tool_call_id,
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
        payload = {
            "results": [value.model_dump(mode="json") for value in results],
            "child_run_ids": [value.child_run_id for value in results],
        }
        pending = []
        interaction_reader = getattr(
            self.coordinator.executor, "pending_interaction", None
        )
        for value in results:
            if (
                value.outcome.value != "suspended"
                or value.child_run_id is None
                or interaction_reader is None
            ):
                continue
            interaction = await interaction_reader(value.child_run_id)
            if interaction is not None:
                pending.append(
                    {
                        "agent_id": value.agent_id,
                        "child_run_id": value.child_run_id,
                        "interaction": interaction,
                    }
                )
        if not pending:
            return payload
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(JsonBlock(value=payload),),
            metadata={"delegation_interactions": pending},
        )


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
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        if invocation is None:  # pragma: no cover - provider invariant
            raise RuntimeError("Tool invocation was not injected")
        command = await self._assert_delegation_allowed(invocation)
        descriptor = await self.coordinator.spawn(
            AgentDescriptor(
                agent_id=new_id("agent"),
                name=name,
                description=description,
                instructions=system_prompt,
                mode=AgentMode.SIMPLE,
                # Match v1 Fibre: a dynamically spawned expert inherits the
                # parent's narrowed Tool/Skill grant. Without this, a coding
                # child is created with an empty Tool catalog and can only
                # describe work instead of reading, writing, or testing it.
                tools=command.config.enabled_tools or (),
                skills=command.config.enabled_skills or (),
                dynamic=True,
            )
        )
        return descriptor.model_dump(mode="json")

    @tool(
        description="Delegate concrete tasks to existing sub-agents concurrently.",
        input_schema=_DELEGATION_INPUT_SCHEMA,
    )
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
    @tool(
        description="Delegate concrete tasks to existing Team members concurrently.",
        input_schema=_DELEGATION_INPUT_SCHEMA,
    )
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
