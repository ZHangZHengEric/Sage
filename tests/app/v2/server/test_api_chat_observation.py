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
                f"/api/agents/{agent_id}/runs?workspace_path=projects/artwork-1",
                headers={"SAGE-TENANT-ID": "business-user-123"},
                json={
                    "threadId": "work-1",
                    "runId": "create-1",
                    "messages": [
                        {"id": "create-1", "role": "user", "content": "hello"}
                    ],
                    "runtimeContext": {
                        "session_id": "work-1",
                        "wishseen_project": {"id": "artwork-1"},
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
