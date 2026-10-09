"""Validate exported data, identity, isolation and exporter failure boundaries."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sagents.v2.contracts.items import TextBlock, UsageSummary
from sagents.v2.model import ModelRequest, RecordingModelProvider
from sagents.v2.model.contracts import (
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
    ModelEventKind,
)
from sagents.v2.runtime.observability import (
    NoopDiagnosticSink,
    StructuredTracer,
    TraceSpan,
)
from sagents.v2.runtime.observability.content import trace_content
from sagents.v2.runtime.observability.plugins.otlp import OtlpTraceSink
from sagents.v2.runtime.observability.plugins.langfuse import LangfuseTraceSink
from sagents.v2.runtime.observability.traces import current_trace_context
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


def make_sink(kind="otlp", **options):
    exporter = options.pop("exporter", InMemorySpanExporter())
    if kind == "langfuse":
        sink = LangfuseTraceSink(
            base_url="http://localhost:3000",
            public_key="pk-test",
            secret_key="sk-test-secret",
            exporter=exporter,
            **options,
        )
    else:
        sink = OtlpTraceSink(exporter=exporter, **options)
    return sink, exporter


def request():
    return ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="fast",
        messages=(ModelMessage(role="user", content=(TextBlock(text="hello"),)),),
        temperature=0.2,
        max_output_tokens=100,
    )


@pytest.mark.parametrize("kind", ["otlp", "langfuse"])
def test_export_preserves_root_remote_and_ended_parent_ids(kind):
    sink, exporter = make_sink(kind)
    root = TraceSpan(trace_id="1" * 32, span_id="2" * 16, name="agent.run")
    child = TraceSpan(
        trace_id=root.trace_id,
        span_id="3" * 16,
        parent_span_id=root.span_id,
        name="model.request",
    )
    sink.start_span(root)
    sink.end_span(root)
    sink.start_span(child)
    sink.end_span(child)
    remote = child.model_copy(update={"span_id": "4" * 16, "parent_span_id": "5" * 16})
    sink.start_span(remote)
    sink.end_span(remote)
    spans = exporter.get_finished_spans()
    assert spans[0].parent is None
    assert spans[0].context.trace_id == int(root.trace_id, 16)
    assert spans[0].context.span_id == int(root.span_id, 16)
    assert spans[1].parent.span_id == int(root.span_id, 16)
    assert spans[2].parent.span_id == int(remote.parent_span_id, 16)
    sink.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["otlp", "langfuse"])
async def test_complete_generation_contains_content_usage_and_first_token(kind):
    sink, exporter = make_sink(kind)
    response = ModelResponse(
        response_id="response",
        text="answer",
        finish_reason="stop",
        usage=UsageSummary(
            reported=True,
            input_tokens=100,
            output_tokens=30,
            cached_input_tokens=40,
            reasoning_tokens=10,
            cost=0.01,
        ),
        provider_metadata={"model": "actual-model", "provider_id": "provider"},
    )
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.REASONING_DELTA, delta="thinking"
                    ),
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="answer"),
                    ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response),
                )
            ),
        )
    )

    async def session(_):
        return "session"

    model = RecordingModelProvider(
        provider,
        sink=NoopDiagnosticSink(),
        trace_sink=sink,
        session_id_resolver=session,
    )
    parent = StructuredTracer(sink, "test").start_span(
        "agent.run",
        session_id="session",
        correlation_id="req-http",
        attributes={"user_id": "user", "root_session_id": "session"},
    )
    events = [event async for event in model.stream(request())]
    parent.end()
    assert events[-1].response == response
    generation = next(
        span for span in exporter.get_finished_spans() if span.name == "model.request"
    )
    attrs = generation.attributes
    assert generation.parent.span_id == int(parent.span.span_id, 16)
    assert attrs["gen_ai.request.model"] == "actual-model"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.cached_input_tokens"] == 40
    assert json.loads(attrs["input"])["messages"][0]["content"][0]["text"] == "hello"
    assert json.loads(attrs["output"])["text"] == "answer"
    assert attrs["completion_start_time"]
    assert attrs["correlation_id"] == "req-http"
    if kind == "langfuse":
        assert attrs["langfuse.observation.type"] == "generation"
        assert attrs["langfuse.user.id"] == "user"
        assert attrs["langfuse.session.id"] == "session"
        usage = json.loads(attrs["langfuse.observation.usage_details"])
        assert sum(usage.values()) == 130
        assert usage["input_cached_tokens"] == 40
        assert usage["output_reasoning_tokens"] == 10
        assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.01}
    assert current_trace_context() is None
    sink.close()


@pytest.mark.asyncio
async def test_broken_diagnostics_does_not_break_model_or_trace():
    class BrokenDiagnostics:
        async def begin_model_request(self, **kwargs):
            raise OSError("disk full")

        complete_model_request = begin_model_request
        record_model_first_token = begin_model_request
        fail_model_request = begin_model_request

    sink, exporter = make_sink()

    async def session(_):
        return "session"

    model = RecordingModelProvider(
        ScriptedModelProvider(
            (
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED,
                            response=ModelResponse(
                                response_id="r", text="ok", finish_reason="stop"
                            ),
                        ),
                    )
                ),
            )
        ),
        sink=BrokenDiagnostics(),
        trace_sink=sink,
        session_id_resolver=session,
    )
    events = [event async for event in model.stream(request())]
    assert events[-1].response.text == "ok"
    assert len(exporter.get_finished_spans()) == 1
    assert current_trace_context() is None
    sink.close()


@pytest.mark.asyncio
async def test_concurrent_traces_do_not_share_parent_or_user():
    sink, exporter = make_sink("langfuse")

    async def run(user):
        parent = StructuredTracer(sink, "test").start_span(
            "agent.run", attributes={"user_id": user}
        )
        await asyncio.sleep(0)
        child = StructuredTracer(sink, "test").start_span("model.request")
        await asyncio.sleep(0)
        child.end()
        parent.end()

    await asyncio.gather(run("one"), run("two"))
    spans = exporter.get_finished_spans()
    for user in ("one", "two"):
        selected = [s for s in spans if s.attributes["langfuse.user.id"] == user]
        assert len(selected) == 2
        assert selected[0].parent.span_id == selected[1].context.span_id
    assert len({span.context.trace_id for span in spans}) == 2
    assert current_trace_context() is None
    sink.close()


@pytest.mark.parametrize("mode", ["redacted", "metadata"])
def test_content_policy_redacts_media_and_signed_urls_and_bounds_json(mode):
    sink, exporter = make_sink("langfuse", content_mode=mode, max_content_chars=512)
    content = {
        "api_key": "credential-value",
        "url": "https://user:pass@host/image?signature=signed-secret",
        "media": "data:image/png;base64,abc123",
        "data": "base64blob",
        "text": "Bearer abc-token",
    }
    handle = StructuredTracer(sink, "test").start_span(
        "tool.call", attributes={"input": trace_content(sink, content)}
    )
    handle.end(attributes={"output": trace_content(sink, "x" * 2000)})
    attrs = exporter.get_finished_spans()[0].attributes
    encoded = json.dumps(dict(attrs))
    for secret in (
        "credential-value",
        "user:pass",
        "signed-secret",
        "abc123",
        "base64blob",
        "abc-token",
    ):
        assert secret not in encoded
    if mode == "metadata":
        assert "langfuse.observation.input" not in attrs
        assert "langfuse.observation.output" not in attrs
    else:
        assert (
            json.loads(attrs["langfuse.observation.input"])["url"]
            == "https://host/image"
        )
        assert json.loads(attrs["langfuse.observation.output"])["truncated"] is True
    sink.close()


def test_export_failure_is_counted_and_never_raised(caplog):
    class BrokenExporter:
        def export(self, spans):
            raise RuntimeError("Authorization: sensitive-secret")

        def shutdown(self):
            pass

    sink, _ = make_sink(exporter=BrokenExporter())
    for _ in range(2):
        StructuredTracer(sink, "test").start_span("agent.run").end()
    assert sink.failed_exports == 2
    assert sink.dropped_spans == 2
    assert "sensitive-secret" not in caplog.text
    assert caplog.text.count("trace export degraded") == 1
    sink.close()


def test_sampling_and_active_limit_are_bounded():
    sink, exporter = make_sink(sample_rate=0)
    parent = StructuredTracer(sink, "test").start_span("agent.run")
    StructuredTracer(sink, "test").start_span("model.request").end()
    parent.end()
    assert exporter.get_finished_spans() == ()
    assert sink._spans == {}
    sink.close()
    sink, exporter = make_sink(max_active_spans=1)
    parent = StructuredTracer(sink, "test").start_span("agent.run")
    StructuredTracer(sink, "test").start_span("model.request").end()
    parent.end()
    assert sink.dropped_spans == 1
    sink.close()


def test_real_http_export_uses_langfuse_endpoint_auth_and_protobuf():
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    {key.lower(): value for key, value in self.headers.items()},
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        sink = LangfuseTraceSink(
            base_url=f"http://127.0.0.1:{server.server_port}",
            public_key="pk-test",
            secret_key="sk-test",
            timeout_seconds=2,
        )
        root = StructuredTracer(sink, "test").start_span(
            "agent.run", session_id="session"
        )
        root.end()
        sink.close()
        assert sink.failed_exports == 0
        path, headers, body = received[0]
        assert path == "/api/public/otel/v1/traces"
        assert headers["authorization"] == "Basic cGstdGVzdDpzay10ZXN0"
        assert headers["x-langfuse-ingestion-version"] == "4"
        data = ExportTraceServiceRequest.FromString(body)
        exported = data.resource_spans[0].scope_spans[0].spans[0]
        assert exported.trace_id.hex() == root.span.trace_id
        assert exported.span_id.hex() == root.span.span_id
        assert not exported.parent_span_id
        assert exported.end_time_unix_nano >= exported.start_time_unix_nano
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


@pytest.mark.asyncio
async def test_execute_resume_and_cancel_have_distinct_traces_and_propagate_context():
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, setup_loop
    from sagents.v2.contracts.run_state import RunState

    sink, exporter = make_sink("langfuse")
    runtime, handle, loop, _ = await setup_loop(
        ScriptedModelProvider(()), trace_sink=sink
    )
    contexts = []

    async def body(run_id, context):
        contexts.append(context)
        state = RunState.SUSPENDED if len(contexts) == 1 else RunState.CANCELLED
        return (await runtime.get_run(run_id)).model_copy(update={"state": state})

    await loop._observe_run(handle.run_id, CONTEXT, resumed=False, body=body)
    await loop._observe_run(handle.run_id, CONTEXT, resumed=True, body=body)
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert spans[0].context.trace_id != spans[1].context.trace_id
    assert all(span.parent is None for span in spans)
    assert spans[0].attributes["run_state"] == "suspended"
    assert spans[1].attributes["run_state"] == "cancelled"
    assert spans[1].attributes["resumed"] is True
    assert spans[1].attributes["langfuse.observation.level"] == "WARNING"
    for context, span in zip(contexts, spans):
        assert int(context.trace.trace_id, 16) == span.context.trace_id
        assert int(context.trace.span_id, 16) == span.context.span_id
    assert current_trace_context() is None
    sink.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("provider failed"), asyncio.CancelledError()]
)
async def test_model_error_or_cancellation_closes_trace_and_preserves_exception(error):
    class Provider:
        async def stream(self, request):
            yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="partial")
            raise error

    sink, exporter = make_sink()

    async def session(_):
        return "session"

    model = RecordingModelProvider(
        Provider(),
        sink=NoopDiagnosticSink(),
        trace_sink=sink,
        session_id_resolver=session,
    )
    with pytest.raises(type(error)):
        [event async for event in model.stream(request())]
    assert len(exporter.get_finished_spans()) == 1
    assert sink._spans == {}
    assert current_trace_context() is None
    sink.close()


def test_close_is_bounded_when_exporter_shutdown_hangs():
    import time

    release = threading.Event()

    class Exporter(InMemorySpanExporter):
        def shutdown(self):
            release.wait(3)

    sink, _ = make_sink(exporter=Exporter(), timeout_seconds=0.05)
    try:
        started = time.monotonic()
        sink.close()
        assert time.monotonic() - started < 0.5
        sink.close()
    finally:
        release.set()


def test_slow_exporter_saturates_bounded_queue_without_blocking(monkeypatch):
    from opentelemetry.exporter.otlp.proto.http import trace_exporter
    from opentelemetry.sdk.trace.export import SpanExportResult

    started = threading.Event()
    release = threading.Event()

    class SlowExporter:
        def export(self, spans):
            started.set()
            release.wait(3)
            return SpanExportResult.SUCCESS

        def shutdown(self):
            pass

    monkeypatch.setattr(
        trace_exporter, "OTLPSpanExporter", lambda **kwargs: SlowExporter()
    )
    sink = OtlpTraceSink(protocol="http", max_queue_size=1, timeout_seconds=0.5)
    try:
        StructuredTracer(sink, "test").start_span("agent.run").end()
        assert started.wait(1)
        StructuredTracer(sink, "test").start_span("agent.run").end()
        assert sink.statistics()["dropped_spans"] == 1
        assert sink.statistics()["active_spans"] == 0
    finally:
        release.set()
        sink.close()
