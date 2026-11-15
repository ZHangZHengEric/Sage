"""Internal Run routes enforce persisted tenant and request identity bounds."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from app.v2.server.conversations.agui.service import ConversationService

import base64
from dataclasses import replace
from io import BytesIO
import os
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.test_external_chat import make_host, setup_agent


def _headers(tenant="tenant-a"):
    return {"SAGE-TENANT-ID": tenant}


@pytest.mark.parametrize("backend", ["local", "cube"])
def test_external_workspace_get_returns_only_one_regular_file(tmp_path, monkeypatch, backend):
    if backend == "cube":
        from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
        from tests.app.v2.server.test_cube_execution import cube_host
        from tests.sagents.v2.cube_fakes import FakeCubeClient

        remote = FakeCubeClient(tmp_path / "cube")
        monkeypatch.setattr(
            "sagents.v2.runtime.execution.sandbox.plugins.cube.CubeVolumeClient", lambda **_: remote,
        )
        host = cube_host(tmp_path / "sage")
    else:
        host = make_host(tmp_path / "sage")

    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        del client.headers["Authorization"]
        agent = client.headers["SAGE-AGENT-ID"]
        console = {"Authorization": f"Bearer {token}"}
        url = f"/api/agents/{agent}/workspace/file"

        def workspace(tenant):
            if backend == "cube":
                return remote.root / cube_volume_name(tenant, agent)
            return host.paths.workspace_path(tenant, agent)

        body = "\ufeff# 身份\r\n".encode()
        for tenant, content in (("tenant-a", body), ("tenant-b", b"other tenant")):
            root = workspace(tenant)
            root.mkdir(parents=True)
            (root / "IDENTITY.md").write_bytes(content)
        root = workspace("tenant-a")
        (root / "directory").mkdir()
        (root / "directory" / "nested.bin").write_bytes(b"\x00\xff")
        (root / "link.md").symlink_to(workspace("tenant-b") / "IDENTITY.md")
        (root / "linked-dir").symlink_to(workspace("tenant-b"), target_is_directory=True)
        secret = workspace("tenant-b") / "secret.bin"
        secret.write_bytes(b"other tenant's file")
        os.link(secret, root / "hardlink.bin")

        def credential(name, scope):
            issued = client.post("/api/keys", headers=console, json={
                "agent_id": agent, "name": name, "scopes": [scope],
            })
            assert issued.status_code == 200, issued.text
            key = issued.json()["data"]
            return {"Authorization": "Bearer " + key["api_key"]}, key["key_id"]

        read_key, read_key_id = credential("read files", "a2a:read")
        identity = {"path": "IDENTITY.md"}
        headers = {**read_key, **_headers()}
        response = client.get(url, params=identity, headers=headers)
        assert response.status_code == 200, response.text
        assert response.content == body
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.headers["cache-control"] == "private, no-store"
        # A trusted holder of this machine key selects the tenant for this Agent.
        assert client.get(url, params=identity, headers={**read_key, **_headers("tenant-b")}).content == b"other tenant"
        binary = client.get(url, params={"path": "directory/nested.bin"}, headers=headers)
        assert binary.content == b"\x00\xff"
        assert binary.headers["content-type"] == "application/octet-stream"
        for tenant in ("missing", "TENANT-A", "../tenant-b", "tenant%2Db"):
            assert client.get(url, params=identity, headers={**read_key, **_headers(tenant)}).status_code == 404, tenant
        assert client.get(url, params={"path": "SOUL.md"}, headers=headers).status_code == 404
        for invalid in ("", "directory", "link.md", "linked-dir/IDENTITY.md", "hardlink.bin",
                        "../IDENTITY.md", "/workspace/IDENTITY.md", "directory\\nested.bin"):
            assert client.get(url, params={"path": invalid}, headers=headers).status_code == 422, invalid
        assert client.get(url + "?path=%2e%2e%2fIDENTITY.md", headers=headers).status_code == 422
        victim = _headers("tenant-b")
        for untrusted in (victim, {**console, **victim}, {**victim, "Authorization": "Bearer invalid"}):
            assert client.get(url, params=identity, headers=untrusted).status_code == 401
        duplicate_auth = [*headers.items(), ("Authorization", "Bearer invalid")]
        assert client.get(url, params=identity, headers=duplicate_auth).status_code == 401
        duplicate_tenant = [*headers.items(), *victim.items()]
        assert client.get(url, params=identity, headers=duplicate_tenant).status_code == 422
        assert client.get(url, params=identity, headers={**read_key, **_headers("tenant-a, tenant-b")}).status_code == 422
        assert client.get(url, params=identity, headers={"Authorization": ""}).status_code == 401
        assert client.get(url, params=identity, headers=read_key).status_code == 422
        invoke_key, _ = credential("invoke only", "a2a:invoke")
        assert client.get(url, params=identity, headers={**invoke_key, **victim}).status_code == 403
        other_agent = client.post("/api/agents", headers=console, json={"name": "Other Agent"}).json()["data"]["id"]
        assert client.get(f"/api/agents/{other_agent}/workspace/file", params=identity, headers=headers).status_code == 403
        if backend == "local":
            # An Agent-directory symlink must not escape the authorized root.
            alias = workspace("alias").parent
            alias.parent.mkdir()
            alias.symlink_to(workspace("tenant-b").parent, target_is_directory=True)
            assert client.get(url, params=identity, headers={**read_key, **_headers("alias")}).status_code == 422
        assert client.delete(f"/api/keys/{read_key_id}", headers=console).status_code == 200
        assert client.get(url, params=identity, headers={**read_key, **victim}).status_code == 401


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
    path = {"path": "projects/site/user-uploads/reference.mov"}
    video = b"v" * ((4 << 20) + 1)
    for _ in range(2):
        uploaded = client.put(base + "/workspace/file", params=path,
                              headers=_headers(), content=video)
        assert uploaded.status_code == 200, uploaded.text
    assert client.put(base + "/workspace/file", params=path,
                      headers=_headers(), content=b"different").status_code == 409
    assert _run(client, agent_id).status_code == 200
    result = client.get(base + "/runs/thread-a/run-a", headers=_headers())
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "completed"
    assert result.json()["data"]["threadId"] == "thread-a"
    assert result.json()["data"]["runId"] == "run-a"
    assert "request_id" not in result.json()["data"]
    assert "run_id" not in result.json()["data"]
    assert result.json()["data"]["items"]
    metrics_path = base + "/runs/thread-a/run-a/metrics"
    metrics = client.get(metrics_path, headers=_headers())
    assert metrics.status_code == 200, metrics.text
    measured = metrics.json()["data"]
    assert measured["runId"] == "run-a"
    assert measured["completedAt"]
    assert measured["activeMilliseconds"] >= 0
    assert set(measured["usage"]) == {"reported", "input_tokens", "output_tokens", "cached_input_tokens"}
    assert client.get(metrics_path, headers=_headers("tenant-b")).status_code == 404
    assert client.get(base + "/runs/thread-a/missing/metrics", headers=_headers()).status_code == 404

    assert client.get(base + "/runs/thread-a/run-a", headers=_headers("tenant-b")).status_code == 404
    assert client.get(base + "/runs/thread-a/wrong-run", headers=_headers()).status_code == 404
    downloaded = client.get(base + "/runs/thread-a/run-a/files", headers=_headers())
    assert downloaded.status_code == 200, downloaded.text
    with ZipFile(BytesIO(downloaded.content)) as archive:
        assert archive.read("site/index.html") == b"<html></html>"
        assert archive.read("site/user-uploads/reference.mov") == video
    filtered = client.get(base + "/runs/thread-a/run-a/files", headers=_headers(),
                          params={"exclude": "user-uploads"})
    assert filtered.status_code == 200, filtered.text
    with ZipFile(BytesIO(filtered.content)) as archive:
        assert "site/index.html" in archive.namelist()
        assert "site/user-uploads/reference.mov" not in archive.namelist()
    for exclusion in ("../escape", "nested/uploads", ".sage", ""):
        assert client.get(base + "/runs/thread-a/run-a/files", headers=_headers(),
                          params={"exclude": exclusion}).status_code == 422
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
        original = cast('ConversationService', host.conversations).start

        async def capture(request, **kwargs):
            received.append(kwargs["runtime_context"])
            return await original(request, **kwargs)

        cast('ConversationService', host.conversations).start = capture
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
    from sagents.v2.agent.policy.plugins._shared.continuation_rules import BudgetRule

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
                a for a in (await host.catalog.get(cast(str, owner))).agents if a.id == agent_id
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
            await host.catalog.store.update_agent(cast(str, owner), updated)

        cast('BlockingPortal', client.portal).call(configure, agent_steps, package_steps, entrypoint_steps)
        response = _run(client, agent_id)
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text

        async def stored_command():
            selected = await selected_run(
                host.conversations, tenant_id="tenant-a", agent_id=agent_id,
                thread_id="thread-a", run_id="run-a",
            )
            return selected[-1]

        command = cast('BlockingPortal', client.portal).call(stored_command)
        assert command.config.max_steps == expected
        assert observed_limits and set(observed_limits) == {expected or 24}

        # Retrying the same Run after a package update reuses its frozen budget.
        cast('BlockingPortal', client.portal).call(configure, 2, 2, None)
        replay = _run(client, agent_id)
        assert replay.status_code == 200, replay.text
        assert cast('BlockingPortal', client.portal).call(stored_command) == command
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
        cast('BlockingPortal', client.portal).call(enqueue)
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
