"""Single inventory of first-party plugin registrations.

Implementation classes remain in their owning domains. This module only binds
stable plugin IDs to factories so every host-selectable implementation appears
in one ExtensionRegistry. Call ``builtin_extension_registry()`` for a fresh
inventory.
"""

from __future__ import annotations

import importlib.util

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
    JsonHeuristicTokenEstimator,
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
    SessionDerivedConversationSummaryStore,
    TiktokenTokenEstimator,
    UnicodeHeuristicTokenEstimator,
    WindowContextReducer,
)
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.interfaces.protocols.acp import AcpProtocolAdapter
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.interfaces.protocols.mcp import McpProtocolAdapter
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter
from sagents.v2.package.registry import InMemoryAgentPackageRegistry
from sagents.v2.runtime.artifact import InMemoryArtifactStore
from sagents.v2.runtime.credentials import (
    EnvironmentCredentialProvider,
    MappingCredentialProvider,
)
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.sandbox import (
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
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin
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
from sagents.v2.memory.plugins.recall_direct import DirectMemoryRecallQueryGenerator
from sagents.v2.memory.plugins.recall_llm import LLMMemoryRecallQueryGenerator
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    model_protocol_descriptors,
)
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    FilesystemSessionStore,
    MysqlSessionStore,
    PostgresSessionStore,
)
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.tool.plugins.delegation import MultiAgentToolPlugin
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin
from sagents.v2.tool.plugins.official import OfficialToolPlugin
from sagents.v2.tool.plugins.skill import SkillToolPlugin
from sagents.v2.flow.plugins.agent import NativeAgentFlowNode


def builtin_extension_registry() -> ExtensionRegistry:
    """Return a fresh registry whose inventory is backed by real factories."""

    registry = ExtensionRegistry()
    register_official_plugins(registry)
    return registry


def register_official_plugins(registry: ExtensionRegistry) -> None:
    """Register every first-party host-selectable plugin."""

    _register_session_and_memory(registry)
    _register_tools_skills_and_flow(registry)
    _register_infrastructure(registry)
    _register_model_protocols(registry)


