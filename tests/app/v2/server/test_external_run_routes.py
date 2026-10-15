"""Internal Run routes enforce persisted tenant and request identity bounds."""

import base64
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.test_external_chat import make_host, setup_agent


def _headers(tenant="tenant-a"):
    return {"SAGE-TENANT-ID": tenant}


def _run(client, agent_id, run_id="run-a", tenant="tenant-a"):
    return client.post(
        f"/api/agents/{agent_id}/runs",
        params={"workspace_path": "projects/site"},
        headers=_headers(tenant),
        json={"threadId": "thread-a", "runId": run_id,
              "messages": [{"id": run_id, "role": "user", "content": "hello"}]},
    )


@pytest.mark.timeout(15)
def test_external_run_routes_are_scoped_to_agent_tenant_and_request(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent_id}"
        _exercise_run_routes(client, base, agent_id)


def _exercise_run_routes(client, base, agent_id):
    seed = {"index.html": base64.b64encode(b"<html></html>").decode()}
    imported = client.put(base + "/workspace/files", headers=_headers(),
                          json={"directory": "projects/site", "files": seed})
    assert imported.status_code == 200, imported.text
    assert imported.json()["data"]["file_count"] == 1
    assert (client.put(base + "/workspace/files", headers=_headers(),
                      json={"directory": "projects/site", "files": seed})).status_code == 200
    assert (client.put(base + "/workspace/files", headers=_headers(),
                      json={"directory": "../escape", "files": seed})).status_code == 422
    assert _run(client, agent_id).status_code == 200
    result = client.get(base + "/runs/thread-a/run-a", headers=_headers())
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "completed"
    assert result.json()["data"]["threadId"] == "thread-a"
    assert result.json()["data"]["runId"] == "run-a"
    assert "request_id" not in result.json()["data"]
    assert "run_id" not in result.json()["data"]
    assert result.json()["data"]["items"]
    assert client.get(base + "/runs/thread-a/run-a", headers=_headers("tenant-b")).status_code == 404
    assert client.get(base + "/runs/thread-a/wrong-run", headers=_headers()).status_code == 404
    downloaded = client.get(base + "/runs/thread-a/run-a/files", headers=_headers())
    assert downloaded.status_code == 200, downloaded.text
    with ZipFile(BytesIO(downloaded.content)) as archive:
        assert archive.read("site/index.html") == b"<html></html>"
    cancelled = client.post(base + "/runs/thread-a/run-a/cancel", headers=_headers())
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["cancelled"] is False
    assert _run(client, agent_id, run_id="run-b").status_code == 200
    stale = client.get(base + "/runs/thread-a/run-a/files", headers=_headers())
    assert stale.status_code == 409


def test_external_run_rejects_invalid_workspace_path_before_start(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        response = client.post(f"/api/agents/{agent_id}/runs",
                               params={"workspace_path": "../escape"}, headers=_headers(),
                               json={"threadId": "thread-a", "runId": "run-a",
                                     "messages": [{"id": "m", "role": "user", "content": "hello"}]})
        assert response.status_code == 422
        result = client.get(f"/api/agents/{agent_id}/runs/thread-a/run-a",
                            headers=_headers())
        assert result.status_code == 404


def test_external_run_passes_runtime_context_separately_from_agui(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        received = []
        original = host.conversations.start

        async def capture(request, **kwargs):
            received.append(kwargs["runtime_context"])
            return await original(request, **kwargs)

        host.conversations.start = capture
        response = client.post(
            f"/api/agents/{agent_id}/runs",
            params={"workspace_path": "projects/site"},
            headers=_headers(),
            json={"threadId": "thread-a", "runId": "request-a",
                  "messages": [{"id": "request-a", "role": "user", "content": "hello"}],
                  "runtimeContext": {"project": {"id": "site", "revision": 1}}},
        )
        assert response.status_code == 200, response.text
        assert received == [{"project": {"id": "site", "revision": 1}}]
