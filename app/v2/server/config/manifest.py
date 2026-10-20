from __future__ import annotations

from sagents.v2.package.manifest.agents import (
    AgentDefinition,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.root import (
    InterfaceDeclaration,
    ManifestMetadata,
    SageManifest,
)
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig

from app.v2.server.config.settings import ServerSettings
from app.v2.server.catalog.records import AgentRecord
from app.v2.server.runtime.official import default_agent_tools


def distributed_runtime_prefix(settings, component):
    import hashlib
    import json
    from sagents.v2.runtime.session.plugins.mysql import parse_mysql_dsn
    identity = parse_mysql_dsn(settings.mysql_url)
    identity.pop("password")
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return f"sage:{component}:{{{digest}}}:distributed"


def server_v2_run_manifest(
    settings: ServerSettings | None = None,
    *,
    registry=None,
    agent: AgentRecord | None = None,
    agent_id: str = "main",
    skills: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    instructions: str | None = None,
    name: str | None = None,
) -> SageManifest:
    """Per-run manifest from a catalog Agent. Process backends stay unchanged."""

    if agent is not None:
        agent_id = agent.id
        name = name or agent.name
        instructions = instructions if instructions is not None else agent.instructions
        if not tools:
            tools = (*agent.tools, *agent.external_tools)
    selected_tools = list(tools) if agent is not None or tools else default_agent_tools()
    host = server_v2_manifest(settings)
    base = agent.package.resolved_manifest() if agent is not None else host
    source = base.agents.get(agent_id) or next(iter(base.agents.values()))
    composed = source.model_copy(
        update={
            "name": name or source.name,
            "description": agent.description
            if agent is not None
            else source.description,
            "skills": tuple(name for name in skills if name in source.skills)
            if agent is not None and agent.package.dependencies else tuple(skills),
            "tools": tuple(selected_tools),
            "tool_approval": agent.tool_approval
            if agent is not None
            else source.tool_approval,
            "instructions": Instructions(
                inline=instructions
                or source.instructions.inline
                or "Be helpful, concise, and explicit about uncertainty."
            ),
        }
    )
    from app.v2.server.catalog.plugins import validate_agent_plugins

    selections = dict(base.runtime.capabilities) if agent is not None else {}
    validate_agent_plugins(selections, registry=registry)
    from sagents.v2.package.manifest.runtime import merge_capability_selections

    selections = merge_capability_selections(host.runtime.capabilities, selections)
    return base.model_copy(
        update={
            "runtime": host.runtime.model_copy(
                update={"capabilities": selections}
            ),
            "interfaces": host.interfaces,
            "agents": {agent_id: composed},
            "entrypoint": ApplicationEntrypoint(agent=agent_id),
        }
    )


def server_v2_manifest(settings: ServerSettings | None = None) -> SageManifest:
    """In-process package: no yaml, no env credentials, no model routes.

    Models are supplied by the registered per-Run model capability.
    Host backends (default stdout logs, MySQL session, Jaeger OTLP) are selected
    here and passed as plugin config. ServerHost injects its shared log sink in
    place of the default stdout sink. Plugins do not read environment variables.
    """

    return SageManifest(
        kind="application",
        metadata=ManifestMetadata(
            id="com.sage.server-v2",
            version="0.1.0",
            name="Sage Server v2",
        ),
        runtime=RuntimeConfig(
            capabilities=_runtime_capabilities(settings),
            required_guarantees=_required_guarantees(settings),
        ),
        agents={
            "main": AgentDefinition(
                name="Main Assistant",
                instructions=Instructions(
                    inline="Be helpful, concise, and explicit about uncertainty."
                ),
            )
        },
        entrypoint=ApplicationEntrypoint(agent="main"),
        interfaces={
            "ag_ui": InterfaceDeclaration(
                plugin="sage.protocol.ag-ui",
                enabled=True,
                config={"enable_sage_extensions": True},
            ),
            "a2a": InterfaceDeclaration(
                plugin="sage.protocol.a2a",
                enabled=True,
            ),
        },
    )


def _required_guarantees(
    settings: ServerSettings | None,
) -> dict[str, dict[str, object]]:
    """Assert what the Server actually depends on, so a swap fails at build.

    These are requirements, not documentation: selecting a SessionStore that
    cannot prove them aborts startup instead of degrading a multi-tenant
    deployment at runtime. Process topology is not duplicated in application
    configuration; stores and schedulers enforce their own writer and lease
    contracts.
    """

    store: dict[str, object] = {
        "transactional_run_events": True,
        "transactional_suspension": True,
        "supports_actor_authorization": True,
    }
    if settings is not None and settings.mysql_url:
        store["durable_across_process_restart"] = True
    if settings is not None and settings.redis_url and settings.session_store_plugin != "sage.session.mysql":
        store.update(multi_process_writes=True, cross_process_subscribe=True, atomic_worker_fence=True)
    if settings is not None and settings.scheduler_plugin == "sage.scheduler.redis-distributed":
        return {"session.store": store, "execution.scheduler": {
            "supports_distributed_claims": True, "supports_atomic_fenced_mutations": True},
            "execution.job-runtime": {"multi_process_writes": True, "supports_remote_cancel": True}}
    return {"session.store": store}


def _runtime_capabilities(
    settings: ServerSettings | None,
) -> dict[str, CapabilitySelection]:
    log_level = settings.log_level if settings is not None else "info"
    log_format = settings.log_format if settings is not None else "json"
    from app.v2.server.catalog.plugins import AGENT_DEFAULTS, DEFAULT_CONFIG

    capabilities: dict[str, CapabilitySelection] = {
        **{key: CapabilitySelection(plugin=plugin, config=DEFAULT_CONFIG.get(key, {}))
           for key, plugin in AGENT_DEFAULTS.items()},
        "artifact.store": CapabilitySelection(plugin="sage.artifact.session"),
        # Pin the deployed product choices rather than inheriting SDK defaults
        # that may change when the SDK is upgraded.
        "context.summary-store": CapabilitySelection(
            plugin="sage.context.summary-store.session-derived",
        ),
        "observability.trace-sink": CapabilitySelection(plugin="sage.trace.noop"),
        "package.registry": CapabilitySelection(plugin="sage.package-registry.ephemeral"),
        "context.summarizer": CapabilitySelection(
            plugin="sage.context.summarizer.model",
            config={"model_binding": "primary"},
        ),
        "agent.continuation-policy": CapabilitySelection(
            plugin="sage.agent.continuation.llm-judge",
            config={"model_binding": "fast"},
        ),
        "observability.log-sink": CapabilitySelection(
            plugin="sage.logging.stdout",
            config={
                "stream": "stdout",
                "min_level": log_level,
                "format": log_format,
            },
        )
    }
    if settings is not None:
        capabilities.update({
            "memory.provider": CapabilitySelection(
                plugin="sage.memory.filesystem-bm25",
                config={"root": str(settings.data_root / "runtime" / "memory")},
            ),
            "session-memory.provider": CapabilitySelection(
                plugin="sage.session-memory.sqlite-bm25",
                config={"root": str(settings.data_root / "runtime" / "session-memory")},
            ),
            "workspace.initializer": CapabilitySelection(
                plugin="sage.workspace.initializer.claw", config={"language": settings.language},
            ),
        })
        capabilities["execution.scheduler"] = CapabilitySelection(
            plugin="sage.scheduler.ephemeral",
            config={
                "max_concurrent_runs": settings.max_concurrent_runs,
                "max_concurrent_runs_per_tenant": settings.max_concurrent_runs_per_user,
                "max_pending_items": settings.max_pending_runs,
            },
        )
    if settings is not None and settings.mysql_url:
        capabilities["session.store"] = CapabilitySelection(
            plugin=settings.session_store_plugin or ("sage.session.redis-mysql" if settings.redis_url else "sage.session.mysql"),
            config={
                "dsn": settings.mysql_url,
                "table_prefix": "",
                **({"redis_url": settings.redis_url} if settings.redis_url and settings.session_store_plugin != "sage.session.mysql" else {}),
                **({"key_prefix": settings.session_store_key_prefix} if settings.session_store_key_prefix else {}),
            },
        )
        if settings.scheduler_plugin == "sage.scheduler.redis-distributed":
            capabilities["execution.job-runtime"] = CapabilitySelection(
                plugin="sage.job.redis-distributed", config={"redis_url": settings.redis_url,
                    "key_prefix": distributed_runtime_prefix(settings, "jobs")})
            capabilities["execution.scheduler"] = CapabilitySelection(
                plugin="sage.scheduler.redis-distributed", config={
                    "redis_url": settings.redis_url,
                    "key_prefix": distributed_runtime_prefix(settings, "scheduler"),
                    "queue_id": "server", "lease_seconds": 30,
                    "max_concurrent_runs": settings.max_concurrent_runs,
                    "max_concurrent_runs_per_tenant": settings.max_concurrent_runs_per_user,
                    "max_pending_items": settings.max_pending_runs,
                })
    if settings is not None and settings.effective_trace_backend != "noop":
        config = {
            "environment": settings.trace_environment,
            "content_mode": settings.trace_content_mode or (
                "raw" if settings.effective_trace_backend == "phoenix" else "redacted"
            ),
            "max_content_chars": settings.trace_max_content_chars,
            "sample_rate": settings.trace_sample_rate,
            "timeout_seconds": settings.trace_timeout_seconds,
        }
        if settings.effective_trace_backend == "langfuse":
            config.update({
                "base_url": settings.langfuse_base_url,
                "service_name": settings.trace_service_name,
                "public_key_env": settings.langfuse_public_key_env,
                "secret_key_env": settings.langfuse_secret_key_env,
                "ingestion_version": settings.langfuse_ingestion_version,
            })
        elif settings.effective_trace_backend == "phoenix":
            config.update({
                "endpoint": settings.phoenix_endpoint,
                "service_name": settings.trace_service_name,
                "project_name": settings.phoenix_project_name,
                "api_key_env": settings.phoenix_api_key_env,
            })
        else:
            legacy_jaeger = not settings.trace_otlp_endpoint and bool(settings.jaeger_url)
            config.update({
                "endpoint": settings.trace_otlp_endpoint or settings.jaeger_url,
                "service_name": settings.jaeger_service_name if legacy_jaeger else settings.trace_service_name,
                "protocol": "grpc" if legacy_jaeger else settings.trace_otlp_protocol,
                "insecure": True if legacy_jaeger else settings.trace_otlp_insecure,
            })
        capabilities["observability.trace-sink"] = CapabilitySelection(
            plugin=f"sage.trace.{settings.effective_trace_backend}", config=config,
        )
    if settings is not None:
        capabilities.update({
            key: CapabilitySelection.model_validate(value)
            for key, value in settings.plugin_overrides.items()
        })
        trace = capabilities["observability.trace-sink"]
        if trace.plugin == "sage.trace.phoenix" and "content_mode" not in trace.config:
            capabilities["observability.trace-sink"] = trace.model_copy(update={
                "config": {**trace.config, "content_mode": settings.trace_content_mode or "raw"},
            })
    return capabilities
