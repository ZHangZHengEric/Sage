"""Official Flow-node registrations."""

from __future__ import annotations

from sagents.v2.agent.multi_agent.contracts import (
    AgentDescriptor,
    WorkspaceSharingPolicy,
)
from sagents.v2.flow.plugins.agent import NativeAgentFlowNode
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import implementation_identity
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_flow_plugins(registry: ExtensionRegistry) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(NativeAgentFlowNode),
                dependencies=(
                    ExtensionDependency(capability="runtime.kernel"),
                    ExtensionDependency(capability="agent.child-executor"),
                ),
                version="2.0.0",
                provides=(
                    CapabilityOffer(
                        capability="flow.node", api_version="2", name="agent"
                    ),
                ),
                supported_scopes=frozenset({ExtensionScope.RUN}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "descriptor": {"type": "object"},
                        "workspace_policy": {
                            "type": "string",
                            "enum": [
                                "private_child",
                                "shared_parent",
                                "read_only_parent",
                            ],
                        },
                    },
                    "required": ["descriptor"],
                    "additionalProperties": False,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: NativeAgentFlowNode(
                runtime=dependencies.require_unique("runtime.kernel"),
                descriptor=AgentDescriptor.model_validate(context.config["descriptor"]),
                child_executor=dependencies.require_unique("agent.child-executor"),
                workspace_policy=WorkspaceSharingPolicy(
                    context.config.get("workspace_policy", "shared_parent")
                ),
            ),
        )
    )
