"""The only selectable observation capability and its backend implementations."""

from .provider import ObservabilityConfig, create_observability_provider
from .plugins._shared.otlp_transport import otel_available
from .plugins.langfuse import langfuse_available
from .plugins.phoenix import phoenix_available
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionAvailability,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)


def register_observability_plugins(registry):
    common = {
        name for name in ObservabilityConfig.model_fields if name.startswith("log_")
    }
    common |= {"diagnostic_content_mode"}
    trace = {
        "service_name",
        "environment",
        "content_mode",
        "max_content_chars",
        "sample_rate",
        "max_queue_size",
        "max_active_spans",
        "timeout_seconds",
    }
    query = {"query_url", "query_headers_env"}
    for backend, title, fields, availability in (
        ("noop", "关闭观测", set(), True),
        (
            "local",
            "本地观测",
            common | {"diagnostics_root", "diagnostics_storage"},
            True,
        ),
        (
            "otlp",
            "OTLP / Jaeger 观测",
            common
            | trace
            | query
            | {"endpoint", "protocol", "insecure", "query_backend"},
            otel_available(),
        ),
        (
            "langfuse",
            "Langfuse 观测",
            common
            | trace
            | {"base_url", "public_key_env", "secret_key_env", "ingestion_version"},
            langfuse_available(),
        ),
        (
            "phoenix",
            "Phoenix 观测",
            common | trace | query | {"endpoint", "project_name", "api_key_env"},
            phoenix_available(),
        ),
    ):
        schema = ObservabilityConfig.model_json_schema()
        schema["properties"] = {
            key: value for key, value in schema["properties"].items() if key in fields
        }
        if backend != "noop":
            # Validate saved queue limits without advertising a queue setting in
            # the editor. The provider discards it when saving a new snapshot.
            schema["patternProperties"] = {
                "^raw_max_bytes$": {"type": "integer", "minimum": 4096}
            }
        if backend == "phoenix":
            schema["properties"]["endpoint"]["default"] = (
                "http://127.0.0.1:6006/v1/traces"
            )
        if backend == "local":
            schema["properties"]["diagnostic_content_mode"]["enum"] = [
                "off",
                "redacted",
            ]
        schema["required"] = (
            ["endpoint"]
            if backend == "phoenix"
            else ["base_url"]
            if backend == "langfuse"
            else []
        )
        plugin = f"sage.observability.{backend}"
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    plugin_id=plugin,
                    name=title,
                    version="2.0.0",
                    description="Unified log, trace and model evidence collection with owned lifecycle.",
                    provides=(
                        CapabilityOffer(
                            capability="observability.provider", api_version="2"
                        ),
                    ),
                    supported_scopes=frozenset({ExtensionScope.PROCESS}),
                    config_schema=schema,
                    availability=ExtensionAvailability(
                        available=availability,
                        reason=None
                        if availability
                        else "optional OpenTelemetry exporter packages are required",
                    ),
                    capabilities={
                        "exports_otlp": backend not in {"noop", "local"},
                        "supports_evidence_query": backend
                        in {"local", "phoenix", "otlp"},
                    },
                    built_in=True,
                ),
                factory=lambda context, deps, plugin=plugin: (
                    create_observability_provider(plugin, context.config)
                ),
            )
        )
