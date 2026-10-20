"""Single inventory of first-party plugin registrations.

Implementation classes remain in their owning domains. This module only binds
stable plugin IDs to factories so every host-selectable implementation appears
in one ExtensionRegistry. Call ``builtin_extension_registry()`` for a fresh
inventory.
"""

from __future__ import annotations

import importlib.util
import inspect
import os

from sagents.v2.agent.policy import (
    BudgetRule,
    CompositeContinuationPolicy,
    ExplicitStatusContinuationPolicy,
    ExplicitStatusRule,
    FlowBoundaryRule,
    LoopRecoveryRule,
    HybridContinuationPolicy,
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
    ToolOrTextRule,
)
from sagents.v2.context import (
    ExtractiveConversationSummarizer,
    InMemoryConversationSummaryStore,
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
    SessionDerivedConversationSummaryStore,
    WindowContextReducer,
)
from sagents.v2.context.plugins.summarizer_model import (
    DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS,
)
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.interfaces.protocols.acp import AcpProtocolAdapter
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.interfaces.protocols.mcp import McpProtocolAdapter
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter
from sagents.v2.package.registry import InMemoryAgentPackageRegistry
from sagents.v2.runtime.artifact import InMemoryArtifactStore
from sagents.v2.runtime.artifact import FilesystemArtifactStore, SessionArtifactStore
from sagents.v2.runtime.credentials import (
    EnvironmentCredentialProvider,
    MappingCredentialProvider,
)
from sagents.v2.runtime.execution.dispatcher import DEFAULT_LEASE_SECONDS
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.sandbox import (
    CubeVolumeSandboxProvider,
    InMemorySandboxProvider,
    LocalWorkspaceSandboxProvider,
)
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
)
from sagents.v2.runtime.observability import (
    FilesystemDiagnosticSink,
    FilesystemLogSink,
    NoopDiagnosticSink,
    NoopLogSink,
    NoopTraceSink,
    OtlpTraceSink,
    LangfuseTraceSink,
    langfuse_available,
    PhoenixTraceSink,
    phoenix_available,
    StdoutLogSink,
    otel_available,
)
from sagents.v2.session_memory import (
    NoopSessionMemoryProvider,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionAvailability,
    ExtensionDescriptor,
    ExtensionDependency,
    ExtensionRegistration,
    ExtensionScope,
    plugin_identity,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.plugins.selection_direct import DirectToolSelectionPolicy
from sagents.v2.tool.plugins.selection_lexical import LexicalToolSelectionPolicy
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy
from sagents.v2.workspace import (
    BareWorkspaceInitializer,
    ClawWorkspaceInitializer,
)
from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.memory.plugins.noop import NoopMemoryProvider
from sagents.v2.model.provider import DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
from sagents.v2.memory.plugins.recall_direct import DirectMemoryRecallQueryGenerator
from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    model_protocol_descriptors,
    model_protocol_implementation,
)
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.package.manifest.credentials import CredentialDeclaration
from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    FilesystemSessionStore,
    MysqlSessionStore,
    RedisMysqlSessionStore,
)
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.skill.plugins.loading import SkillLoadingConfig, SkillLoadingPlugin
from sagents.v2.tool.plugins.delegation import MultiAgentToolPlugin
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.flow.plugins.agent import NativeAgentFlowNode
from sagents.v2.agent.multi_agent.contracts import AgentDescriptor, WorkspaceSharingPolicy


def builtin_extension_registry() -> ExtensionRegistry:
    """Return a fresh registry whose inventory is backed by real factories."""

    registry = ExtensionRegistry()
    register_official_plugins(registry)
    return registry


def register_official_plugins(registry: ExtensionRegistry) -> None:
    """Register every first-party host-selectable plugin."""

    existing = {value.descriptor.plugin_id for value in registry.registrations()}
    from sagents.v2.runtime.execution.plugins.local_binding.registration import local_execution_binding_registration
    registry.register(local_execution_binding_registration())
    from sagents.v2.runtime.execution.plugins.ephemeral_binding import ephemeral_execution_binding_registration
    registry.register(ephemeral_execution_binding_registration())
    from sagents.v2.runtime.execution.environment import (
        run_environment_registration,
        tool_runtime_registration,
    )
    registry.register(run_environment_registration())
    registry.register(tool_runtime_registration())
    from sagents.v2.runtime.extensions.core import core_registrations
    for registration in core_registrations():
        registry.register(registration)
    _register_session_and_memory(registry)
    _register_distributed_runtime(registry)
    _register_tools_skills_and_flow(registry)
    _register_infrastructure(registry)
    _register_distributed_jobs(registry)
    _register_model_protocols(registry)
    added = {
        value.descriptor.plugin_id for value in registry.registrations()
    }.difference(existing)
    registry.trust_builtins(added)


