"""Official generic OTLP trace projection."""

from sagents.v2.runtime.observability.otlp_transport import (
    OtlpTraceTransport,
    otel_available as otel_available,
)


class OtlpTraceSink(OtlpTraceTransport):
    plugin_id = "sage.trace.otlp"
    name = "OTLP / Jaeger trace sink"
    description = "Exports traces over OTLP to Jaeger or a compatible collector."