def _register_infrastructure(registry: ExtensionRegistry) -> None:

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
        },
        "additionalProperties": False,
    }
    for name, description, implementation, uses_model in (
        (
            "Show all Tools",
            "Sends every policy-allowed Tool to the model. Best for small catalogs.",
            DirectToolSelectionPolicy,
            False,
        ),
        (
            "LLM Tool selection",
            "Uses a fast model and recent context to select relevant Tools; falls back locally on failure.",
            LLMToolSelectionPolicy,
            True,
        ),
        (
            "BM25 Tool selection",
            "Ranks Tool names, descriptions, and parameters locally like a search engine.",
            LexicalToolSelectionPolicy,
            False,
        ),
        (
            "Recently used Tools first",
            "Keeps recently called Tools first, then fills the remaining count deterministically.",
            RecentToolSelectionPolicy,
            False,
        ),
    ):
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    plugin_id=implementation.plugin_id,
                    version="2.0.0",
                    name=name,
                    description=description,
                    provides=(
                        CapabilityOffer(
                            capability="tool.selection-policy", api_version="2"
                        ),
                    ),
                    supported_scopes=frozenset(
                        {ExtensionScope.AGENT, ExtensionScope.RUN}
                    ),
                    config_schema=(
                        {"type": "object", "properties": {}, "additionalProperties": False}
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
                factory=lambda context, dependencies, implementation=implementation: implementation(
                    context.config
                ),
            )
        )

    _one(
        registry,
        "sage.session-memory.noop",
        "No-op Session Memory provider",
        "session-memory.provider",
        lambda context, dependencies: NoopSessionMemoryProvider(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        "sage.session-memory.sqlite-bm25",
        "SQLite BM25 Session Memory provider",
        "session-memory.provider",
        lambda context, dependencies: SqliteBm25SessionMemoryProvider(
            context.config["root"]
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        "sage.agent.continuation.deterministic",
        "Deterministic continuation policy",
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
    )
    _one(
        registry,
        "sage.agent.continuation.llm-judge",
        "No-tool-call LLM Judge completion policy",
        "agent.continuation-policy",
        lambda context, dependencies: LLMJudgeContinuationPolicy(
            LLMContinuationJudge(
                context.config["model"],
                model_binding=str(context.config.get("model_binding", "fast")),
            ),
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
    )
    _one(
        registry,
        "sage.agent.continuation.hybrid",
        "Hybrid deterministic and LLM Judge policy",
        "agent.continuation-policy",
        lambda context, dependencies: HybridContinuationPolicy(
            LLMContinuationJudge(
                context.config["model"],
                model_binding=str(context.config.get("model_binding", "fast")),
            ),
            repeat_threshold=int(context.config.get("repeat_threshold", 3)),
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
    )
    _one(
        registry,
        "sage.agent.continuation.explicit-status",
        "Explicit turn_status completion policy",
        "agent.continuation-policy",
        lambda context, dependencies: ExplicitStatusContinuationPolicy(
            repeat_threshold=int(context.config.get("repeat_threshold", 3))
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
    )

    _one(
        registry,
        JsonHeuristicTokenEstimator.plugin_id,
        "JSON heuristic token estimator",
        "context.token-estimator",
        lambda context, dependencies: JsonHeuristicTokenEstimator(**context.config),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        UnicodeHeuristicTokenEstimator.plugin_id,
        "Unicode heuristic token estimator",
        "context.token-estimator",
        lambda context, dependencies: UnicodeHeuristicTokenEstimator(**context.config),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        TiktokenTokenEstimator.plugin_id,
        "Tiktoken token estimator",
        "context.token-estimator",
        lambda context, dependencies: TiktokenTokenEstimator(**context.config),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
        availability=ExtensionAvailability(
            available=importlib.util.find_spec("tiktoken") is not None,
            reason=(
                None
                if importlib.util.find_spec("tiktoken") is not None
                else "optional tiktoken package is not installed"
            ),
        ),
    )
    _one(
        registry,
        ReferenceContextUnitCompactor.plugin_id,
        "Durable-reference context unit compactor",
        "context.unit-compactor",
        lambda context, dependencies: ReferenceContextUnitCompactor(
            context.config.get("estimator")
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        WindowContextReducer.plugin_id,
        "Window context reducer",
        "context.reducer",
        lambda context, dependencies: WindowContextReducer(
            context.config.get("estimator")
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
    )
    _one(
        registry,
        PersistentSummaryContextReducer.plugin_id,
        "Persistent summary context reducer",
        "context.reducer",
        lambda context, dependencies: PersistentSummaryContextReducer(
            context.config["store"],
            summarizer=context.config.get("summarizer"),
            estimator=context.config.get("estimator"),
            summary_target_tokens=int(
                context.config.get("summary_target_tokens", 1024)
            ),
            protected_recent_units=int(context.config.get("protected_recent_units", 4)),
            max_summary_source_tokens=int(
                context.config.get("max_summary_source_tokens", 24000)
            ),
            unit_compactor=context.config.get("unit_compactor"),
        ),
        scopes={ExtensionScope.AGENT, ExtensionScope.RUN},
    )
    _one(
        registry,
        InMemoryConversationSummaryStore.plugin_id,
        "Ephemeral conversation summary store",
        "context.summary-store",
        lambda context, dependencies: InMemoryConversationSummaryStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        SessionDerivedConversationSummaryStore.plugin_id,
        "Session-derived conversation summary store",
        "context.summary-store",
        lambda context, dependencies: SessionDerivedConversationSummaryStore(
            context.config["session_store"]
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        ExtractiveConversationSummarizer.plugin_id,
        "Extractive conversation summarizer",
        "context.summarizer",
        lambda context, dependencies: ExtractiveConversationSummarizer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        ModelConversationSummarizer.plugin_id,
        "Model conversation summarizer",
        "context.summarizer",
        lambda context, dependencies: ModelConversationSummarizer(
            context.config["model"],
            model_binding=str(context.config.get("model_binding", "summary")),
            max_source_tokens=int(context.config.get("max_source_tokens", 24000)),
        ),
        scopes={ExtensionScope.AGENT},
    )

    _one(
        registry,
        "sage.scheduler.ephemeral",
        "In-memory scheduler",
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
        "sage.scheduler.filesystem",
        "Filesystem durable scheduler",
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
        "sage.job.ephemeral",
        "In-memory Job runtime",
        "execution.job-runtime",
        lambda context, dependencies: InMemoryJobRuntime(
            context.config.get("runners", {}),
            max_concurrent_jobs=int(context.config.get("max_concurrent_jobs", 32)),
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
        "sage.sandbox.ephemeral",
        "In-memory sandbox provider",
        "execution.sandbox",
        lambda context, dependencies: InMemorySandboxProvider(
            _bytes(context.config["verification_key"]),
            process_handlers=context.config.get("process_handlers"),
            network_handlers=context.config.get("network_handlers"),
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
        config_schema=_sandbox_config_schema(in_memory=True),
        capabilities={
            "supports_terminal_purge": True,
            "supports_automatic_terminal_retention": True,
        },
    )
    _one(
        registry,
        "sage.sandbox.local-workspace",
        "Local workspace sandbox provider",
        "execution.sandbox",
        lambda context, dependencies: LocalWorkspaceSandboxProvider(
            _bytes(context.config["verification_key"]),
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
        "sage.credentials.environment",
        "Environment credential provider",
        "credentials.provider",
        lambda context, dependencies: EnvironmentCredentialProvider(
            context.config.get("declarations", {}),
            context.config.get("environment"),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
    )
    _one(
        registry,
        "sage.credentials.mapping",
        "Mapping credential provider",
        "credentials.provider",
        lambda context, dependencies: MappingCredentialProvider(
            context.config.get("values", {}),
            source=str(context.config.get("source", "host")),
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.TENANT},
    )
    _one(
        registry,
        NoopDiagnosticSink.plugin_id,
        "No-op diagnostic sink",
        "observability.diagnostic-sink",
        lambda context, dependencies: NoopDiagnosticSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        FilesystemDiagnosticSink.plugin_id,
        "Filesystem diagnostic sink",
        "observability.diagnostic-sink",
        lambda context, dependencies: FilesystemDiagnosticSink(
            context.config["root"],
            legacy_root=context.config.get("legacy_root"),
        ),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        NoopLogSink.plugin_id,
        "No-op structured log sink",
        "observability.log-sink",
        lambda context, dependencies: NoopLogSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        FilesystemLogSink.plugin_id,
        "Rotating filesystem structured log sink",
        "observability.log-sink",
        lambda context, dependencies: FilesystemLogSink(
            context.config["root"],
            filename=str(context.config.get("filename", "sage.jsonl")),
            max_bytes=int(context.config.get("max_bytes", 10 * 1024 * 1024)),
            backup_count=int(context.config.get("backup_count", 5)),
            min_level=str(context.config.get("min_level", "info")),
        ),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        StdoutLogSink.plugin_id,
        "Stdout structured log sink",
        "observability.log-sink",
        lambda context, dependencies: StdoutLogSink(
            stream=str(context.config.get("stream", "stdout")),
            min_level=str(context.config.get("min_level", "info")),
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
            },
            "additionalProperties": False,
        },
    )
    _one(
        registry,
        NoopTraceSink.plugin_id,
        "No-op trace sink",
        "observability.trace-sink",
        lambda context, dependencies: NoopTraceSink(),
        scopes={ExtensionScope.PROCESS},
    )
    _one(
        registry,
        OtlpTraceSink.plugin_id,
        "OTLP / Jaeger trace sink",
        "observability.trace-sink",
        lambda context, dependencies: OtlpTraceSink(
            endpoint=str(context.config.get("endpoint") or "http://127.0.0.1:4317"),
            service_name=str(context.config.get("service_name") or "sage"),
            protocol=str(context.config.get("protocol") or "grpc"),
            insecure=bool(context.config.get("insecure", True)),
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
            },
            "additionalProperties": False,
        },
        capabilities={"exports_otlp": True},
    )
    _one(
        registry,
        "sage.workspace.initializer.claw",
        "Claw Mode workspace",
        "workspace.initializer",
        lambda context, dependencies: ClawWorkspaceInitializer(
            language=str(context.config.get("language", "en"))
        ),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        "sage.workspace.initializer.bare",
        "Bare workspace",
        "workspace.initializer",
        lambda context, dependencies: BareWorkspaceInitializer(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.AGENT},
    )
    _one(
        registry,
        "sage.artifact.ephemeral",
        "In-memory ArtifactStore",
        "artifact.store",
        lambda context, dependencies: InMemoryArtifactStore(),
        scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
    )
    _one(
        registry,
        "sage.package-registry.ephemeral",
        "In-memory AgentPackage registry",
        "package.registry",
        lambda context, dependencies: InMemoryAgentPackageRegistry(),
        scopes={ExtensionScope.PROCESS},
    )

    for plugin_id, name, adapter in (
        ("sage.protocol.native", "Native protocol adapter", NativeProtocolAdapter),
        ("sage.protocol.ag-ui", "AG-UI protocol adapter", AgUiProtocolAdapter),
        ("sage.protocol.acp", "ACP protocol adapter", AcpProtocolAdapter),
        ("sage.protocol.a2a", "A2A protocol adapter", A2AProtocolAdapter),
        ("sage.protocol.mcp", "MCP protocol adapter", McpProtocolAdapter),
    ):
        _one(
            registry,
            plugin_id,
            name,
            "interface.protocol-adapter",
            lambda context, dependencies, adapter=adapter: adapter(**context.config),
            scopes={ExtensionScope.PROCESS, ExtensionScope.RUN},
            provider_name=plugin_id.rsplit(".", 1)[-1],
            multi_provider=True,
        )

    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.tool.mcp",
                version="2.0.0",
                name="MCP Tool provider",
                provides=(
                    CapabilityOffer(
                        capability="tool.catalog", api_version="2", name="mcp"
                    ),
                    CapabilityOffer(
                        capability="tool.executor", api_version="2", name="mcp"
                    ),
                ),
                supported_scopes=frozenset(
                    {ExtensionScope.PROCESS, ExtensionScope.AGENT}
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: McpToolPlugin(
                tuple(
                    McpServerConfig.model_validate(value)
                    for value in context.config.get("servers", ())
                ),
                session_factory=context.config.get("session_factory"),
            ),
            start=lambda provider, context, dependencies: {
                "tool.catalog:mcp": provider,
                "tool.executor:mcp": provider,
            },
        )
    )


def _one(
    registry: ExtensionRegistry,
    plugin_id: str,
    name: str,
    capability: str,
    factory,
    *,
    scopes: set[ExtensionScope],
    provider_name: str = "default",
    multi_provider: bool = False,
    availability: ExtensionAvailability | None = None,
    config_schema: dict | None = None,
    capabilities: dict | None = None,
    api_version: str = "2",
    version: str = "2.0.0",
) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=plugin_id,
                version=version,
                name=name,
                provides=(
                    CapabilityOffer(
                        capability=capability,
                        api_version=api_version,
                        name=provider_name,
                        multi_provider=multi_provider,
                    ),
                ),
                supported_scopes=frozenset(scopes),
                config_schema=config_schema or {},
                capabilities=capabilities or {},
                availability=availability or ExtensionAvailability(),
                built_in=True,
            ),
            factory=factory,
        )
    )


def _scheduler_config_schema(*, durable: bool) -> dict:
    properties = {
        "max_pending_items": {"type": "integer", "minimum": 1},
        "max_retained_terminal_items": {"type": "integer", "minimum": 0},
        "max_concurrent_runs": {"type": "integer", "minimum": 1},
        "max_concurrent_runs_per_tenant": {"type": "integer", "minimum": 1},
        "lease_seconds": {"type": "number", "exclusiveMinimum": 0},
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
    if in_memory:
        properties.update(
            {
                "process_handlers": {"type": "object"},
                "network_handlers": {"type": "object"},
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
                    "supports_actor_authorization": True,
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
                plugin_id="sage.session.postgres",
                version="2.2.0",
                name="PostgreSQL SessionStore",
                description=(
                    "Durable per-Session PostgreSQL store with appended Run events. "
                    "Single-process writers; no global Session index."
                ),
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "schema_name": {"type": "string", "minLength": 1},
                        "table_prefix": {"type": "string", "minLength": 1},
                    },
                    "required": ["dsn"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                    "supports_actor_authorization": True,
                    "cross_process_subscribe": False,
                    "transactional_outbox": False,
                    "atomic_session_cas": True,
                },
                availability=ExtensionAvailability(
                    available=importlib.util.find_spec("asyncpg") is not None,
                    reason=(
                        None
                        if importlib.util.find_spec("asyncpg") is not None
                        else "optional asyncpg package is not installed"
                    ),
                ),
                built_in=True,
            ),
            factory=lambda context, dependencies: PostgresSessionStore(
                str(context.config["dsn"]),
                schema_name=str(context.config.get("schema_name") or "sage_v2"),
                table_prefix=str(context.config.get("table_prefix") or "sagent"),
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="sage.session.mysql",
                version="2.0.0",
                name="MySQL SessionStore",
                description=(
                    "Durable per-Session MySQL store with appended Run events. "
                    "Single-process writers; no global Session index."
                ),
                provides=(
                    CapabilityOffer(capability="session.store", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={
                    "type": "object",
                    "properties": {
                        "dsn": {"type": "string", "minLength": 1},
                        "table_prefix": {"type": "string", "minLength": 1},
                    },
                    "required": ["dsn"],
                    "additionalProperties": False,
                },
                capabilities={
                    "durable": True,
                    "global_session_index": False,
                    "multi_process_writes": False,
                    "supports_actor_authorization": True,
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
                table_prefix=str(context.config.get("table_prefix") or "sagent"),
            ),
        )
    )
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=DirectMemoryRecallQueryGenerator.plugin_id,
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
                plugin_id=LLMMemoryRecallQueryGenerator.plugin_id,
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
                plugin_id=NoopMemoryProvider.plugin_id,
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
                plugin_id=FilesystemBm25MemoryProvider.plugin_id,
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


def _register_tools_skills_and_flow(registry: ExtensionRegistry) -> None:
    registry.register(
        ExtensionRegistration(
            descriptor=EphemeralToolPlugin.descriptor,
            factory=lambda context, dependencies: EphemeralToolPlugin(
                tools=tuple(context.config.get("tools") or ()),
                handlers=context.config.get("handlers") or {},
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


def _register_model_protocols(registry: ExtensionRegistry) -> None:
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
