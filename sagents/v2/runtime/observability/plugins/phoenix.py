"""Phoenix OpenInference projection over the shared OTLP transport."""

from __future__ import annotations

import importlib.util
import json
from typing import Any
from urllib.parse import urlsplit

from sagents.v2.runtime.observability.contracts import TraceSpan
from sagents.v2.runtime.observability.plugins._shared.otlp_transport import (
    OtlpTraceTransport,
)


def phoenix_available() -> bool:
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


class PhoenixTraceSink(OtlpTraceTransport):
    plugin_id = "sage.trace.phoenix"
    name = "Phoenix trace sink"
    description = "Exports Agent, model and tool observations to Phoenix."

    def __init__(
        self,
        *,
        endpoint: str,
        project_name: str = "sage",
        api_key: str = "",
        **options: Any,
    ) -> None:
        self.validate_configuration(endpoint, project_name)
        super().__init__(
            endpoint=endpoint,
            protocol="http",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            resource_attributes={"openinference.project.name": project_name},
            **options,
        )

    @staticmethod
    def validate_configuration(endpoint: str, project_name: str = "sage") -> None:
        url = urlsplit(endpoint)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.username is not None
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Phoenix endpoint must be an HTTP(S) URL without credentials, query or fragment"
            )
        if not project_name.strip():
            raise ValueError("Phoenix project_name must be non-empty")

    def _attributes(self, span: TraceSpan) -> dict[str, Any]:
        values = super()._attributes(span)
        values.update(
            {
                "openinference.span.kind": {
                    "agent.run": "AGENT",
                    "model.request": "LLM",
                    "tool.call": "TOOL",
                }.get(span.name, "CHAIN"),
                "session.id": values.get("root_session_id") or span.session_id,
                "user.id": values.get("user_id"),
            }
        )
        for direction in ("input", "output"):
            if values.get(direction) is not None:
                values[f"{direction}.value"] = json.dumps(
                    values[direction], ensure_ascii=False
                )
                values[f"{direction}.mime_type"] = "application/json"
        if span.name == "model.request":
            values.update(
                {
                    "llm.model_name": values.get("model"),
                    "llm.provider": values.get("provider"),
                    "llm.invocation_parameters": values.get("model_parameters"),
                    "llm.cost.total": values.get("cost"),
                }
            )
            usage = values.get("usage")
            if usage is not None:
                values.update(
                    {
                        "llm.token_count.prompt": usage["input_tokens"],
                        "llm.token_count.completion": usage["output_tokens"],
                        "llm.token_count.total": usage["input_tokens"]
                        + usage["output_tokens"],
                        "llm.token_count.prompt_details.cache_read": usage.get(
                            "cached_input_tokens"
                        ),
                        "llm.token_count.completion_details.reasoning": usage.get(
                            "reasoning_tokens"
                        ),
                    }
                )
        elif span.name == "tool.call":
            values["tool.name"] = values.get("tool_name")
            values["tool.parameters"] = values.get("input")
        # Scalar keys shadow Phoenix's nested OpenInference input/output fields.
        values.pop("input", None)
        values.pop("output", None)
        return values
