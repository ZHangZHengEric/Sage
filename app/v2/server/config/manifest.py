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
from app.v2.server.runtime.official import resolve_agent_tools


def server_v2_run_manifest(
    settings: ServerSettings | None = None,
    *,
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
            tools = tuple(agent.tools)
    selected_tools = list(resolve_agent_tools(tools, has_skills=bool(skills)))
    base = server_v2_manifest(settings)
    source = base.agents.get("main") or next(iter(base.agents.values()))
    composed = source.model_copy(
        update={
            "name": name or source.name,
            "description": agent.description
            if agent is not None
            else source.description,
            "skills": tuple(skills),
            "tools": tuple(selected_tools),
            "instructions": Instructions(
                inline=instructions
                or source.instructions.inline
                or "Be helpful, concise, and explicit about uncertainty."
            ),
        }
    )
    return base.model_copy(
        update={
            "agents": {agent_id: composed},
            "entrypoint": ApplicationEntrypoint(agent=agent_id),
        }
    )


def server_v2_manifest(settings: ServerSettings | None = None) -> SageManifest:
    """In-process package: no yaml, no env credentials, no model routes.

    The live model is injected by ``SAgentBuilder.with_model_provider``.
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
    return {"session.store": store}


def _runtime_capabilities(
    settings: ServerSettings | None,
) -> dict[str, CapabilitySelection]:
    log_level = settings.log_level if settings is not None else "info"
    log_format = settings.log_format if settings is not None else "json"
    capabilities: dict[str, CapabilitySelection] = {
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
            plugin="sage.session.mysql",
            config={
                "dsn": settings.mysql_url,
                "table_prefix": "",
            },
        )
    if settings is not None and settings.effective_trace_backend != "noop":
        config = {
            "environment": settings.trace_environment,
            "content_mode": settings.trace_content_mode,
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
    return capabilities
