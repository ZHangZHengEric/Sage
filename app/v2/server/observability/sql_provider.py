"""Default Server observation plugin using the host's database."""

from dataclasses import replace

from app.v2.server.runtime.sdk_plugins import service_registration
from sagents.v2.runtime.observability.provider import ObservabilityConfig, create_observability_provider

SQL_OBSERVABILITY_PLUGIN = "com.sage.server.observability-sql"


def sql_observability_registration(database):
    from .diagnostics import DatabaseDiagnostics

    schema = ObservabilityConfig.model_json_schema()
    schema["properties"] = {
        name: field for name, field in schema["properties"].items()
        if name.startswith("log_") or name == "diagnostic_content_mode"
    }
    schema["properties"]["diagnostic_content_mode"]["enum"] = ["off", "redacted"]
    registration = service_registration(
        "observability.provider", None, ownership="owned", config_schema=schema,
    )
    return replace(
        registration,
        descriptor=registration.descriptor.model_copy(update={
            "plugin_id": SQL_OBSERVABILITY_PLUGIN,
            "name": "Server SQL 观测",
            "capabilities": {"exports_otlp": False, "supports_evidence_query": True},
        }),
        factory=lambda context, deps: create_observability_provider(
            SQL_OBSERVABILITY_PLUGIN, context.config,
            local_diagnostics_factory=lambda: DatabaseDiagnostics(database),
        ),
    )
