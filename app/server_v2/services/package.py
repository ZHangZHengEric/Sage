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
    Host backends (MySQL session, Jaeger OTLP) are selected here and passed as
    plugin config; plugins themselves do not read environment variables.
    """

    return SageManifest(
        kind="application",
        metadata=ManifestMetadata(
            id="com.sage.server-v2",
            version="0.1.0",
            name="Sage Server v2",
        ),
        runtime=RuntimeConfig(capabilities=_runtime_capabilities(settings)),
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


def _runtime_capabilities(
    settings: ServerV2Settings | None,
) -> dict[str, CapabilitySelection]:
    capabilities: dict[str, CapabilitySelection] = {}
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
