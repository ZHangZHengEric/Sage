"""Official tool providers, selection policies and Run runtime registration."""

from __future__ import annotations

from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import (
    implementation_identity,
    register_plugin,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.plugins.delegation import MultiAgentToolPlugin
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.selection_direct import DirectToolSelectionPolicy
from sagents.v2.tool.plugins.selection_lexical import LexicalToolSelectionPolicy
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.tool.provider import ToolProvider


def tool_runtime_registration():
    from sagents.v2.runtime.artifact.binding import bind_artifact_store
    from sagents.v2.runtime.extensions.contracts import (
        CapabilityOffer,
        ExtensionDependency,
        ExtensionDescriptor,
        ExtensionRegistration,
        ExtensionScope,
    )
    from sagents.v2.tool.official import OfficialToolRuntime

    def create(context, dependencies):
        environment = dependencies.require("execution.environment")
        if environment.sandbox is None or environment.grant_issuer is None:
            raise RuntimeError(
                "official tools require a Run-owned execution.binding sandbox"
            )
        runtime = OfficialToolRuntime(
            environment.sandbox,
            environment.grant_issuer,
            job_runtime=dependencies.require("execution.job-runtime"),
        )
        runtime.artifact_store = bind_artifact_store(
            dependencies.require("artifact.store"), environment.run_id
        )
        runtime.memory_service = environment.memory_service
        runtime.session_memory_service = environment.session_memory_service
        runtime.goal_state_service = environment.goal_state_service
        runtime.tool_selection_policy = dependencies.require("tool.selection-policy")
        runtime.bind_job_runtime(dependencies.require("execution.job-runtime"))
        return runtime

    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=OfficialToolRuntime.plugin_id,
            name="Run tool environment",
            version="2.0.0",
            description="Official tools bound to the accepted Run sandbox and shared services.",
            provides=(
                CapabilityOffer(capability="execution.tool-runtime", api_version="2"),
            ),
            dependencies=tuple(
                ExtensionDependency(capability=capability)
                for capability in (
                    "execution.environment",
                    "execution.job-runtime",
                    "artifact.store",
                    "tool.selection-policy",
                )
            ),
            supported_scopes=frozenset({ExtensionScope.RUN}),
            default_scope=ExtensionScope.RUN,
            config_schema={"type": "object", "additionalProperties": False},
            built_in=True,
        ),
        factory=create,
    )


def register_tool_plugins(registry: ExtensionRegistry) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=EphemeralToolPlugin.descriptor,
            factory=lambda context, dependencies: EphemeralToolPlugin(
                tools=tuple(
                    ToolDefinition.model_validate(item)
                    for item in context.config.get("tools", ())
                ),
                handlers=dependencies.get_provider("tool.handlers"),
            ),
            start=lambda plugin, context, dependencies: {
                "tool.provider:ephemeral": ToolProvider(
                    plugin.catalog, plugin.executor
                ),
            },
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=OfficialToolPlugin.descriptor,
            factory=lambda context, dependencies: OfficialToolPlugin(
                dependencies.require("execution.tool-runtime")
            ),
            start=lambda plugin, context, dependencies: plugin.start(
                context, dependencies
            ),
            stop=lambda plugin, reason: plugin.stop(reason),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=SkillToolPlugin.descriptor,
            factory=lambda context, dependencies: SkillToolPlugin(
                dependencies.require_unique("skill.loader"),
                language=context.config.get("language"),
                allow_editing=context.config.get("allow_editing", False),
            ),
            start=lambda plugin, context, dependencies: {
                "tool.provider:skill": ToolProvider(plugin.catalog, plugin.executor),
            },
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=MultiAgentToolPlugin.descriptor,
            factory=lambda context, dependencies: MultiAgentToolPlugin(
                coordinator=dependencies.require_unique("agent.coordinator"),
                runtime=dependencies.require_unique("runtime.kernel"),
            ),
            start=lambda plugin, context, dependencies: {
                "tool.provider:multi-agent": ToolProvider(
                    plugin.catalog, plugin.executor
                ),
            },
        )
    )

    from sagents.v2.tool.plugins.result_file import FileToolResultProcessor

    register_plugin(
        registry,
        FileToolResultProcessor,
        "tool.result-processor",
        lambda context, dependencies: FileToolResultProcessor(**context.config),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"max_inline_characters": {"type": "integer", "minimum": 1}},
        },
    )

    bounded_config_schema = {
        "type": "object",
        "properties": {
            "max_visible_tools": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10_000,
                "default": 24,
                "title": "Tool count limit",
                "description": "Maximum number of full Tool schemas sent to the model.",
            },
            "model_timeout_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 120,
                "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                "title": "Auxiliary model timeout",
                "description": (
                    "Maximum wait before model-assisted selection reports an error."
                ),
            },
        },
        "additionalProperties": False,
    }

    for implementation, uses_model in (
        (DirectToolSelectionPolicy, False),
        (LLMToolSelectionPolicy, True),
        (LexicalToolSelectionPolicy, False),
        (RecentToolSelectionPolicy, False),
    ):
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    **implementation_identity(implementation),
                    version="2.0.0",
                    provides=(
                        CapabilityOffer(
                            capability="tool.selection-policy", api_version="2"
                        ),
                    ),
                    supported_scopes=frozenset(
                        {ExtensionScope.AGENT, ExtensionScope.RUN}
                    ),
                    config_schema=(
                        {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        }
                        if implementation is DirectToolSelectionPolicy
                        else bounded_config_schema
                    ),
                    capabilities={
                        "bounded_catalog": implementation
                        is not DirectToolSelectionPolicy,
                        "supports_expansion": True,
                        "uses_model": uses_model,
                    },
                    built_in=True,
                ),
                factory=lambda context, dependencies, implementation=implementation: (
                    implementation(context.config)
                ),
            )
        )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(McpToolPlugin),
                dependencies=(
                    ExtensionDependency(
                        capability="mcp.session-factory", name="default", optional=True
                    ),
                ),
                version="2.0.0",
                provides=(
                    CapabilityOffer(
                        capability="tool.provider", api_version="2", name="mcp"
                    ),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
                ),
                config_schema={
                    "type": "object",
                    "properties": {
                        "servers": {
                            "type": "array",
                            "items": McpServerConfig.model_json_schema(),
                        },
                    },
                    "additionalProperties": False,
                },
                capabilities={
                    "durable_operation_ledger": False,
                    "supports_restart_reconciliation": False,
                    "protocol_exactly_once": False,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: McpToolPlugin(
                tuple(
                    McpServerConfig.model_validate(value)
                    for value in context.config.get("servers", ())
                ),
                session_factory=dependencies.get_provider("mcp.session-factory"),
            ),
            start=lambda provider, context, dependencies: {
                "tool.provider:mcp": ToolProvider(provider, provider),
            },
        )
    )

    registry.register(tool_runtime_registration())
