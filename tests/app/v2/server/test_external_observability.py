import json
from datetime import datetime, timezone

import httpx
import pytest

from app.v2.server.observability.external import (
    ExternalDiagnostics,
    external_diagnostics,
)
from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord
from tests.app.v2.server.test_performance import BASE, sample


class TraceCapture:
    def __init__(self):
        self.spans = []

    def start_span(self, span):
        pass

    def add_event(self, span_id, event):
        pass

    def end_span(self, span):
        self.spans.append(span)


def capture_sample(sink):
    events, models = sample()
    sink.emit(
        "model", {**models[0], "completed_at": models[0]["ended_at"]}, at=BASE + 6
    )
    for row in events:
        sink.write(
            LogRecord(
                timestamp=datetime.fromtimestamp(row["at"], timezone.utc),
                level=LogLevel.INFO,
                component="test",
                event=row["event"],
                message="private text",
                session_id="s",
                run_id="r",
                tool_call_id=row["identity"],
                request_id=row["identity"],
                attributes={
                    "started_at": row["started_at"],
                    "agent_id": "agent",
                    "purpose": row["purpose"],
                    "run_state": row["state"],
                    "password": "private",
                },
            )
        )



def phoenix_span(span):
    return {
        "name": span.name,
        "context": {"trace_id": span.trace_id, "span_id": span.span_id},
        "attributes": {**span.attributes, "session_id": span.session_id, "run_id": span.run_id},
        "events": [e.model_dump(mode="json") for e in span.events],
        "start_time": span.start_time.isoformat(),
    }


