from io import BytesIO
from zipfile import ZipFile

import pytest

from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_agui_chat import _run_input


def identity(client, name):
    token = register_and_login(client, name)
    headers = {"Authorization": f"Bearer {token}"}
    user = client.get("/api/auth/session", headers=headers).json()["data"]
    return headers, user["user_id"]


@pytest.mark.timeout(30)
def test_workspace_listing_and_download_are_scoped_and_skip_symlinks(client, service, tmp_path):
    alice, alice_id = identity(client, "alice")
    bob, bob_id = identity(client, "bob")
    agent_id = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
    root = service.paths.workspace_dir(alice_id, client.get("/api/agents", headers=alice).json()["data"][0]["id"])
    (root / "项目").mkdir()
    (root / "项目" / "说明.txt").write_text("hello 世界", encoding="utf-8")
    (root / "项目" / "empty").mkdir()
    other = service.paths.workspace_dir(bob_id, client.get("/api/agents", headers=bob).json()["data"][0]["id"])
    (other / "private.txt").write_text("Bob private")
    (root / "outside").symlink_to(other, target_is_directory=True)
    (root / "file-link").symlink_to(other / "private.txt")

    response = client.get(f"/api/workspace/files?agent_id={agent_id}", headers=alice)
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["data"]] == ["项目"]
    assert all(not item["path"].startswith("/") for item in response.json()["data"])
    listing = client.get(f"/api/workspace/files?agent_id={agent_id}", params={"agent_id": agent_id, "path": "项目"}, headers=alice).json()["data"]
    assert [item["is_directory"] for item in listing] == [True, False]
    content = client.get(f"/api/workspace/download?agent_id={agent_id}", params={"agent_id": agent_id, "path": "项目/说明.txt"}, headers=alice)
    assert content.content.decode() == "hello 世界"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert content.headers["cache-control"] == "no-store"
    assert client.get(f"/api/workspace/download?agent_id={agent_id}", params={"agent_id": agent_id, "path": "项目/说明.txt"}, headers=bob).status_code == 404
    for path in ["../private.txt", "/etc/passwd", "a/../../private", "a\\b",
                 "/workspace/../private.txt", "/workspace-other/private.txt", "/workspace//etc/passwd"]:
        assert client.get(f"/api/workspace/download?agent_id={agent_id}", params={"agent_id": agent_id, "path": path}, headers=alice).status_code == 400
    for path in ["outside/private.txt", "file-link"]:
        assert client.get(f"/api/workspace/download?agent_id={agent_id}", params={"agent_id": agent_id, "path": path}, headers=alice).status_code == 404
    folder = client.get(f"/api/workspace/download?agent_id={agent_id}", headers=alice)
    with ZipFile(BytesIO(folder.content)) as archive:
        assert "workspace/项目/说明.txt" in archive.namelist()
        assert "workspace/项目/empty/" in archive.namelist()
        assert not any("outside" in name or "file-link" in name for name in archive.namelist())
    # Sandbox-visible paths and frontend-relative paths select identical files.
    mapped = client.get("/api/workspace/files", params={"agent_id": agent_id, "path": "/workspace/项目"}, headers=alice)
    assert mapped.json()["data"] == listing
    mapped_file = client.get("/api/workspace/download", params={"agent_id": agent_id, "path": "/workspace/项目/说明.txt"}, headers=alice)
    assert mapped_file.content == content.content
    mapped_folder = client.get("/api/workspace/download", params={"agent_id": agent_id, "path": "/workspace/项目"}, headers=alice)
    with ZipFile(BytesIO(mapped_folder.content)) as archive:
        assert archive.read("项目/说明.txt").decode() == "hello 世界"
    mapped_root = client.get("/api/workspace/download", params={"agent_id": agent_id, "path": "/workspace"}, headers=alice)
    with ZipFile(BytesIO(mapped_root.content)) as archive:
        assert "workspace/项目/说明.txt" in archive.namelist()
    assert client.get(f"/api/workspace/files?agent_id={agent_id}", headers={**bob, "X-Sage-View-User": alice_id}).status_code == 403


