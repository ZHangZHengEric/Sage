"""Langfuse projection over the shared OTLP transport."""

from __future__ import annotations

import base64
import importlib.util
import json
from typing import Any
from urllib.parse import urlsplit

from sagents.v2.runtime.observability.contracts import TraceSpan, TraceStatus
from sagents.v2.runtime.observability.otlp_transport import OtlpTraceTransport


def langfuse_available() -> bool:
    try:
        return (
            importlib.util.find_spec("opentelemetry.sdk.trace") is not None
            and importlib.util.find_spec(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter"
            )
            is not None
        )
    except ModuleNotFoundError:
        return False


class LangfuseTraceSink(OtlpTraceTransport):
    plugin_id = "sage.trace.langfuse"
    name = "Langfuse trace sink"
    description = "Exports Agent, model and tool observations to Langfuse."

    def __init__(
        self,
        *,
        base_url: str,
        public_key: str,
        secret_key: str,
        ingestion_version: int = 4,
        **options: Any,
    ) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.username
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Langfuse base_url must be an HTTP(S) URL without credentials, query or fragment"
            )
        if not public_key or not secret_key:
            raise ValueError(
                "Langfuse public and secret key environment variables must be set"
            )
        if ingestion_version not in {3, 4}:
            raise ValueError("Langfuse ingestion_version must be 3 or 4")
        authorization = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        headers = {"Authorization": f"Basic {authorization}"}
        if ingestion_version == 4:
            headers["x-langfuse-ingestion-version"] = "4"
        super().__init__(
            endpoint=f"{base_url.rstrip('/')}/api/public/otel/v1/traces",
            protocol="http",
            headers=headers,
            **options,
        )

    def _attributes(self, span: TraceSpan) -> dict[str, Any]:
        values = super()._attributes(span)
        values.update(
            {
                "langfuse.observation.type": {
                    "agent.run": "agent",
                    "model.request": "generation",
                    "tool.call": "tool",
                }.get(span.name, "span"),
                "langfuse.session.id": values.get("root_session_id") or span.session_id,
                "langfuse.user.id": values.get("user_id"),
                "langfuse.environment": self.environment,
                "langfuse.observation.input": values.get("input"),
                "langfuse.observation.output": values.get("output"),
                "langfuse.observation.level": "ERROR"
                if span.status is TraceStatus.ERROR
                else "WARNING"
                if values.get("run_state") == "cancelled"
                else "DEFAULT",
                "langfuse.observation.status_message": values.get("status_message"),
            }
        )
        for key in (
            "session_id",
            "root_session_id",
            "run_id",
            "turn_id",
            "step_id",
            "request_id",
            "correlation_id",
            "tool_call_id",
            "agent_id",
            "tenant_id",
            "purpose",
            "run_state",
            "resumed",
            "ttfb_ms",
            "first_text_ms",
        ):
            values[f"langfuse.observation.metadata.{key}"] = values.get(key)
        if span.error:
            from sagents.v2.runtime.observability.content import safe_trace_value

            values["langfuse.observation.status_message"] = safe_trace_value(
                span.error.message
            )
        if span.name == "model.request":
            values.update(
                {
                    "langfuse.observation.model.name": values.get("model"),
                    "langfuse.observation.model.parameters": values.get(
                        "model_parameters"
                    ),
                    "langfuse.observation.completion_start_time": values.get(
                        "completion_start_time"
                    ),
                }
            )
            usage = values.get("usage")
            if usage is not None:
                # Cache/reasoning are subsets in Sage. Export disjoint types so
                # Langfuse totals and per-type prices do not double count them.
                cached = min(usage["input_tokens"], usage.get("cached_input_tokens", 0))
                reasoning = min(
                    usage["output_tokens"], usage.get("reasoning_tokens", 0)
                )
                values["langfuse.observation.usage_details"] = json.dumps(
                    {
                        "input": usage["input_tokens"] - cached,
                        "input_cached_tokens": cached,
                        "output": usage["output_tokens"] - reasoning,
                        "output_reasoning_tokens": reasoning,
                    }
                )
            if values.get("cost") is not None:
                values["langfuse.observation.cost_details"] = json.dumps(
                    {"total": values["cost"]}
                )
        return values