@pytest.mark.asyncio
async def test_external_timing_roundtrip_without_local_files(tmp_path):
    capture = TraceCapture()
    sink = ExternalDiagnostics(
        backend="phoenix", query_url="http://phoenix", project="sage"
    )
    sink.trace_sink = capture
    capture_sample(sink)
    assert capture.spans
    assert "private" not in json.dumps([s.attributes for s in capture.spans])
    assert len({s.trace_id for s in capture.spans}) == 1
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.path == "/v1/projects/sage/spans"
        return httpx.Response(
            200,
            json={
                "data": [phoenix_span(s) for s in capture.spans],
                "next_cursor": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await sink.report(start=BASE, end=BASE + 100, client=client)
    assert result["summary"]["total_ms"]["p50"] == 10000
    assert result["summary"]["first_text_ms"]["p50"] == 4000
    assert result["summary"]["framework_ms"]["p50"] == 4000
    assert result["source"] == "phoenix"
    assert not list(tmp_path.iterdir())
    assert any(any(v.startswith("run_id:") for v in r.url.params.get_list("attribute")) for r in requests)


@pytest.mark.asyncio
async def test_external_failure_does_not_use_local_history(tmp_path):
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await sink.report(start=BASE, end=BASE + 100, client=client)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend,options",
    [
        (
            "phoenix",
            {
                "trace_backend": "phoenix",
                "phoenix_endpoint": "http://phoenix/v1/traces",
            },
        ),
        ("jaeger", {"jaeger_url": "http://jaeger:4317"}),
    ],
)
async def test_host_external_backend_does_not_create_diagnostic_database(
    tmp_path, backend, options
):
    from tests.app.v2.server.conftest import make_test_service

    host = make_test_service(tmp_path, **options)
    await host.start()
    try:
        assert isinstance(host.diagnostics, ExternalDiagnostics)
        assert host.diagnostics.backend == backend
        assert not (host.paths.runtime_root / "diagnostics").exists()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_jaeger_v3_stream_and_partial_model_updates_keep_timing_parity():
    capture = TraceCapture()
    sink = ExternalDiagnostics(backend="jaeger", query_url="http://jaeger")
    sink.trace_sink = capture
    capture_sample(sink)

    def handle(request):
        assert request.url.path == "/api/v3/traces"
        assert request.url.params["query.service_name"] == "sage-server"
        if "run_id" not in json.loads(request.url.params["query.attributes"]):
            assert request.url.params["query.start_time_min"].startswith("2026-10-19")
        else:
            assert request.url.params["query.start_time_min"].startswith("1970-01-01")
        spans = [
            {
                "traceId": s.trace_id,
                "spanId": s.span_id,
                "name": s.name,
                "startTimeUnixNano": str(int(s.start_time.timestamp() * 1e9)),
                "attributes": [
                    {"key": k, "value": {"stringValue": v}}
                    for k, v in {**s.attributes, "run_id": s.run_id, "session_id": s.session_id}.items()
                ],
            }
            for s in capture.spans
        ]
        return httpx.Response(
            200,
            text="\n".join(
                json.dumps(
                    {
                        "result": {
                            "resourceSpans": [
                                {"scopeSpans": [{"spans": spans[i : i + 2]}]}
                            ]
                        }
                    }
                )
                for i in range(0, len(spans), 2)
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await sink.report(start=BASE, end=BASE + 100, client=client)
    assert result["summary"]["total_ms"]["p50"] == 10000
    assert result["summary"]["framework_ms"]["p50"] == 4000
    assert result["source"] == "jaeger"


@pytest.mark.asyncio
async def test_phoenix_paginates_and_fetches_completion_outside_selected_window():
    capture = TraceCapture()
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    sink.trace_sink = capture
    capture_sample(sink)
    rows = [phoenix_span(s) for s in capture.spans]
    calls = []

    def handle(request):
        params = request.url.params
        calls.append(params)
        if "start_time" in params:
            return httpx.Response(200, json={"data": rows[:1], "next_cursor": None})
        assert "end_time" not in params
        page = rows[3:] if params.get("cursor") else rows[:3]
        return httpx.Response(
            200,
            json={
                "data": page,
                "next_cursor": None if params.get("cursor") else "page-2",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await sink.report(start=BASE, end=BASE + 5, client=client)
    assert result["summary"]["total_ms"]["p50"] == 10000
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_snapshot_filters_session_and_authoritative_run_allowlist(monkeypatch):
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")

    async def query(client, **kwargs):
        assert kwargs["session_id"] == "s"
        return [
            {
                "attributes": {"session_id": "s", "run_id": "r"},
                "name": "model.request",
                "start_time": BASE,
            },
            {
                "attributes": {"session_id": "s", "run_id": "not-allowed"},
                "start_time": BASE,
            },
            {"attributes": {"session_id": "other", "run_id": "r"}, "start_time": BASE},
        ], False

    monkeypatch.setattr(sink, "_query", query)
    result = await sink.snapshot("s", {"r"})
    assert len(result["traces"]) == 1
    assert result["raw_model_streams_available"] is False
    assert result["source"] == "phoenix"


def test_effective_plugin_and_query_auth_configuration(tmp_path, monkeypatch):
    from tests.app.v2.server.conftest import make_settings
    from app.v2.server.config.manifest import server_v2_manifest

    settings = make_settings(
        tmp_path, trace_backend="phoenix", phoenix_endpoint="http://internal/v1/traces"
    )
    selection = server_v2_manifest(settings).runtime.capabilities[
        "observability.trace-sink"
    ]
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Basic%20encoded"
    )
    sink = external_diagnostics(settings, selection)
    assert sink.query_url == "http://internal"
    assert sink.headers == {"Authorization": "Basic encoded"}
    assert (
        external_diagnostics(
            settings, selection.model_copy(update={"plugin": "sage.trace.noop"})
        )
        is None
    )


def test_external_performance_api_and_failure_do_not_read_local_db(
    client, service, monkeypatch
):
    from tests.app.v2.server.test_admin import admin_login

    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    service.diagnostics = sink
    calls = []

    async def report(**kwargs):
        calls.append(kwargs)
        return {"summary": {}, "source": "phoenix"}

    monkeypatch.setattr(sink, "report", report)
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    response = client.get("/api/observability/performance", headers=admin)
    assert response.status_code == 200
    assert response.json()["data"]["source"] == "phoenix"
    assert len(calls) == 1

    async def fail(**kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(sink, "report", fail)
    assert (
        client.get("/api/observability/performance", headers=admin).status_code == 503
    )


@pytest.mark.parametrize("content_mode", ["redacted", "raw"])
def test_real_run_exports_remote_performance_and_download_without_local_capture(
    tmp_path, monkeypatch, content_mode
):
    from fastapi.testclient import TestClient
    from io import BytesIO
    from zipfile import ZipFile
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_agui_chat import _run_input
    from tests.app.v2.server.test_file_downloads import identity
    from tests.app.v2.server.test_admin import admin_login

    exporter = InMemorySpanExporter()
    original = PhoenixTraceSink.__init__

    def initialize(self, **kwargs):
        original(self, **kwargs, exporter=exporter)

    monkeypatch.setattr(PhoenixTraceSink, "__init__", initialize)
    host = make_test_service(
        tmp_path, trace_backend="phoenix", phoenix_endpoint="http://unused/v1/traces", trace_content_mode=content_mode
    )
    with TestClient(create_app(service=host)) as client:
        user, _ = identity(client, "external-user")
        response = client.post("/api/agent", json=_run_input(), headers=user)
        assert response.status_code == 200, response.text
        import asyncio

        async def settle():
            async with asyncio.timeout(10):
                while host.execution._drives:
                    await asyncio.sleep(0.01)

        client.portal.call(settle)
        spans = exporter.get_finished_spans()
        assert any(s.name == "model.request" for s in spans)
        summaries = [s for s in spans if s.name == "sage.performance"]
        assert len(summaries) == 1
        agent = next(s for s in spans if s.name == "agent.run")
        assert summaries[0].context.trace_id == agent.context.trace_id
        assert summaries[0].parent.span_id == agent.context.span_id
        assert all(s.name != "sage.diagnostic" for s in spans)

        async def query(client, **kwargs):
            return [
                {
                    "name": s.name,
                    "start_time": s.start_time / 1e9,
                    "attributes": dict(s.attributes),
                    "events": [{"name": e.name, "timestamp": e.timestamp / 1e9, "attributes": dict(e.attributes)} for e in s.events],
                    "context": {
                        "trace_id": format(s.context.trace_id, "032x"),
                        "span_id": format(s.context.span_id, "016x"),
                    },
                }
                for s in spans
            ], False

        monkeypatch.setattr(host.diagnostics, "_query", query)
        admin = {"Authorization": f"Bearer {admin_login(client)}"}
        response = client.get("/api/observability/performance", headers=admin)
        assert response.status_code == 200, response.text
        report = response.json()["data"]
        assert report["summary"]["measured"] == 1
        assert report["summary"]["first_text_ms"]["p50"] is not None
        assert report["summary"]["framework_ms"]["p50"] is not None
        assert report["source"] == "phoenix"
        response = client.get("/api/threads/thread-1/download", headers=admin)
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("thread-1/manifest.json"))
            assert manifest["diagnostic_source"] == "phoenix"
            assert manifest["model_request_coverage"] == "external_traces_only"
            assert json.loads(archive.read("thread-1/traces.json"))
            if content_mode == "raw":
                models = json.loads(archive.read("thread-1/models.json"))
                assert models and any(row.get("response", {}).get("text") == "hello" for row in models)
                assert any("normalized_events" in row.get("stream", {}) for row in models)
        assert not (host.paths.runtime_root / "diagnostics").exists()
        assert (
            client.get("/api/threads/thread-1/download", headers=user).status_code
            == 403
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"trace_backend": "langfuse", "langfuse_base_url": "https://lf.example"},
    {"trace_backend": "otlp", "trace_otlp_endpoint": "http://collector:4317"},
])
async def test_export_only_backends_do_not_fallback_to_local_capture(tmp_path, monkeypatch, options):
    from tests.app.v2.server.conftest import make_test_service
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    host = make_test_service(tmp_path, **options)
    await host.start()
    try:
        assert host.diagnostics.available is False
        with pytest.raises(NotImplementedError):
            await host.diagnostics.export_evidence("s", {"r"})
        assert not (host.paths.runtime_root / "diagnostics").exists()
    finally:
        await host.close()


@pytest.mark.parametrize("outcome,expected", [("ok", 200), ("unsupported", 409), ("offline", 503)])
def test_download_queries_observation_capability_after_authorization(client, service, monkeypatch, outcome, expected):
    from io import BytesIO
    from zipfile import ZipFile
    from tests.app.v2.server.test_file_downloads import identity
    from tests.app.v2.server.test_agui_chat import _run_input
    from tests.app.v2.server.test_session_diagnostics import admin_headers

    alice, _ = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    calls = []

    async def export_evidence(session_id, run_ids):
        calls.append((session_id, run_ids))
        assert session_id == "thread-1"
        assert run_ids
        if outcome == "unsupported":
            raise NotImplementedError
        if outcome == "offline":
            raise httpx.ConnectError("upstream unavailable")
        return {"source": "phoenix", "models": [], "logs": [], "traces": [],
                "tools": [], "failures": [], "truncated": True}

    monkeypatch.setattr(service.diagnostics, "export_evidence", export_evidence)
    # No diagnostic query is made for a non-admin.
    assert client.get("/api/threads/thread-1/download", headers=alice).status_code == 403
    assert calls == []
    response = client.get("/api/threads/thread-1/download", headers=admin_headers(client))
    assert response.status_code == expected
    assert len(calls) == 1
    if expected == 200:
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("thread-1/manifest.json"))
            assert manifest["format_version"].endswith("/v2")
            assert manifest["diagnostic_source"] == "phoenix"
            assert manifest["external_traces_truncated"] is True
            assert "thread-1/state.json" not in archive.namelist()


def test_performance_events_collapse_to_one_linked_summary_per_execution():
    from sagents.v2.runtime.observability.traces import StructuredTracer
    trace = TraceCapture()
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    sink.trace_sink = trace
    parent = StructuredTracer(trace, "test").start_span("agent.run", session_id="s", run_id="r")
    capture_sample(sink)
    parent.end()
    summaries = [s for s in trace.spans if s.name == "sage.performance"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.trace_id == parent.span.trace_id
    assert summary.parent_span_id == parent.span.span_id
    assert summary.attributes["sage.performance.total_ms"] == 10000
    assert summary.attributes["sage.performance.first_text_ms"] == 4000
    assert summary.attributes["sage.performance.framework_ms"] == 4000
    assert len(summary.events) == 8
    assert not sink._performance


@pytest.mark.asyncio
async def test_shutdown_flushes_unfinished_performance_as_incomplete():
    trace = TraceCapture()
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    sink.trace_sink = trace
    sink.emit("log", {"session_id":"s", "run_id":"r", "event":"agent.run.started", "timestamp":BASE}, at=BASE)
    assert trace.spans == []
    await sink.close()
    assert len(trace.spans) == 1
    assert trace.spans[0].attributes["sage.performance.incomplete"]
    assert "sage.performance.total_ms" not in trace.spans[0].attributes


@pytest.mark.asyncio
async def test_resume_segments_are_loaded_across_execution_traces(monkeypatch):
    from sagents.v2.runtime.observability.traces import StructuredTracer
    from app.v2.server.observability.external import timing_rows
    trace = TraceCapture()
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    sink.trace_sink = trace
    parent = StructuredTracer(trace, "test").start_span("agent.run", session_id="s", run_id="r")
    capture_sample(sink)
    parent.end()
    second = StructuredTracer(trace, "test").start_span("agent.run", session_id="s", run_id="r")
    for at, event, attrs in [
        (100, "server.run.performance.resuming", {"started_at": BASE + 100}),
        (102, "agent.run.started", {}), (109, "agent.run.completed", {}),
        (110, "server.run.performance.finished", {"run_state": "completed"}),
    ]:
        sink.emit("log", {"session_id":"s", "run_id":"r", "event":event,
                          "timestamp":BASE + at, "attributes":attrs}, at=BASE + at)
    second.end()
    summaries = [phoenix_span(s) for s in trace.spans if s.name == "sage.performance"]
    assert len(summaries) == 2 and summaries[0]["context"]["trace_id"] != summaries[1]["context"]["trace_id"]
    calls = []
    async def query(client, params):
        calls.append(params)
        if any(key == "start_time" for key, value in params):
            return summaries[:1], False
        assert ("attribute", 'run_id:"r"') in params
        return summaries, False
    monkeypatch.setattr(sink, "_phoenix", query)
    async with httpx.AsyncClient() as client:
        spans, cut = await sink._query(client, start=BASE, end=BASE + 10)
    assert len(calls) == 2 and not cut
    events, _ = timing_rows(spans)
    assert len([e for e in events["r"] if e["event"] == "agent.run.started"]) == 2
    assert any(e["event"] == "server.run.performance.resuming" for e in events["r"])


@pytest.mark.asyncio
async def test_diagnostic_events_cannot_escape_the_authorized_run(monkeypatch):
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    async def query(client, **options):
        return [{"name":"agent.run", "start_time":BASE,
                 "attributes":{"session_id":"s", "run_id":"r"},
                 "events":[{"timestamp":BASE, "attributes":{
                     "session_id":"other", "run_id":"r", "sage.diagnostic.kind":"log",
                     "sage.diagnostic.data":json.dumps({"message":"private"})}}]}], False
    monkeypatch.setattr(sink, "_query", query)
    evidence = await sink.snapshot("s", {"r"})
    assert evidence["logs"] == [] and evidence["models"] == []


@pytest.mark.asyncio
async def test_download_projects_model_spans_when_raw_diagnostics_were_not_captured(monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile
    from app.v2.server.storage.downloads import prepare_session_export
    from tests.sagents.v2.test_model_evidence import span
    sink = ExternalDiagnostics(backend="phoenix", query_url="http://phoenix")
    async def query(client, **options):
        return [span()], False
    monkeypatch.setattr(sink, "_query", query)
    evidence = await sink.snapshot("s", {"r"})
    assert len(evidence["models"]) == 1 and evidence["logs"] == []
    stream, _ = prepare_session_export("s", {"r"}, evidence)
    with stream, ZipFile(BytesIO(stream.read())) as archive:
        models = json.loads(archive.read("s/models.json"))
        index = json.loads(archive.read("s/requests/index.json"))
        manifest = json.loads(archive.read("s/manifest.json"))
        assert models[0]["response"]["text"] == "answer"
        assert index[0]["evidence_source"] == "trace_projection"
        assert len(index) == 1 and index[0]["path"] in {n.removeprefix("s/") for n in archive.namelist()}
        assert not manifest["model_request_ids_missing"]
        assert manifest["stream_evidence_missing_for_requests"] == ["m"]
        assert manifest["evidence_availability"]["models"]["status"] == "partial"
        assert manifest["evidence_availability"]["logs"]["status"] == "not_captured"
        assert manifest["evidence_availability"]["raw_model_streams"]["status"] == "not_captured"