@pytest.mark.timeout(30)
def test_session_zip_exports_only_observation_evidence_for_admin(client, service):
    alice, _ = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    assert client.get("/api/threads/thread-1/download", headers=alice).status_code == 403
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.get("/api/threads/thread-1/download", headers=headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "thread-1/models.json" in names
        assert "thread-1/manifest.json" in names
        assert not any(name.startswith(("thread-1/state", "thread-1/session", "thread-1/runs/", "thread-1/events/")) for name in names)
        assert all(name.startswith("thread-1/") for name in names)
    assert client.get("/api/threads/missing/download", headers=headers).status_code == 404


def test_workspace_uses_session_owner_for_admin_and_rejects_other_users(client, service):
    alice, alice_id = identity(client, "alice")
    bob, _ = identity(client, "bob")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    root = service.paths.workspace_dir(alice_id, client.get("/api/agents", headers=alice).json()["data"][0]["id"])
    (root / "owner.txt").write_text("Alice workspace")
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    admin = {"Authorization": f"Bearer {admin_token}"}
    params = {"thread_id": "thread-1", "path": "/workspace"}
    listing = client.get("/api/workspace/files", params=params, headers=admin)
    assert listing.status_code == 200
    assert "owner.txt" in [item["name"] for item in listing.json()["data"]]
    response = client.get("/api/workspace/download", params={**params, "path": "owner.txt"}, headers=admin)
    assert response.content == b"Alice workspace"
    archive = client.get("/api/workspace/download", params=params, headers=admin)
    with ZipFile(BytesIO(archive.content)) as zipped:
        assert zipped.read("workspace/owner.txt") == b"Alice workspace"
    for endpoint in ("files", "download"):
        assert client.get(f"/api/workspace/{endpoint}", params=params, headers=bob).status_code == 404
        assert client.get(f"/api/workspace/{endpoint}", params={"thread_id": "missing"}, headers=admin).status_code == 404


def test_session_download_never_exports_business_aggregate(client, service, monkeypatch):
    from unittest.mock import AsyncMock
    alice, _ = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    store = service.conversations.application.entrypoint().runtime.session_store
    export = AsyncMock(side_effect=AssertionError("business aggregate must not be exported"))
    monkeypatch.setattr(store, "export_session_state", export)
    monkeypatch.setattr(store, "read_events", AsyncMock(side_effect=AssertionError("business events must not be read")))
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    response = client.get("/api/threads/thread-1/download", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert "thread-1/models.json" in archive.namelist()
        assert "thread-1/state.json" not in archive.namelist()
    export.assert_not_called()


def test_workspace_honors_persisted_external_project_binding(client, service, monkeypatch):
    from unittest.mock import AsyncMock

    alice, alice_id = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    workspace_id = "external-user-123"
    agent_id = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
    root = service.paths.workspace_dir(workspace_id, agent_id)
    (root / "external.txt").write_text("external user's file")
    (service.paths.workspace_dir(alice_id, client.get("/api/agents", headers=alice).json()["data"][0]["id"]) / "owner.txt").write_text("Agent owner file")
    access = service.conversations.session_access
    context = service.conversations.context_for(alice_id)
    runs = client.portal.call(access.list_session_runs, "thread-1", context)
    command = client.portal.call(access.get_start_command, runs[0].run_id, context)
    bound = command.model_copy(update={"config": command.config.model_copy(update={"metadata": {
        **command.config.metadata, "server_v2.workspace_user_id": workspace_id,
    }})})
    monkeypatch.setattr(access, "get_start_command", AsyncMock(return_value=bound))
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    admin = {"Authorization": f"Bearer {admin_token}"}
    params = {"thread_id": "thread-1"}
    response = client.get("/api/workspace/files", params=params, headers=admin)
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["data"]] == ["external.txt"]
    download = client.get("/api/workspace/download", params={**params, "path": "external.txt"}, headers=admin)
    assert download.content == b"external user's file"


def test_workspace_api_isolates_agents_and_requires_identity(client, service):
    headers, user_id = identity(client, "alice")
    first = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
    second = client.post("/api/agents", headers=headers, json={"name": "second"}).json()["data"]["id"]
    root = service.paths.workspace_dir(user_id, first)
    (root / "private.txt").write_text("first agent only")
    assert client.get("/api/workspace/files", headers=headers).status_code == 400
    assert client.get("/api/workspace/files", params={"agent_id": "unknown"}, headers=headers).status_code == 404
    response = client.get("/api/workspace/files", params={"agent_id": second}, headers=headers)
    assert response.status_code == 200 and response.json()["data"] == []
    assert client.get("/api/workspace/download", params={"agent_id": second, "path": "private.txt"}, headers=headers).status_code == 404
    assert client.get("/api/workspace/download", params={"agent_id": first, "path": "private.txt"}, headers=headers).content == b"first agent only"
