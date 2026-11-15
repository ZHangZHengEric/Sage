"""Machine workspace inspection and tenant-wide erasure exercise the real HTTP routes."""
import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from sagents.v2.contracts.common import utc_now
from sagents.v2.memory import MemoryQuery, MemoryRecord
from sagents.v2.memory.identity import command_memory_scope
from sagents.v2.session_memory import SessionMemoryQuery
from tests.app.v2.server.test_external_chat import make_host, setup_agent
from tests.app.v2.server.test_external_memory_isolation import MemoryTestModel


def _key(client, token, agent, scope):
    response = client.post("/api/keys", headers={"Authorization": f"Bearer {token}"}, json={
        "agent_id": agent, "name": scope, "scopes": [scope],
    })
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["api_key"],
            "SAGE-TENANT-ID": "tenant-a"}


@pytest.mark.parametrize("backend", ["local", "cube"])
def test_machine_workspace_metadata_and_empty_purge(tmp_path, monkeypatch, backend):
    if backend == "cube":
        from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
        from tests.app.v2.server.test_cube_execution import cube_host
        from tests.sagents.v2.cube_fakes import FakeCubeClient

        remote = FakeCubeClient(tmp_path / "cube")
        monkeypatch.setattr("sagents.v2.runtime.execution.sandbox.plugins.cube.CubeVolumeClient",
                            lambda **_: remote)
        host = cube_host(tmp_path / "sage")
        workspace = lambda tenant, agent: remote.root / cube_volume_name(tenant, agent)
    else:
        host = make_host(tmp_path / "sage")
        workspace = host.paths.workspace_path

    with TestClient(create_app(host)) as client:
        console = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        del client.headers["Authorization"]
        base = f"/api/agents/{agent}"
        files = base + "/workspace/files"
        stat_url = files + "/stat"
        delete_url = base + "/tenant-data"
        read, invoke = (_key(client, console, agent, scope) for scope in ["a2a:read", "a2a:invoke"])

        root, other = (workspace(tenant, agent) for tenant in ["tenant-a", "tenant-b"])
        assert client.get(files, headers=read).json()["data"] == {"files": [], "truncated_by_depth": False}
        (root / "site" / "empty").mkdir(parents=True, exist_ok=True)
        (other / "site").mkdir(parents=True)
        content = b"\0\xffbinary"
        (root / "site" / "file.bin").write_bytes(content)
        (other / "site" / "file.bin").write_bytes(b"keep")
        (root / ".hidden").write_bytes(b"private")
        (root / "site" / ".hidden").write_bytes(b"private")
        (root / "alias").symlink_to(other, target_is_directory=True)
        os.link(other / "site" / "file.bin", root / "hardlink")
        if backend == "cube":
            private = remote.root / cube_volume_name("tenant-a", agent, private_run_id="old-child")
            private.mkdir()
            (private / ".hidden").write_text("erase")
            unrelated = remote.root / (root.name + "-unrelated")
            unrelated.mkdir()

        def list_at(path, depth):
            response = client.get(files, headers=read, params={"path": path, "depth": depth})
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            return [row["path"] for row in data["files"]], data["truncated_by_depth"]

        assert list_at(".", 0) == ([], True)
        assert list_at("", 1) == (["site"], True)
        assert list_at("site", 1) == (["site/empty", "site/file.bin"], False)
        assert list_at("site/empty", 0) == ([], False)
        assert client.get(files, headers=read, params={"path": "missing"}).status_code == 404
        for path in ("../site", ".hidden", "/workspace", "alias/site"):
            assert client.get(files, headers=read, params={"path": path}).status_code == 422

        values = ["site/file.bin", "site", "missing", "alias/site/file.bin", "hardlink", "site/file.bin"]
        response = client.post(stat_url, headers=read, json={"paths": values})
        assert response.status_code == 200, response.text
        rows = response.json()["data"]["files"]
        assert [row["path"] for row in rows] == values
        assert rows[0] == {"path": values[0], "exists": True, "type": "file",
                           "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        assert rows[1] == {"path": "site", "exists": True, "type": "directory",
                           "size": None, "sha256": None}
        assert not any(row["exists"] for row in rows[2:5])
        assert rows[0] == rows[-1]
        assert client.post(stat_url, headers=read, json={"paths": ["site", ".hidden"]}).status_code == 422
        assert client.post(stat_url, headers=invoke, json={"paths": ["site"]}).status_code == 403
        assert client.get(files, headers=invoke).status_code == 403
        assert client.get(files, headers={"SAGE-TENANT-ID": "tenant-a",
                                          "Authorization": f"Bearer {console}"}).status_code == 401
        assert client.delete(delete_url, headers=read).status_code == 403
        other_agent = client.post("/api/agents", headers={"Authorization": f"Bearer {console}"},
                                  json={"name": "Other agent"}).json()["data"]["id"]
        assert client.delete(f"/api/agents/{other_agent}/tenant-data", headers=invoke).status_code == 403

        for _ in range(2):
            response = client.delete(delete_url, headers=invoke)
            assert response.status_code == 200, response.text
            assert response.json()["data"] == {"deleted": True}
        assert not root.exists() or not list(root.iterdir())
        assert (other / "site" / "file.bin").read_bytes() == b"keep"
        if backend == "cube":
            assert not private.exists()
            assert unrelated.exists()


