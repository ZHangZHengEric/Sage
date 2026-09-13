"""Model-visible full AgentPackage lifecycle, separate from leaf delegation."""

from __future__ import annotations

from typing import Any

from sagents.v2.agent.management import AgentManagementService, AgentPackageBundle
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.tool.contracts import SideEffectLevel
from sagents.v2.tool.decorated import DecoratedToolProvider, ToolInvocation
from sagents.v2.tool.decorators import tool


def _context(invocation):
    if invocation is None:
        raise RuntimeError("ToolInvocation is required")
    return invocation.request_context


class AgentManagementTools:
    def __init__(self, service: AgentManagementService):
        self.service = service

    @tool(
        description="Inspect the complete agent package schema and host-provided plugin inventory.",
        plan_safe=True,
    )
    async def agent_package_schema(self) -> dict[str, Any]:
        return self.service.schema()

    @tool(
        description="List your persistent agent package versions; use exact refs for execution.",
        plan_safe=True,
    )
    async def agent_package_list(
        self, limit: int = 50, offset: int = 0, invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return {
            "packages": await self.service.list(
                _context(invocation), limit=limit, offset=offset
            )
        }

    @tool(
        description="Read a complete package and its files to inspect, edit or fork it.",
        plan_safe=True,
    )
    async def agent_package_get(
        self, ref: str, invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return (await self.service.get(ref, _context(invocation))).model_dump(
            mode="json"
        )

    @tool(
        description="Validate full agent settings, references and provider initialization. Does not run tasks.",
        side_effect_level=SideEffectLevel.REVERSIBLE,
    )
    async def agent_package_validate(
        self, bundle: dict[str, Any], readiness: bool = False, invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return await self.service.validate(
            AgentPackageBundle.model_validate(bundle), _context(invocation), readiness=readiness
        )

    @tool(
        description="Create or revise agents using the complete package schema. Supply a new version for edits; saved versions are immutable. Identical retries reuse the saved version; use validate to probe current providers again. Returns a saved ref; use validate(readiness=true) to check declared resource availability.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_save(
        self, bundle: dict[str, Any], invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return await self.service.save(
            AgentPackageBundle.model_validate(bundle), _context(invocation)
        )

    @tool(
        description="Fork an existing full package under another id/version. Read and save a new version to customize every setting.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_fork(
        self,
        ref: str,
        package_id: str,
        version: str,
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        return await self.service.fork(ref, package_id, version, _context(invocation))

    @tool(
        description="Select an existing package version as active, or roll back. expected_ref is the current active ref, empty for first activation. This is not a quality certification.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_activate(
        self, ref: str, expected_ref: str = "", invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return await self.service.activate(
            ref, expected_ref or None, _context(invocation)
        )

    @tool(
        description="Start a task on an exact package ref and agent_id. Returns immediately; read agent_package_status for results. Reuse operation for retries only. session_id continues the same agent/version conversation.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_run(
        self,
        ref: str,
        agent_id: str,
        content: str,
        operation: str,
        session_id: str = "",
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        return await self.service.run(
            ref,
            agent_id,
            content,
            operation,
            _context(invocation),
            session_id=session_id or None,
        )

    @tool(
        description="Read a managed task's state and result by operation key, including whether it needs attention.",
        plan_safe=True,
    )
    async def agent_package_status(
        self, operation: str, invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return await self.service.status(operation, _context(invocation))

    @tool(
        description="Answer a managed agent's pending user-input question using interaction_id from status. Retries must repeat the same ID and answer. Host approvals and credentials cannot be answered here.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_reply(
        self,
        operation: str,
        decision: str,
        interaction_id: str,
        payload: dict[str, Any],
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        return await self.service.control(
            operation,
            "reply",
            _context(invocation),
            decision=decision,
            payload=payload,
            interaction_id=interaction_id,
        )

    @tool(
        description="Cancel a managed task by its operation key.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def agent_package_cancel(
        self, operation: str, invocation: ToolInvocation | None = None
    ) -> dict[str, Any]:
        return await self.service.control(operation, "cancel", _context(invocation))


class AgentManagementToolPlugin:
    plugin_id = "sage.tool.agent-management"
    name = "Agent package management"
    description = (
        "Host-authorized full-package agent creation, versioning and execution."
    )
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
        provides=(
            CapabilityOffer(
                capability="tool.catalog", api_version="2", name="agent-management"
            ),
            CapabilityOffer(
                capability="tool.executor", api_version="2", name="agent-management"
            ),
        ),
        supported_scopes=frozenset({ExtensionScope.PROCESS}),
        config_schema={
            "type": "object",
            "properties": {"service": {}},
            "required": ["service"],
            "additionalProperties": False,
        },
    )

    def __init__(self, service: AgentManagementService):
        provider = DecoratedToolProvider(AgentManagementTools(service))
        self.catalog, self.executor = provider.catalog, provider.executor
        self.definitions = provider.definitions

    def provide(self):
        return {
            "tool.catalog:agent-management": self.catalog,
            "tool.executor:agent-management": self.executor,
        }
