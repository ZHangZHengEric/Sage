"""Official extension registrations used by SAgentBuilder.with_defaults()."""

from __future__ import annotations

from sagents.v2.memory.plugins.noop import NoopMemoryProvider
from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.memory.query import (
    DirectMemoryRecallQueryGenerator,
    LLMMemoryRecallQueryGenerator,
)
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    model_protocol_descriptors,
)
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.runtime.session import EphemeralSessionStore, FilesystemSessionStore
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.official.delegation import MultiAgentToolPlugin
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.flow.plugins.agent import NativeAgentFlowNode
from sagents.v2.runtime.extensions.official import register_official_infrastructure


def builtin_extension_registry() -> ExtensionRegistry:
    """Return a fresh registry whose inventory is backed by real factories."""

    registry = ExtensionRegistry()
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.session.filesystem",
                version="2.1.0",
                name="Filesystem SessionStore",
                description="Compact authoritative checksummed state per Session.",
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string", "minLength": 1},
                    },
                    "required": ["root"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: FilesystemSessionStore(
                context.config["root"],
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.memory.recall-query.direct",
                version="2.0.0",
                name="Direct user input",
                description=(
                    "Uses the current user input as the search_memory query without "
                    "an additional model request."
                ),
                provides=(
                    CapabilityOffer(
                        capability="memory.recall-query", api_version="2"
                    ),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
                ),
                capabilities={"uses_model": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: DirectMemoryRecallQueryGenerator(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.memory.recall-query.llm",
                version="2.0.0",
                name="LLM-generated keywords",
                description=(
                    "Uses a fast model to generate compact keywords before calling "
                    "search_memory."
                ),
                provides=(
                    CapabilityOffer(
                        capability="memory.recall-query", api_version="2"
                    ),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.AGENT, ExtensionScope.RUN}
                ),
                config_schema={
                    "type": "object",
                    "properties": {
                        "model": {},
                        "language": {"type": "string"},
                    },
                    "required": ["model"],
                    "additionalProperties": False,
                },
                capabilities={"uses_model": True},
                built_in=True,
            ),
            factory=lambda context, dependencies: LLMMemoryRecallQueryGenerator(
                context.config["model"],
                language=str(context.config.get("language") or "en"),
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.session.ephemeral",
                version="2.0.0",
                name="Ephemeral SessionStore",
                description="Full lifecycle semantics without restart durability.",
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                capabilities={"durable": False, "testing": True},
                built_in=True,
            ),
            factory=lambda context, dependencies: EphemeralSessionStore(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.memory.noop",
                version="2.0.0",
                name="No-op Memory",
                description="Disables long-term Memory without changing Agent logic.",
                provides=(
                    CapabilityOffer(capability="memory.provider", api_version="2"),
                ),
                supported_scopes=frozenset(
                    {
                        ExtensionScope.PROCESS,
                        ExtensionScope.TENANT,
                        ExtensionScope.AGENT,
                    }
                ),
                capabilities={"durable": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: NoopMemoryProvider(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.memory.filesystem-bm25",
                version="2.1.0",
                name="Filesystem BM25 Memory",
                description="Durable scoped Memory records with incremental SQLite FTS5 BM25 recall.",
                provides=(
                    CapabilityOffer(capability="memory.provider", api_version="2"),
                ),
                supported_scopes=frozenset(
                    {
                        ExtensionScope.PROCESS,
                        ExtensionScope.TENANT,
                        ExtensionScope.AGENT,
                    }
                ),
                config_schema={
                    "type": "object",
                    "properties": {"root": {"type": "string", "minLength": 1}},
                    "required": ["root"],
                },
                capabilities={
                    "durable": True,
                    "retrieval": "bm25",
                    "storage": "sqlite-fts5",
                    "incremental_index": True,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: FilesystemBm25MemoryProvider(
                context.config["root"]
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=OfficialToolPlugin.descriptor,
            factory=lambda context, dependencies: OfficialToolPlugin(context),
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
                context.config["loader"], language=context.config.get("language")
            ),
            start=lambda plugin, context, dependencies: {
                "tool.catalog:skill": plugin.catalog,
                "tool.executor:skill": plugin.executor,
            },
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=MultiAgentToolPlugin.descriptor,
            factory=lambda context, dependencies: MultiAgentToolPlugin(
                coordinator=context.config["coordinator"],
                runtime=context.config["runtime"],
            ),
            start=lambda plugin, context, dependencies: {
                "tool.catalog:multi-agent": plugin.catalog,
                "tool.executor:multi-agent": plugin.executor,
            },
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.skill.filesystem",
                version="2.0.0",
                name="Filesystem Skill provider",
                description="Lazy, bounded, symlink-safe Skill catalog and source.",
                provides=(
                    CapabilityOffer(
                        capability="skill.catalog", api_version="2", name="filesystem"
                    ),
                    CapabilityOffer(
                        capability="skill.source", api_version="2", name="filesystem"
                    ),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT}
                ),
                config_schema={
                    "type": "object",
                    "properties": {
                        "roots": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["roots"],
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: FilesystemSkillProvider(
                tuple(context.config["roots"])
            ),
            start=lambda provider, context, dependencies: {
                "skill.catalog:filesystem": provider,
                "skill.source:filesystem": provider,
            },
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.flow.agent",
                version="2.0.0",
                name="Agent Flow node",
                description="Runs a child Agent through the shared AgentLoopEngine.",
                provides=(
                    CapabilityOffer(
                        capability="flow.node", api_version="2", name="agent"
                    ),
                ),
                supported_scopes=frozenset({ExtensionScope.RUN}),
                built_in=True,
            ),
            factory=lambda context, dependencies: NativeAgentFlowNode(**context.config),
        )
    )
    register_official_infrastructure(registry)
    for descriptor in model_protocol_descriptors():
        plugin_id = f"sage.model.{descriptor.protocol.value}"
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    plugin_id=plugin_id,
                    version="2.0.0",
                    name=descriptor.name,
                    description=descriptor.value,
                    provides=(
                        CapabilityOffer(
                            capability="model.provider",
                            api_version="2",
                            name=descriptor.protocol.value,
                        ),
                    ),
                    supported_scopes=frozenset(
                        {ExtensionScope.AGENT, ExtensionScope.RUN}
                    ),
                    config_schema={
                        "type": "object",
                        "properties": {"route": {"type": "object"}},
                        "required": ["route"],
                    },
                    capabilities={"protocol": descriptor.protocol.value},
                    built_in=True,
                ),
                factory=_model_factory,
            )
        )
    return registry


def _model_factory(context, dependencies):
    route = ModelRoute.model_validate(context.config["route"])
    credential_data = context.config.get("credential")
    credential = (
        credential_data
        if isinstance(credential_data, CredentialMaterial)
        else CredentialMaterial.model_validate(credential_data)
        if credential_data is not None
        else None
    )
    return create_registered_model_provider(
        route,
        credential,
        client=context.config.get("client"),
        provider_instance_id=context.config.get("provider_instance_id"),
    )
