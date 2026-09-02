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

from app.server_v2.core.settings import ServerV2Settings


def server_v2_manifest(settings: ServerV2Settings | None = None) -> SageManifest:
    """In-process package: no yaml, no env credentials, no model routes.

    The live model is injected by ``SAgentBuilder.with_model_provider``.
    Host backends (stdout logs, MySQL session, Jaeger OTLP) are selected here
    and passed as plugin config; plugins themselves do not read environment
    variables.
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
            )
        },
    )


def _required_guarantees(
    settings: ServerV2Settings | None,
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
    settings: ServerV2Settings | None,
) -> dict[str, CapabilitySelection]:
    log_level = settings.log_level if settings is not None else "info"
    log_format = settings.log_format if settings is not None else "json"
    capabilities: dict[str, CapabilitySelection] = {
        "observability.log-sink": CapabilitySelection(
            plugin="sage.logging.stdout",
            config={
                "stream": "stdout",
                "min_level": log_level,
                "format": log_format,
            },
        )
    }
    if settings is not None and settings.mysql_url:
        capabilities["session.store"] = CapabilitySelection(
            plugin="sage.session.mysql",
            config={
                "dsn": settings.mysql_url,
                "table_prefix": "",
            },
        )
    if settings is not None and settings.jaeger_url:
        capabilities["observability.trace-sink"] = CapabilitySelection(
            plugin="sage.trace.otlp",
            config={
                "endpoint": settings.jaeger_url,
                "service_name": settings.jaeger_service_name,
                "protocol": "grpc",
                "insecure": True,
            },
        )
    return capabilities
