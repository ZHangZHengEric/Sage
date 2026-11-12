"""API key chat uses the same semantic observations as browser chat."""

import asyncio
import json

import pytest

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.v2.server.main import create_app
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink
from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.test_external_chat import setup_agent, send


@pytest.mark.parametrize("project", [False, True])
def test_api_chat_exports_semantic_spans_without_diagnostic_chunks(
    tmp_path, monkeypatch, project
):
    exporter = InMemorySpanExporter()
    original = PhoenixTraceSink.__init__

    def initialize(self, **options):
        original(self, **options, exporter=exporter)

    monkeypatch.setattr(PhoenixTraceSink, "__init__", initialize)
    host = make_test_service(
        tmp_path,
        trace_backend="phoenix",
        phoenix_endpoint="http://unused/v1/traces",
        trace_content_mode="raw",
    )
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        response = (
            client.post(
                f"/api/agents/{agent_id}/runs?workspace_path=projects/project-1",
                headers={"SAGE-TENANT-ID": "business-user-123"},
                json={
                    "threadId": "work-1",
                    "runId": "create-1",
                    "messages": [
                        {"id": "create-1", "role": "user", "content": "hello"}
                    ],
                    "runtimeContext": {
                        "session_id": "work-1",
                        "project_metadata": {"id": "project-1"},
                    },
                },
            )
            if project
            else send(client)
        )
        assert response.status_code == 200, response.text

        async def settle():
            async with asyncio.timeout(5):
                while host.execution._drives:
                    await asyncio.sleep(0.01)

        client.portal.call(settle)
        spans = exporter.get_finished_spans()
        agents = [span for span in spans if span.name == "agent.run"]
        assert len(agents) == 1, [span.name for span in spans]
        assert agents[0].attributes["agent_id"] == agent_id
        assert agents[0].attributes["session.id"] == "work-1"
        assert agents[0].attributes["sage.performance.total_ms"] >= 0
        models = [span for span in spans if span.name == "model.request"]
        assert models
        assert json.loads(models[0].attributes["input.value"])["messages"]
        assert json.loads(models[0].attributes["output.value"])["text"] == "hello"
        assert not any(span.name.startswith("sage.diagnostic.") for span in spans)


@pytest.mark.parametrize("trace_mode", ["off", "langfuse", "unsampled", "export_failed", "diagnostics_off"])
def test_session_diagnostic_zip_is_independent_of_trace(tmp_path, monkeypatch, trace_mode):
    from io import BytesIO
    from zipfile import ZipFile

    from sagents.v2.model.wire_diagnostics import record_wire_event, record_wire_request
    from sagents.v2.runtime.observability.plugins.langfuse import LangfuseTraceSink
    from tests.app.v2.server.conftest import scripted_hello
    from tests.app.v2.server.test_admin import admin_login
    from tests.app.v2.server.test_agui_chat import _run_input
    from tests.app.v2.server.test_file_downloads import identity

    exporter = InMemorySpanExporter()
    if trace_mode == "export_failed":
        from opentelemetry.sdk.trace.export import SpanExportResult

        monkeypatch.setattr(exporter, "export", lambda _: SpanExportResult.FAILURE)
    original = LangfuseTraceSink.__init__

    def initialize(self, **options):
        original(self, **options, exporter=exporter)

    monkeypatch.setattr(LangfuseTraceSink, "__init__", initialize)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    model = scripted_hello()
    original_stream = model.stream

    async def stream(request):
        await record_wire_request(
            {"model": "test-model", "api_key": "sk-zip-private-test", "messages": [{"role": "user", "content": "hello"}]},
            model="test-model", provider="test",
        )
        record_wire_event({"choices": [{"delta": {"content": "hello", "token": "sk-wire-raw-token"}}]})
        async for event in original_stream(request):
            yield event

    monkeypatch.setattr(model, "stream", stream)
    host = make_test_service(
        tmp_path, model_provider=model,
        trace_backend="noop" if trace_mode == "off" else "langfuse",
        langfuse_base_url="http://unused",
        trace_sample_rate=0 if trace_mode == "unsampled" else 1,
        diagnostics_enabled=trace_mode != "diagnostics_off",
    )
    with TestClient(create_app(host)) as client:
        user, _ = identity(client, "zip-owner")
        response = client.post("/api/agent", json=_run_input(), headers=user)
        assert response.status_code == 200, response.text
        url = "/api/threads/thread-1/download"
        assert client.get(url, headers=user).status_code == 403
        admin = {"Authorization": f"Bearer {admin_login(client)}"}
        download = client.get(url, headers=admin)
        if trace_mode == "diagnostics_off":
            assert download.status_code == 409
            assert any(span.name == "model.request" for span in exporter.get_finished_spans())
            return
        assert download.status_code == 200, download.text
        with ZipFile(BytesIO(download.content)) as archive:
            assert archive.testzip() is None
            manifest = json.loads(archive.read("thread-1/manifest.json"))
            logs = json.loads(archive.read("thread-1/logs.json"))
            index = json.loads(archive.read("thread-1/requests/index.json"))
            main, = (json.loads(archive.read(f"thread-1/{row['path']}")) for row in index if row["purpose"] == "agent")
            assert manifest["diagnostic_source"] == "local"
            assert manifest["diagnostic_storage_available"]
            assert not manifest["diagnostic_writes_pending"]
            assert not manifest["redacted"]
            assert not manifest["model_evidence_redacted_on_export"]
            assert main["run_id"] in manifest["run_ids"]
            assert main["request_format"] == "provider_wire"
            assert main["capture_mode"] == "raw"
            assert main["request"]["api_key"] == "sk-zip-private-test"
            assert main["response"]["text"] == "hello"
            assert main["stream"]["wire_capture_available"]
            assert main["stream"]["wire_events"][0]["choices"][0]["delta"] == {
                "content": "hello", "token": "sk-wire-raw-token",
            }
            assert main["stream"]["normalized_events"][0]["delta"] == "hello"
            assert any(log["event"] == "model.request.completed" and log["run_id"] == main["run_id"] for log in logs)
            assert b"sk-zip-private-test" in archive.read("thread-1/models.json")
            assert b"sk-zip-private-test" not in archive.read("thread-1/logs.json")
        assert bool(exporter.get_finished_spans()) == (trace_mode == "langfuse")
