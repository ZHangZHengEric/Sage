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


@pytest.mark.parametrize(
    "agent_steps,package_steps,entrypoint_steps,expected",
    [
        (1000, None, None, 1000),
        (1000, 100, None, 100),
        (100, 1000, None, 100),
        (None, 1000, None, 1000),
        (None, None, 1000, 1000),
        (None, 100, 1000, 100),
        (None, None, None, None),
    ],
)
def test_external_run_uses_effective_package_step_budget(
    tmp_path, monkeypatch, agent_steps, package_steps, entrypoint_steps, expected
):
    from app.v2.server.conversations.external_runs import selected_run
    from sagents.v2.agent.management import AgentPackageBundle
    from sagents.v2.agent.policy.continuation import BudgetRule

    host = make_host(tmp_path)
    observed_limits = []
    evaluate = BudgetRule.evaluate

    async def capture(self, context):
        # This is the execution engine's actual continuation budget, after
        # loading the durable StartRun, rather than the HTTP request mapping.
        observed_limits.append(context.max_steps)
        return await evaluate(self, context)

    monkeypatch.setattr(BudgetRule, "evaluate", capture)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]

        async def configure(agent_limit, package_limit, entrypoint_limit):
            owner = await host.catalog.agent_owner(agent_id)
            agent = next(
                a for a in (await host.catalog.get(owner)).agents if a.id == agent_id
            )
            data = agent.package.model_dump(mode="json")
            definition = data["manifest"]["agents"][agent_id]
            definition["budgets"]["max_steps"] = agent_limit
            definition["entrypoint"]["config"]["max_steps"] = entrypoint_limit
            data["manifest"]["policies"]["budgets"]["max_steps"] = package_limit
            data["manifest"]["metadata"]["version"] = (
                f"budget-{agent_limit}-{package_limit}-{entrypoint_limit}"
            )
            updated = agent.model_copy(update={"package": AgentPackageBundle.model_validate(data)})
            await host.catalog.store.update_agent(owner, updated)

        client.portal.call(configure, agent_steps, package_steps, entrypoint_steps)
        response = _run(client, agent_id)
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text

        async def stored_command():
            selected = await selected_run(
                host.conversations, tenant_id="tenant-a", agent_id=agent_id,
                thread_id="thread-a", run_id="run-a",
            )
            return selected[-1]

        command = client.portal.call(stored_command)
        assert command.config.max_steps == expected
        assert observed_limits and set(observed_limits) == {expected or 24}

        # Retrying the same Run after a package update reuses its frozen budget.
        client.portal.call(configure, 2, 2, None)
        replay = _run(client, agent_id)
        assert replay.status_code == 200, replay.text
        assert client.portal.call(stored_command) == command
        assert set(observed_limits) == {expected or 24}


def test_external_cleanup_routes_are_independent_and_idempotent(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent_id}"
        client.put(base + "/workspace/files", headers=_headers(),
                   json={"directory": "assets/site", "files": {"index.html": "YQ=="}})
        assert _run(client, agent_id).status_code == 200
        # Session cleanup must preserve files, and reject a different tenant.
        assert client.delete(base + "/sessions/thread-a", headers=_headers("tenant-b")).status_code == 404
        for _ in range(2):
            response = client.delete(base + "/sessions/thread-a", headers=_headers())
            assert response.status_code == 200, response.text
        root = host.paths.workspace_path("tenant-a", agent_id)
        assert (root / "assets/site/index.html").exists()
        for expected in [True, False]:
            response = client.delete(base + "/workspace/files", headers=_headers(),
                                     params={"path": "assets", "recursive": True})
            assert response.status_code == 200, response.text
            assert response.json()["data"] == {"path": "assets", "deleted": expected}


@pytest.mark.parametrize("error,status,detail", [
    (PermissionError(13, "denied"), 403, "workspace_permission_denied"),
    (OSError(16, "busy"), 409, "workspace_busy"),
    (OSError(5, "io"), 500, "workspace_storage_failure"),
])
def test_workspace_delete_reports_storage_errors(tmp_path, monkeypatch, error, status, detail):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        base = f'/api/agents/{client.headers["SAGE-AGENT-ID"]}'
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr("app.v2.server.routers.conversations.delete_workspace_path", fail)
        response = client.delete(base + "/workspace/files", headers=_headers(), params={"path": "assets"})
        assert response.status_code == status, response.text
        assert response.json()["error_detail"] == detail


def test_workspace_cleanup_refuses_durable_unfinished_runs(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent_id = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent_id}"
        assert _run(client, agent_id).status_code == 200

        async def enqueue():
            from app.v2.server.conversations.external_runs import selected_run
            selected = await selected_run(host.conversations, tenant_id="tenant-a",
                agent_id=agent_id, thread_id="thread-a", run_id="run-a")
            command = selected[-1].model_copy(update={
                "run_id": "unfinished", "idempotency_key": "unfinished"})
            await host.application.entrypoint().runtime.session_store.create_run(command, selected[4])
        client.portal.call(enqueue)
        # Even an unrelated child path is reachable by a task in this workspace.
        response = client.delete(base + "/workspace/files", headers=_headers(),
                                 params={"path": "other", "recursive": True})
        assert response.status_code == 409, response.text
        assert response.json()["error_detail"] == "workspace_busy"
        response = client.delete(base + "/sessions/thread-a", headers=_headers())
        assert response.status_code == 409, response.text
        # Another tenant's workspace remains independent.
        assert client.delete(base + "/workspace/files", headers=_headers("tenant-b"),
                             params={"path": "other"}).status_code == 200
