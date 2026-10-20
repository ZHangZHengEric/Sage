"""Phoenix wire format, project routing and content policy."""

import json

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sagents.v2.runtime.observability import StructuredTracer
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink


@pytest.mark.parametrize("content_mode", ["redacted", "metadata"])
def test_phoenix_agent_model_and_tool_projection(content_mode):
    exporter = InMemorySpanExporter()
    sink = PhoenixTraceSink(
        endpoint="http://localhost:6006/v1/traces",
        project_name="sage-test",
        exporter=exporter,
        content_mode=content_mode,
    )
    tracer = StructuredTracer(sink, "test")
    parent = tracer.start_span(
        "agent.run",
        session_id="child-session",
        attributes={"root_session_id": "root-session", "user_id": "user", "input": "hello"},
    )
    model_span = tracer.start_span(
        "model.request",
        attributes={
            "model": "actual-model",
            "provider": "openai",
            "input": {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]}
                ]
            },
            "output": {"text": "answer"},
            "model_parameters": {"temperature": 0.2},
            "usage": {
                "input_tokens": 100,
                "output_tokens": 30,
                "cached_input_tokens": 40,
                "reasoning_tokens": 10,
            },
            "cost": 0.01,
        },
    )
    model_span.end()
    tool_span = tracer.start_span(
        "tool.call",
        attributes={
            "tool_name": "lookup",
            "input": {"secret_key": "never-export-me", "query": "hello"},
            "output": "found",
        },
    )
    tool_span.end()
    parent.end(attributes={"output": "answer"})
    model, tool, agent = exporter.get_finished_spans()
    assert model.resource.attributes["openinference.project.name"] == "sage-test"
    assert model.attributes["openinference.span.kind"] == "LLM"
    assert agent.attributes["openinference.span.kind"] == "AGENT"
    assert agent.attributes["session.id"] == "root-session"
    assert model.attributes["user.id"] == "user"
    assert tool.attributes["openinference.span.kind"] == "TOOL"
    assert tool.attributes["tool.name"] == "lookup"
    assert model.parent.span_id == agent.context.span_id
    assert model.attributes["llm.model_name"] == "actual-model"
    assert model.attributes["llm.token_count.prompt"] == 100
    assert model.attributes["llm.token_count.completion"] == 30
    assert model.attributes["llm.token_count.total"] == 130
    assert model.attributes["llm.token_count.prompt_details.cache_read"] == 40
    assert model.attributes["llm.token_count.completion_details.reasoning"] == 10
    assert model.attributes["llm.cost.total"] == 0.01
    if content_mode == "metadata":
        assert "input.value" not in agent.attributes
        assert "output.value" not in agent.attributes
        assert "input.value" not in model.attributes
        assert "output.value" not in model.attributes
        assert "tool.parameters" not in tool.attributes
    else:
        assert json.loads(agent.attributes["input.value"]) == "hello"
        assert json.loads(agent.attributes["output.value"]) == "answer"
        assert json.loads(model.attributes["output.value"]) == {"text": "answer"}
        assert model.attributes["input.mime_type"] == "application/json"
        assert (
            json.loads(tool.attributes["tool.parameters"])["secret_key"] == "[REDACTED]"
        )
    assert "never-export-me" not in str(exporter.get_finished_spans())
    # Phoenix unflattens dotted attributes. A scalar `input`/`output` blocks
    # the corresponding OpenInference namespace, hiding content in its UI.
    for span in (model, tool, agent):
        assert "input" not in span.attributes
        assert "output" not in span.attributes
    sink.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://host/v1/traces",
        "http://user:pass@host/v1/traces",
        "http://host/v1/traces?key=secret",
        "http://host/v1/traces#fragment",
        "",
    ],
)
def test_phoenix_rejects_invalid_endpoint(endpoint):
    with pytest.raises(ValueError, match="endpoint"):
        PhoenixTraceSink(endpoint=endpoint)


def test_phoenix_does_not_invent_model_or_usage():
    exporter = InMemorySpanExporter()
    sink = PhoenixTraceSink(
        endpoint="http://localhost:6006/v1/traces", exporter=exporter
    )
    StructuredTracer(sink, "test").start_span("model.request").end()
    attrs = exporter.get_finished_spans()[0].attributes
    assert "llm.model_name" not in attrs
    assert not any(key.startswith("llm.token_count.") for key in attrs)
    sink.close()