@pytest.mark.timeout(25)
def test_tenant_data_retries_session_memory_cleanup_and_preserves_other_tenants(tmp_path, monkeypatch):
    host = make_host(tmp_path, steps=20)
    host.execution.fallback_model = MemoryTestModel(host.execution.fallback_model)
    with TestClient(create_app(host)) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent}"
        auth = {"Authorization": f"Bearer {token}"}
        configured = client.put(base, headers=auth,
                                json={"name": "Memory test", "tools": ["search_memory"]})
        assert configured.status_code == 200, configured.text
        for tenant, thread in (("tenant-a", "a-one"), ("tenant-a", "a-two"), ("tenant-b", "b-one")):
            response = client.post(base + "/runs", headers={"SAGE-TENANT-ID": tenant},
                                   json={"threadId": thread, "runId": "create",
                                         "messages": [{"id": "input", "role": "user", "content": "cobaltcoffee"}]})
            assert "RUN_FINISHED" in response.text, response.text[-1500:]
        portal = client.portal
        assert portal is not None
        store = host.application.runtime.session_store
        memory = host.application.service("memory.provider")
        session_memory = host.application.service("session-memory.provider")

        async def session(thread):
            run = (await store.list_session_runs(thread))[0]
            return run.run_id, command_memory_scope(await store.get_start_command(run.run_id))

        run_a, scope_a = portal.call(session, "a-one")
        run_b, scope_b = portal.call(session, "b-one")
        assert host.conversations is not None
        threads = host.conversations.threads
        private_scope = scope_a.model_copy(update={"workspace_id": "private:formerly-deleted-child"})
        other_scope = scope_a.model_copy(update={"workspace_id": "another-agent"})
        original_forget = session_memory.forget_session

        async def seed_records():
            now = utc_now()
            for scope, source in [
                (scope_a, {}), (scope_b, {}), (private_scope, {"root_workspace_id": agent}), (other_scope, {}),
            ]:
                await memory.remember(MemoryRecord(memory_id="extra", scope=scope, content="cobaltcoffee",
                                                   source=source, created_at=now, updated_at=now))
            assert await session_memory.recall(SessionMemoryQuery(
                session_id="a-one", run_id=run_a, text="cobaltcoffee"))
            assert await session_memory.recall(SessionMemoryQuery(
                session_id="b-one", run_id=run_b, text="cobaltcoffee"))

        portal.call(seed_records)
        root = host.paths.workspace_path("tenant-a", agent)
        (root / ".sage-test").write_text("also erase me")
        private_root = root.parent / ".sage-private-workspaces" / "a-private-run"
        private_root.mkdir(parents=True, exist_ok=True)
        (private_root / "data").write_text("erase this too")

        async def failure(session_id):
            if session_id == "a-two":
                raise OSError("simulated search index outage")
            await original_forget(session_id)

        headers = {"SAGE-TENANT-ID": "tenant-a"}
        with monkeypatch.context() as patch:
            patch.setattr(host.execution, "workspace_driving", lambda *_: True)
            response = client.delete(base + "/tenant-data", headers=headers)
            assert response.status_code == 409, response.text
            assert response.json()["error_detail"] == "workspace_busy"
            assert (root / ".sage-test").exists()
        with monkeypatch.context() as patch:
            patch.setattr(session_memory, "forget_session", failure)
            response = client.delete(base + "/tenant-data", headers=headers)
            assert response.status_code == 503, response.text
            assert response.json()["error_detail"] == "tenant_data_cleanup_incomplete"
            assert portal.call(threads.find, "a-two") is not None
            assert portal.call(store.get_session, "a-two").session_id == "a-two"

        async def assert_erased():
            assert await threads.find("a-one") is None
            assert await threads.find("a-two") is None
            assert await threads.find("b-one") is not None
            from sagents.v2.contracts.errors import SageV2Error
            for thread in ("a-one", "a-two"):
                with pytest.raises(SageV2Error) as error:
                    await store.get_session(thread)
                assert error.value.info.code == "session.not_found"
            for scope in (scope_a, private_scope):
                assert not await memory.recall(MemoryQuery(scope=scope, text="cobaltcoffee"))
            for scope in (scope_b, other_scope):
                assert await memory.recall(MemoryQuery(scope=scope, text="cobaltcoffee"))
            for thread in ("a-one", "a-two"):
                assert not await session_memory.recall(SessionMemoryQuery(
                    session_id=thread, run_id=run_a, text="cobaltcoffee"))
            assert await session_memory.recall(SessionMemoryQuery(
                session_id="b-one", run_id=run_b, text="cobaltcoffee"))

        for _ in range(2):
            response = client.delete(base + "/tenant-data", headers=headers)
            assert response.status_code == 200, response.text
        portal.call(assert_erased)
        assert not root.exists()
        assert not private_root.exists()
        assert host.paths.workspace_path("tenant-b", agent).is_dir()