def _register_distributed_runtime(registry):
    from sagents.v2.runtime.execution.scheduler import RedisDistributedScheduler

    scheduler_schema = _scheduler_config_schema(durable=False)
    scheduler_schema["properties"].update({
        "redis_url": {"type": "string", "minLength": 1},
        "key_prefix": {"type": "string", "minLength": 1},
        "queue_id": {"type": "string", "minLength": 1},
        "coordination_ttl_seconds": {"type": "number", "exclusiveMinimum": 0},
        "poll_seconds": {"type": "number", "exclusiveMinimum": 0},
    })
    scheduler_schema["properties"]["lease_seconds"]["default"] = 30
    scheduler_schema["required"] = ["redis_url"]
    _one(registry, RedisDistributedScheduler, "execution.scheduler",
        lambda context, dependencies: RedisDistributedScheduler(**{key: value for key, value in context.config.items()
            if key not in {"lease_seconds", "preserve_runs_on_shutdown"}}),
        scopes={ExtensionScope.PROCESS}, config_schema=scheduler_schema,
        availability=ExtensionAvailability(available=importlib.util.find_spec("redis") is not None,
            reason=None if importlib.util.find_spec("redis") is not None else "optional redis package is required"),
        capabilities={"durable_across_process_restart": True, "multi_process_writes": True,
            "supports_distributed_claims": True, "supports_leases": True, "supports_fencing": True,
            "supports_atomic_tenant_quota": True, "supports_atomic_fenced_mutations": True})


def _register_distributed_jobs(registry):
    from copy import deepcopy
    from sagents.v2.runtime.execution.jobs import RedisDistributedJobRuntime
    original = registry.get(InMemoryJobRuntime.plugin_id).descriptor
    schema = deepcopy(original.config_schema)
    schema["properties"].update({
        "redis_url": {"type": "string", "minLength": 1},
        "key_prefix": {"type": "string", "minLength": 1},
        "lease_seconds": {"type": "number", "exclusiveMinimum": 0},
        "poll_interval_seconds": {"type": "number", "exclusiveMinimum": 0},
    })
    schema["required"] = ["redis_url"]
    registry.register(ExtensionRegistration(
        descriptor=original.model_copy(update={**_identity(RedisDistributedJobRuntime),
            "availability": ExtensionAvailability(available=importlib.util.find_spec("redis") is not None,
                reason=None if importlib.util.find_spec("redis") is not None else "optional redis package is required"),
            "config_schema": schema, "capabilities": {**original.capabilities,
                "durable_across_process_restart": True, "multi_process_writes": True,
                "supports_reconnect": True, "supports_remote_cancel": True, "supports_adoption": False}}),
        factory=lambda context, dependencies: RedisDistributedJobRuntime(**context.config)))


