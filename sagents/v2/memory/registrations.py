"""Official long-term memory and recall-query registrations."""

from __future__ import annotations

from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.memory.plugins.noop import NoopMemoryProvider
from sagents.v2.memory.plugins.recall_direct import DirectMemoryRecallQueryGenerator
from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import (
    empty_config_schema,
    implementation_identity,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


def register_memory_plugins(registry: ExtensionRegistry) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(DirectMemoryRecallQueryGenerator),
                version="2.0.0",
                provides=(
                    CapabilityOffer(capability="memory.recall-query", api_version="2"),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
                ),
                config_schema=empty_config_schema(),
                capabilities={"uses_model": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: DirectMemoryRecallQueryGenerator(),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(LLMMemoryRecallQueryGenerator),
                dependencies=(ExtensionDependency(capability="model.provider"),),
                version="2.0.0",
                provides=(
                    CapabilityOffer(capability="memory.recall-query", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.AGENT, ExtensionScope.RUN}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "language": {"type": "string"},
                        "timeout_seconds": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                        },
                    },
                    "additionalProperties": False,
                },
                capabilities={"uses_model": True},
                built_in=True,
            ),
            factory=lambda context, dependencies: LLMMemoryRecallQueryGenerator(
                dependencies.require_unique("model.provider"),
                language=str(context.config.get("language") or "en"),
                timeout_seconds=float(
                    context.config.get(
                        "timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                    )
                ),
            ),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(NoopMemoryProvider),
                version="2.0.0",
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
                config_schema=empty_config_schema(),
                capabilities={"durable": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: NoopMemoryProvider(),
        )
    )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **implementation_identity(FilesystemBm25MemoryProvider),
                version="2.1.0",
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
                    "additionalProperties": False,
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