def _register_infrastructure(registry: ExtensionRegistry) -> None:
    from sagents.v2.tool.plugins.result_file import FileToolResultProcessor

    _one(
        registry, FileToolResultProcessor, "tool.result-processor",
        lambda context, dependencies: FileToolResultProcessor(**context.config),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={"type": "object", "additionalProperties": False,
                       "properties": {"max_inline_characters": {"type": "integer", "minimum": 1}}},
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
                    **_identity(implementation),
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

    _one(
        registry,
        NoopSessionMemoryProvider,
        "session-memory.provider",
        lambda context, dependencies: NoopSessionMemoryProvider(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        SqliteBm25SessionMemoryProvider,
        "session-memory.provider",
        lambda context, dependencies: SqliteBm25SessionMemoryProvider(
            context.config["root"]
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema=_root_config_schema(),
    )
    _one(
        registry,
        CompositeContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: CompositeContinuationPolicy(
            rules=(
                BudgetRule(),
                ExplicitStatusRule(),
                LoopRecoveryRule(int(context.config.get("repeat_threshold", 3))),
                FlowBoundaryRule(),
                ToolOrTextRule(),
            )
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(),
    )
    _one(
        registry,
        LLMJudgeContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: LLMJudgeContinuationPolicy(
            LLMContinuationJudge(
                dependencies.require_unique("model.provider"),
                model_binding=str(context.config.get("model_binding", "fast")),
                timeout_seconds=float(
                    context.config.get(
                        "timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                    )
                ),
            ),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(uses_model=True),
    )
    _one(
        registry,
        HybridContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: HybridContinuationPolicy(
            LLMContinuationJudge(
                dependencies.require_unique("model.provider"),
                model_binding=str(context.config.get("model_binding", "fast")),
                timeout_seconds=float(
                    context.config.get(
                        "timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                    )
                ),
            ),
            repeat_threshold=int(context.config.get("repeat_threshold", 3)),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(uses_model=True),
    )
    _one(
        registry,
        ExplicitStatusContinuationPolicy,
        "agent.continuation-policy",
        lambda context, dependencies: ExplicitStatusContinuationPolicy(
            repeat_threshold=int(context.config.get("repeat_threshold", 3))
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema=_continuation_config_schema(),
    )

    _one(
        registry,
        ReferenceContextUnitCompactor,
        "context.unit-compactor",
        lambda context, dependencies: ReferenceContextUnitCompactor(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema={"type": "object", "additionalProperties": False},
    )
    _one(
        registry,
        WindowContextReducer,
        "context.reducer",
        lambda context, dependencies: WindowContextReducer(),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={"type": "object", "additionalProperties": False},
    )
    _one(
        registry,
        PersistentSummaryContextReducer,
        "context.reducer",
        lambda context, dependencies: PersistentSummaryContextReducer(
            dependencies.require_unique("context.summary-store"),
            summarizer=dependencies.require_unique("context.summarizer"),
            summary_target_tokens=int(
                context.config.get("summary_target_tokens", 1024)
            ),
            protected_recent_units=int(context.config.get("protected_recent_units", 4)),
            unit_compactor=dependencies.require_unique("context.unit-compactor"),
            max_summary_calls=int(context.config.get("max_summary_calls", 64)),
        ),
        dependencies=(ExtensionDependency(capability="context.summary-store"), ExtensionDependency(capability="context.summarizer"), ExtensionDependency(capability="context.unit-compactor")),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={
            "type": "object",
            "properties": {
                "summary_target_tokens": {"type": "integer", "minimum": 1},
                "protected_recent_units": {"type": "integer", "minimum": 1},
                "max_summary_calls": {"type": "integer", "minimum": 1},
                "max_summary_source_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 24_000,
                },
            },
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        InMemoryConversationSummaryStore,
        "context.summary-store",
        lambda context, dependencies: InMemoryConversationSummaryStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        SessionDerivedConversationSummaryStore,
        "context.summary-store",
        lambda context, dependencies: SessionDerivedConversationSummaryStore(
            dependencies.require_unique("derived-state.store")
        ),
        dependencies=(ExtensionDependency(capability="derived-state.store"),),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema={
            "type": "object",
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        ExtractiveConversationSummarizer,
        "context.summarizer",
        lambda context, dependencies: ExtractiveConversationSummarizer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        ModelConversationSummarizer,
        "context.summarizer",
        lambda context, dependencies: ModelConversationSummarizer(
            dependencies.require_unique("model.provider"),
            model_binding=str(context.config.get("model_binding", "primary")),
            max_source_tokens=int(context.config.get("max_source_tokens", 24000)),
            timeout_seconds=float(
                context.config.get(
                    "timeout_seconds", DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS
                )
            ),
            idle_timeout_seconds=float(
                context.config.get(
                    "idle_timeout_seconds", DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS
                )
            ),
        ),
        dependencies=(ExtensionDependency(capability="model.provider"),),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
        config_schema={
            "type": "object",
            "properties": {
                "model_binding": {
                    "type": "string",
                    "const": "primary",
                    "default": "primary",
                    "readOnly": True,
                },
                "max_source_tokens": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 24_000,
                },
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS,
                },
                "idle_timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                },
            },
            "additionalProperties": False,
        },
        capabilities={"uses_model": True, "bounded_timeout": True},
    )

    _one(
        registry,
        InMemoryScheduler,
        "execution.scheduler",
        lambda context, dependencies: InMemoryScheduler(
            max_pending_items=int(context.config.get("max_pending_items", 1024)),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 4096)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema=_scheduler_config_schema(durable=False),
        capabilities={
            "durable_across_process_restart": False,
            "multi_process_writes": False,
            "supports_leases": True,
            "supports_fencing": True,
            "supports_distributed_claims": False,
            "supports_atomic_tenant_quota": True,
            "supports_atomic_fenced_mutations": True,
        },
    )
    _one(
        registry,
        FilesystemScheduler,
        "execution.scheduler",
        lambda context, dependencies: FilesystemScheduler(
            context.config["root"],
            max_pending_items=int(context.config.get("max_pending_items", 1024)),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 4096)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema=_scheduler_config_schema(durable=True),
        capabilities={
            "durable_across_process_restart": True,
            "multi_process_writes": False,
            "supports_leases": True,
            "supports_fencing": True,
            "supports_distributed_claims": False,
            "supports_atomic_tenant_quota": True,
            "supports_atomic_fenced_mutations": True,
        },
    )
    _one(
        registry,
        InMemoryJobRuntime,
        "execution.job-runtime",
        lambda context, dependencies: InMemoryJobRuntime(
            context.config.get("runners", {}),
            max_concurrent_jobs=int(context.config.get("max_concurrent_jobs", 32)),
            max_admitted_jobs=int(context.config.get("max_admitted_jobs", 1024)),
            max_job_output_bytes=int(
                context.config.get("max_job_output_bytes", 8 * 1024 * 1024)
            ),
            max_job_output_chunks=int(
                context.config.get("max_job_output_chunks", 8192)
            ),
            max_buffered_output_bytes=int(
                context.config.get("max_buffered_output_bytes", 256 * 1024 * 1024)
            ),
            max_buffered_output_chunks=int(
                context.config.get("max_buffered_output_chunks", 65536)
            ),
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_jobs=int(
                context.config.get("max_retained_terminal_jobs", 4096)
            ),
            max_retained_output_bytes=int(
                context.config.get("max_retained_output_bytes", 256 * 1024 * 1024)
            ),
            output_reconnect_window_seconds=int(
                context.config.get("output_reconnect_window_seconds", 300)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "properties": {
                "runners": {"type": "object"},
                "max_concurrent_jobs": {"type": "integer", "minimum": 1},
                "max_admitted_jobs": {"type": "integer", "minimum": 1},
                "max_job_output_bytes": {"type": "integer", "minimum": 1},
                "max_job_output_chunks": {"type": "integer", "minimum": 1},
                "max_buffered_output_bytes": {"type": "integer", "minimum": 1},
                "max_buffered_output_chunks": {"type": "integer", "minimum": 1},
                "terminal_ttl_seconds": {"type": "integer", "minimum": 1},
                "max_retained_terminal_jobs": {"type": "integer", "minimum": 0},
                "max_retained_output_bytes": {"type": "integer", "minimum": 0},
                "output_reconnect_window_seconds": {
                    "type": "integer",
                    "minimum": 0,
                },
            },
            "additionalProperties": False,
        },
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )
    _one(
        registry,
        InMemorySandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: InMemorySandboxProvider(
            _bytes(context.config["verification_key"]),
            process_handlers=dependencies.get_provider("execution.sandbox.process-handlers"),
            network_handlers=dependencies.get_provider("execution.sandbox.network-handlers"),
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 1024)
            ),
        ),
        dependencies=(
            ExtensionDependency(capability="execution.sandbox.process-handlers", name="default", optional=True),
            ExtensionDependency(capability="execution.sandbox.network-handlers", name="default", optional=True),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        config_schema=_sandbox_config_schema(in_memory=True),
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )
    _one(
        registry,
        LocalWorkspaceSandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: LocalWorkspaceSandboxProvider(
            _bytes(context.config["verification_key"]),
            **{
                key: context.config[key]
                for key in (
                    "command_path",
                    "read_paths",
                    "linux_cgroup_root",
                    "linux_quota_mount",
                    "linux_execution_uid",
                    "linux_execution_gid",
                )
                if key in context.config
            },
            terminal_ttl_seconds=int(
                context.config.get("terminal_ttl_seconds", 86_400)
            ),
            max_retained_terminal_items=int(
                context.config.get("max_retained_terminal_items", 1024)
            ),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        config_schema=_sandbox_config_schema(in_memory=False),
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )
    _one(
        registry,
        CubeVolumeSandboxProvider,
        "execution.sandbox",
        lambda context, dependencies: CubeVolumeSandboxProvider(
            _bytes(context.config["verification_key"]),
            api_url=context.config["api_url"],
            template_id=context.config["template_id"],
            proxy_node_ip=context.config["proxy_node_ip"],
            api_key=context.config.get("api_key"),
            volume_driver=context.config.get("volume_driver"),
        ),
        scopes={ExtensionScope.PROCESS},
        api_version="3",
        version="3.0.0",
        availability=ExtensionAvailability(
            available=importlib.util.find_spec("cubesandbox") is not None,
            reason=(
                None
                if importlib.util.find_spec("cubesandbox") is not None
                else "optional cubesandbox>=0.6.0 package is not installed"
            ),
        ),
        config_schema={
            "type": "object",
            "properties": {
                "verification_key": {},
                "api_url": {"type": "string", "minLength": 1},
                "template_id": {"type": "string", "minLength": 1},
                "proxy_node_ip": {"type": "string", "minLength": 1},
                "api_key": {"type": "string", "writeOnly": True},
                "volume_driver": {"type": "string"},
            },
            "required": ["verification_key", "api_url", "template_id", "proxy_node_ip"],
            "additionalProperties": False,
        },
        capabilities={"supports_terminal_purge": True},
    )

    _one(
        registry,
        EnvironmentCredentialProvider,
        "credentials.provider",
        lambda context, dependencies: EnvironmentCredentialProvider(
            {key: CredentialDeclaration.model_validate(value)
             for key, value in context.config.get("declarations", {}).items()},
            context.config.get("environment"),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
        config_schema={
            "type": "object",
            "properties": {
                "declarations": {"type": "object"},
                "environment": {"type": ["object", "null"]},
            },
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        MappingCredentialProvider,
        "credentials.provider",
        lambda context, dependencies: MappingCredentialProvider(
            context.config.get("values", {}),
            source=str(context.config.get("source", "host")),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
        config_schema={
            "type": "object",
            "properties": {
                "values": {"type": "object"},
                "source": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        NoopDiagnosticSink,
        "observability.diagnostic-sink",
        lambda context, dependencies: NoopDiagnosticSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        FilesystemDiagnosticSink,
        "observability.diagnostic-sink",
        lambda context, dependencies: FilesystemDiagnosticSink(
            context.config["root"],
            legacy_root=context.config.get("legacy_root"),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "properties": {
                "root": {"type": "string", "minLength": 1},
                "legacy_root": {"type": ["string", "null"], "minLength": 1},
            },
            "required": ["root"],
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        NoopLogSink,
        "observability.log-sink",
        lambda context, dependencies: NoopLogSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        FilesystemLogSink,
        "observability.log-sink",
        lambda context, dependencies: FilesystemLogSink(
            context.config["root"],
            filename=str(context.config.get("filename", "sage.jsonl")),
            max_bytes=int(context.config.get("max_bytes", 10 * 1024 * 1024)),
            backup_count=int(context.config.get("backup_count", 5)),
            min_level=str(context.config.get("min_level", "info")),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "properties": {
                "root": {"type": "string", "minLength": 1},
                "filename": {"type": "string", "minLength": 1},
                "max_bytes": {"type": "integer", "minimum": 1024},
                "backup_count": {"type": "integer", "minimum": 1},
                "min_level": {
                    "type": "string",
                    "enum": ["debug", "info", "warning", "error", "critical"],
                },
            },
            "required": ["root"],
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        StdoutLogSink,
        "observability.log-sink",
        lambda context, dependencies: StdoutLogSink(
            stream=str(context.config.get("stream", "stdout")),
            min_level=str(context.config.get("min_level", "info")),
            format=str(context.config.get("format", "json")),
        ),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "properties": {
                "stream": {
                    "type": "string",
                    "enum": ["stdout", "stderr"],
                    "default": "stdout",
                },
                "min_level": {
                    "type": "string",
                    "enum": ["debug", "info", "warning", "error", "critical"],
                    "default": "info",
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "text"],
                    "default": "json",
                },
            },
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        NoopTraceSink,
        "observability.trace-sink",
        lambda context, dependencies: NoopTraceSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        OtlpTraceSink,
        "observability.trace-sink",
        lambda context, dependencies: OtlpTraceSink(
            endpoint=str(context.config.get("endpoint") or "http://127.0.0.1:4317"),
            service_name=str(context.config.get("service_name") or "sage"),
            protocol=str(context.config.get("protocol") or "grpc"),
            insecure=bool(context.config.get("insecure", True)),
            **_trace_options(context.config),
        ),
        scopes={ExtensionScope.PROCESS},
        availability=ExtensionAvailability(
            available=otel_available(),
            reason=(
                None
                if otel_available()
                else "optional opentelemetry packages are not installed"
            ),
        ),
        config_schema={
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "minLength": 1,
                    "default": "http://127.0.0.1:4317",
                },
                "service_name": {
                    "type": "string",
                    "minLength": 1,
                    "default": "sage",
                },
                "protocol": {
                    "type": "string",
                    "enum": ["grpc", "http"],
                    "default": "grpc",
                },
                "insecure": {"type": "boolean", "default": True},
                **_TRACE_PROPERTIES,
            },
            "additionalProperties": False,
        },
        capabilities={"exports_otlp": True},
    )
    _one(
        registry,
        LangfuseTraceSink,
        "observability.trace-sink",
        lambda context, dependencies: LangfuseTraceSink(
            base_url=context.config["base_url"],
            public_key=os.environ.get(
                context.config.get("public_key_env", "LANGFUSE_PUBLIC_KEY"), ""
            ),
            secret_key=os.environ.get(
                context.config.get("secret_key_env", "LANGFUSE_SECRET_KEY"), ""
            ),
            service_name=context.config.get("service_name", "sage"),
            ingestion_version=context.config.get("ingestion_version", 4),
            **_trace_options(context.config),
        ),
        scopes={ExtensionScope.PROCESS},
        availability=ExtensionAvailability(
            available=langfuse_available(),
            reason=None
            if langfuse_available()
            else "optional OTLP HTTP exporter is not installed",
        ),
        config_schema={
            "type": "object",
            "required": ["base_url"],
            "properties": {
                "base_url": {"type": "string", "minLength": 1},
                "public_key_env": {"type": "string", "default": "LANGFUSE_PUBLIC_KEY"},
                "secret_key_env": {"type": "string", "default": "LANGFUSE_SECRET_KEY"},
                "service_name": {"type": "string", "default": "sage"},
                "ingestion_version": {"type": "integer", "enum": [3, 4], "default": 4},
                **_TRACE_PROPERTIES,
            },
            "additionalProperties": False,
        },
        capabilities={"exports_otlp": True},
    )
    _one(
        registry,
        PhoenixTraceSink,
        "observability.trace-sink",
        lambda context, dependencies: PhoenixTraceSink(
            endpoint=context.config["endpoint"],
            project_name=context.config.get("project_name", "sage"),
            api_key=os.environ.get(
                context.config.get("api_key_env", "PHOENIX_API_KEY"), ""
            ),
            service_name=context.config.get("service_name", "sage"),
            **_trace_options(context.config),
        ),
        scopes={ExtensionScope.PROCESS},
        availability=ExtensionAvailability(
            available=phoenix_available(),
            reason=None if phoenix_available() else "optional OTLP HTTP exporter is not installed",
        ),
        config_schema={
            "type": "object",
            "required": ["endpoint"],
            "properties": {
                "endpoint": {"type": "string", "minLength": 1},
                "project_name": {"type": "string", "minLength": 1, "default": "sage"},
                "api_key_env": {"type": "string", "default": "PHOENIX_API_KEY"},
                "service_name": {"type": "string", "default": "sage"},
                **_TRACE_PROPERTIES,
            },
            "additionalProperties": False,
        },
        capabilities={"exports_otlp": True},
    )
    _one(
        registry,
        ClawWorkspaceInitializer,
        "workspace.initializer",
        lambda context, dependencies: ClawWorkspaceInitializer(
            language=str(context.config.get("language", "en"))
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        config_schema={
            "type": "object",
            "properties": {"language": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        BareWorkspaceInitializer,
        "workspace.initializer",
        lambda context, dependencies: BareWorkspaceInitializer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        SessionArtifactStore,
        "artifact.store",
        lambda context, dependencies: SessionArtifactStore(
            dependencies.require_unique("session.store")
        ),
        dependencies=(ExtensionDependency(capability="session.store"),),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        InMemoryArtifactStore,
        "artifact.store",
        lambda context, dependencies: InMemoryArtifactStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
        capabilities={
            "durable_across_process_restart": False,
            "shared_across_processes": False,
        },
    )
    _one(
        registry,
        FilesystemArtifactStore,
        "artifact.store",
        lambda context, dependencies: FilesystemArtifactStore(context.config["root"]),
        scopes={ExtensionScope.PROCESS},
        config_schema={
            "type": "object",
            "required": ["root"],
            "properties": {"root": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        capabilities={
            "durable_across_process_restart": True,
            "shared_across_processes": True,
        },
    )
    _one(
        registry,
        InMemoryAgentPackageRegistry,
        "package.registry",
        lambda context, dependencies: InMemoryAgentPackageRegistry(
            resolver=dependencies.require_unique("package.resolver")
        ),
        dependencies=(ExtensionDependency(capability="package.resolver"),),
        scopes={ExtensionScope.PROCESS},
        config_schema=_strict_empty_config_schema(),
        capabilities={
            "durable_across_process_restart": False,
            "supports_package_signatures": False,
            "shared_across_processes": False,
        },
    )

    for adapter, config_schema in (
        (NativeProtocolAdapter, _strict_empty_config_schema()),
        (
            AgUiProtocolAdapter,
            {
                "type": "object",
                "properties": {"enable_sage_extensions": {"type": "boolean"}},
                "additionalProperties": False,
            },
        ),
        (AcpProtocolAdapter, _strict_empty_config_schema()),
        (A2AProtocolAdapter, _strict_empty_config_schema()),
        (McpProtocolAdapter, _strict_empty_config_schema()),
    ):
        _one(
            registry,
            adapter,
            "interface.protocol-adapter",
            lambda context, dependencies, adapter=adapter: adapter(**context.config),
            scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
            provider_name=adapter.plugin_id.rsplit(".", 1)[-1],
            multi_provider=True,
            config_schema=config_schema,
        )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(McpToolPlugin),
                dependencies=(ExtensionDependency(capability="mcp.session-factory", name="default", optional=True),),
                version="2.0.0",
                provides=(
                    CapabilityOffer(
                        capability="tool.catalog", api_version="2", name="mcp"
                    ),
                    CapabilityOffer(
                        capability="tool.executor", api_version="2", name="mcp"
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
                "tool.catalog:mcp": provider,
                "tool.executor:mcp": provider,
            },
        )
    )


def _identity(implementation: type) -> dict[str, str]:
    plugin_id, name, description = plugin_identity(implementation)
    return {
        "plugin_id": plugin_id,
        "name": name,
        "description": description,
    }


def _one(
    registry: ExtensionRegistry,
    implementation: type,
    capability: str,
    factory,
    *,
    scopes: set[ExtensionScope],
    dependencies: tuple[ExtensionDependency, ...] = (),
    provider_name: str = "default",
    multi_provider: bool = False,
    availability: ExtensionAvailability | None = None,
    config_schema: dict | None = None,
    capabilities: dict | None = None,
    api_version: str = "2",
    version: str = "2.0.0",
) -> None:
    if config_schema is not None:
        config_schema = _with_constructor_defaults(implementation, config_schema)
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(implementation),
                version=version,
                provides=(
                    CapabilityOffer(
                        capability=capability,
                        api_version=api_version,
                        name=provider_name,
                        multi_provider=multi_provider,
                    ),
                ),
                dependencies=dependencies,
                supported_scopes=frozenset(scopes),
                config_schema=(
                    config_schema
                    if config_schema is not None
                    else _strict_empty_config_schema()
                ),
                capabilities=capabilities or {},
                availability=availability or ExtensionAvailability(),
                built_in=True,
            ),
            factory=factory,
        )
    )


def _with_constructor_defaults(implementation: type, schema: dict) -> dict:
    """Publish scalar constructor defaults; explicit factory defaults win."""
    parameters = inspect.signature(implementation).parameters
    properties = {
        key: dict(value) for key, value in schema.get("properties", {}).items()
    }
    for key, field in properties.items():
        parameter = parameters.get(key)
        if parameter is None or "default" in field:
            continue
        value = parameter.default
        if isinstance(value, (str, int, float, bool)):
            field["default"] = value
    return {**schema, "properties": properties}


def _strict_empty_config_schema() -> dict:
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def _root_config_schema() -> dict:
    return {
        "type": "object",
        "properties": {"root": {"type": "string", "minLength": 1}},
        "required": ["root"],
        "additionalProperties": False,
    }


def _continuation_config_schema(*, uses_model: bool = False) -> dict:
    properties = {
        "repeat_threshold": {"type": "integer", "minimum": 1, "default": 3},
    }
    required = []
    if uses_model:
        properties.update(
            {
                "model_binding": {"type": "string", "minLength": 1, "default": "fast"},
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
                },
            }
        )
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _scheduler_config_schema(*, durable: bool) -> dict:
    properties = {
        "preserve_runs_on_shutdown": {"type": "boolean", "default": True},
        "max_pending_items": {"type": "integer", "minimum": 1},
        "max_retained_terminal_items": {"type": "integer", "minimum": 0},
        "max_concurrent_runs": {"type": "integer", "minimum": 1},
        "max_concurrent_runs_per_tenant": {"type": "integer", "minimum": 1},
        "lease_seconds": {
            "type": "number",
            "exclusiveMinimum": 0,
            "default": DEFAULT_LEASE_SECONDS,
        },
    }
    required = []
    if durable:
        properties["root"] = {"type": "string", "minLength": 1}
        required.append("root")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _sandbox_config_schema(*, in_memory: bool) -> dict:
    properties = {
        "verification_key": {},
        "terminal_ttl_seconds": {"type": "integer", "minimum": 1},
        "max_retained_terminal_items": {"type": "integer", "minimum": 0},
    }
    if not in_memory:
        properties.update(
            {
                "network": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["none", "unrestricted", "allowlist", "proxy"],
                        },
                        "deny_private_networks": {"type": "boolean"},
                        "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                        "allowed_ports": {
                            "type": "array",
                            "items": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 65535,
                            },
                        },
                        "allowed_schemes": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["http", "https"]},
                        },
                        "proxy_url": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "command_path": {"type": "string", "minLength": 1},
                "read_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "linux_cgroup_root": {"type": "string"},
                "linux_quota_mount": {"type": "string"},
                "linux_execution_uid": {"type": "integer", "minimum": 1},
                "linux_execution_gid": {"type": "integer", "minimum": 1},
            }
        )
    if in_memory:
        properties.update(
            {
            }
        )
    return {
        "type": "object",
        "properties": properties,
        "required": ["verification_key"],
        "additionalProperties": False,
    }


def _bytes(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


def _register_session_and_memory(registry: ExtensionRegistry) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(FilesystemSessionStore),
                version="2.1.0",
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
                    "supports_actor_authorization": True,
                    "supports_session_attachments": True,
                    "cross_process_subscribe": False,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
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
                **_identity(MysqlSessionStore),
                version="2.0.0",
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "table_prefix": {"type": "string"},
                        "max_cached_sessions": {"type": "integer", "minimum": 1},
                        "max_cached_bytes": {"type": "integer", "minimum": 1},
                        "cache_idle_seconds": {"type": "number", "minimum": 0},
                        "max_connections": {"type": "integer", "minimum": 2},
                        "max_pending_connections": {"type": "integer", "minimum": 1},
                        "connection_acquire_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                    },
                    "required": ["dsn"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                    "supports_actor_authorization": True,
                    "supports_session_attachments": True,
                    "cross_process_subscribe": False,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
                },
                availability=ExtensionAvailability(
                    available=importlib.util.find_spec("aiomysql") is not None,
                    reason=(
                        None
                        if importlib.util.find_spec("aiomysql") is not None
                        else "optional aiomysql package is not installed"
                    ),
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: MysqlSessionStore(
                str(context.config["dsn"]),
                **{key: context.config[key] for key in
                   ("max_cached_sessions", "max_cached_bytes", "cache_idle_seconds",
                    "max_connections", "max_pending_connections", "connection_acquire_timeout_seconds") if key in context.config},
                table_prefix=(
                    None
                    if "table_prefix" not in context.config
                    else str(context.config.get("table_prefix") or "")
                ),
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(RedisMysqlSessionStore),
                version="3.0.0",
                provides=(CapabilityOffer(capability="session.store", api_version="2"),),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "redis_url": {"type": "string", "minLength": 1},
                        "max_cached_sessions": {"type": "integer", "minimum": 1},
                        "max_cached_bytes": {"type": "integer", "minimum": 1},
                        "cache_idle_seconds": {"type": "number", "minimum": 0},
                        "max_connections": {"type": "integer", "minimum": 2},
                        "max_pending_connections": {"type": "integer", "minimum": 1},
                        "connection_acquire_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "table_prefix": {"type": "string"},
                        "key_prefix": {"type": "string", "minLength": 1},
                        "archive_interval_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "retention_seconds": {"type": "integer", "minimum": 1},
                        "coordination_ttl_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "coordination_wait_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "event_poll_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "max_preview_events": {"type": "integer", "minimum": 1},
                        "preview_retention_seconds": {"type": "integer", "minimum": 1},
                    },
                    "required": ["dsn", "redis_url"], "additionalProperties": False,
                },
                capabilities={
                    "durable": True, "global_session_index": False, "multi_process_writes": True,
                    "supports_actor_authorization": True, "supports_session_attachments": True,
                    "cross_process_subscribe": True, "atomic_worker_fence": True, "transactional_outbox": False, "atomic_session_cas": True,
                },
                availability=ExtensionAvailability(
                    available=all(importlib.util.find_spec(name) is not None for name in ("aiomysql", "redis")),
                    reason=None if all(importlib.util.find_spec(name) is not None for name in ("aiomysql", "redis"))
                    else "optional aiomysql and redis packages are required",
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: RedisMysqlSessionStore(
                **{key: value for key, value in context.config.items() if key != "dsn"},
                dsn=str(context.config["dsn"]),
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(DirectMemoryRecallQueryGenerator),
                version="2.0.0",
                provides=(
                    CapabilityOffer(capability="memory.recall-query", api_version="2"),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
                ),
                config_schema=_strict_empty_config_schema(),
                capabilities={"uses_model": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: DirectMemoryRecallQueryGenerator(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(LLMMemoryRecallQueryGenerator),
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
                **_identity(EphemeralSessionStore),
                version="2.0.0",
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema=_strict_empty_config_schema(),
                capabilities={"durable": False, "testing": True},
                built_in=True,
            ),
            factory=lambda context, dependencies: EphemeralSessionStore(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(NoopMemoryProvider),
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
                config_schema=_strict_empty_config_schema(),
                capabilities={"durable": False},
                built_in=True,
            ),
            factory=lambda context, dependencies: NoopMemoryProvider(),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(FilesystemBm25MemoryProvider),
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


def _register_tools_skills_and_flow(registry: ExtensionRegistry) -> None:
    from sagents.v2.skill.registrations import skill_registrations
    for registration in skill_registrations():
        registry.register(registration)
    registry.register(
        ExtensionRegistration(
            descriptor=SkillLoadingPlugin.descriptor,
            config_model=SkillLoadingConfig,
            factory=lambda context, dependencies: SkillLoadingPlugin(**context.config),
            start=lambda plugin, context, dependencies: {"skill.loading": plugin},
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=EphemeralToolPlugin.descriptor,
            factory=lambda context, dependencies: EphemeralToolPlugin(
                tools=tuple(ToolDefinition.model_validate(item) for item in context.config.get("tools", ())),
                handlers=dependencies.get_provider("tool.handlers"),
            ),
            start=lambda plugin, context, dependencies: {
                "tool.catalog:ephemeral": plugin.catalog,
                "tool.executor:ephemeral": plugin.executor,
            },
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=OfficialToolPlugin.descriptor,
            factory=lambda context, dependencies: OfficialToolPlugin(dependencies.require("execution.tool-runtime")),
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
                dependencies.require_unique("skill.loader"), language=context.config.get("language"),
                allow_editing=context.config.get("allow_editing", False),
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
                coordinator=dependencies.require_unique("agent.coordinator"),
                runtime=dependencies.require_unique("runtime.kernel"),
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
                **_identity(FilesystemSkillProvider),
                version="2.0.0",
                provides=(
                    CapabilityOffer(
                        capability="skill.catalog", api_version="2", name="filesystem"
                    ),
                    CapabilityOffer(
                        capability="skill.source", api_version="2", name="filesystem"
                    ),
                    CapabilityOffer(capability="skill.management", api_version="2", name="filesystem"),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT}
                ),
                config_schema={
                    "type": "object",
                    "properties": {
                        "roots": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                        },
                        "max_files": {"type": "integer", "minimum": 1},
                        "max_total_bytes": {"type": "integer", "minimum": 1},
                    },
                    "required": ["roots"],
                    "additionalProperties": False,
                },
                built_in=True,
            ),
            factory=lambda context, dependencies: FilesystemSkillProvider(
                tuple(context.config["roots"]),
                max_files=int(context.config.get("max_files", 2_000)),
                max_total_bytes=int(
                    context.config.get("max_total_bytes", 64 * 1024 * 1024)
                ),
            ),
            start=lambda provider, context, dependencies: {
                "skill.catalog:filesystem": provider,
                "skill.source:filesystem": provider,
                "skill.management:filesystem": provider,
            },
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                **_identity(NativeAgentFlowNode),
                dependencies=(ExtensionDependency(capability="runtime.kernel"),
                              ExtensionDependency(capability="agent.child-executor")),
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
                workspace_policy=WorkspaceSharingPolicy(context.config.get("workspace_policy", "shared_parent")),
            ),
        )
    )


def _register_model_protocols(registry: ExtensionRegistry) -> None:
    for descriptor in model_protocol_descriptors():
        implementation = model_protocol_implementation(descriptor.protocol)
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    **_identity(implementation),
                    dependencies=(ExtensionDependency(capability="credentials.provider"),
                                  ExtensionDependency(capability="model.client", name="default", optional=True)),
                    version=implementation.plugin_version,
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
                        "properties": {
                            "route": {"type": "object"},
                            "provider_instance_id": {"type": "string"},
                        },
                        "required": ["route"],
                        "additionalProperties": False,
                    },
                    capabilities={"protocol": descriptor.protocol.value},
                    built_in=True,
                ),
                factory=_model_factory,
            )
        )


async def _model_factory(context, dependencies):
    from sagents.v2.runtime.credentials.contracts import CredentialRef
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext

    route = ModelRoute.model_validate(context.config["route"])
    credential = None
    if route.credential is not None:
        credential = await dependencies.require_unique("credentials.provider").resolve(
            CredentialRef(credential_id=route.credential, purpose="model.inference"),
            RequestContext(actor=ActorRef(
                principal_id="sagent-builder", principal_type=PrincipalType.SERVICE,
                tenant_id=context.tenant_id,
            )),
        )
    return create_registered_model_provider(
        route, credential, client=dependencies.get_provider("model.client"),
        provider_instance_id=context.config.get("provider_instance_id"),
    )


_TRACE_PROPERTIES = {
    "environment": {"type": "string", "default": "production"},
    "content_mode": {
        "type": "string",
        "enum": ["metadata", "redacted", "raw"],
        "default": "redacted",
    },
    "max_content_chars": {
        "type": "integer",
        "minimum": 256,
        "maximum": 65536,
        "default": 16384,
    },
    "sample_rate": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0},
    "max_queue_size": {"type": "integer", "minimum": 1, "default": 2048},
    "max_active_spans": {"type": "integer", "minimum": 1, "default": 4096},
    "timeout_seconds": {
        "type": "number",
        "exclusiveMinimum": 0,
        "maximum": 30,
        "default": 3.0,
    },
}


def _trace_options(config):
    return {key: config[key] for key in _TRACE_PROPERTIES if key in config}
