"""Browser workspace deletion keeps the same owner and Run boundaries as reads."""
from unittest.mock import AsyncMock

import pytest

from app.v2.server.conversations.cleanup import busy
from tests.app.v2.server.test_agui_chat import _run_input
from tests.app.v2.server.test_file_downloads import identity


def test_web_deletes_files_and_directories_without_crossing_owners(client, service):
    alice, alice_id = identity(client, "alice")
    bob, _ = identity(client, "bob")
    agent_id = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
    root = service.paths.workspace_dir(alice_id, agent_id)
    (root / "项目").mkdir()
    (root / "项目/说明.txt").write_text("hello")
    params = {"agent_id": agent_id, "path": "项目/说明.txt"}
    assert client.delete("/api/workspace/files", params=params, headers=bob).status_code == 404
    assert (root / params["path"]).exists()
    response = client.delete("/api/workspace/files", params=params, headers=alice)
    assert response.status_code == 200
    assert response.json()["data"] == {"path": params["path"], "deleted": True}
    assert not (root / params["path"]).exists()
    assert client.delete("/api/workspace/files", params=params, headers=alice).json()["data"]["deleted"] is False
    (root / "项目/nested.txt").write_text("nested")
    params["path"] = "项目"
    assert client.delete("/api/workspace/files", params=params, headers=alice).status_code == 409
    response = client.delete("/api/workspace/files", params={**params, "recursive": True}, headers=alice)
    assert response.status_code == 200
    assert not (root / "项目").exists()


@pytest.mark.parametrize("path", ["", ".", "..", "../private", "/workspace", "/etc/passwd", "a/../b", "a\\b"])
def test_web_delete_rejects_root_and_path_escape(client, service, path):
    headers, user_id = identity(client, "alice")
    agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
    root = service.paths.workspace_dir(user_id, agent_id)
    (root / "keep.txt").write_text("keep")
    response = client.delete("/api/workspace/files", params={"agent_id": agent_id, "path": path, "recursive": True}, headers=headers)
    assert response.status_code == 422
    assert (root / "keep.txt").exists()


def test_web_delete_uses_thread_binding_and_keeps_admin_views_readonly(client, service, monkeypatch):
    alice, alice_id = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    agent_id = client.get("/api/agents", headers=alice).json()["data"][0]["id"]
    root = service.paths.workspace_dir("external-user", agent_id)
    (root / "file.txt").write_text("external")
    own_root = service.paths.workspace_dir(alice_id, agent_id)
    (own_root / "file.txt").write_text("owner")
    access = service.conversations.session_access
    context = service.conversations.context_for(alice_id)
    runs = client.portal.call(access.list_session_runs, "thread-1", context)
    command = client.portal.call(access.get_start_command, runs[0].run_id, context)
    bound = command.model_copy(update={"config": command.config.model_copy(update={"metadata": {
        **command.config.metadata, "server_v2.workspace_user_id": "external-user",
    }})})
    monkeypatch.setattr(access, "get_start_command", AsyncMock(return_value=bound))
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    admin = {"Authorization": f"Bearer {admin_token}"}
    params = {"thread_id": "thread-1", "path": "file.txt"}
    assert client.delete("/api/workspace/files", params=params, headers=admin).status_code == 403
    assert client.delete("/api/workspace/files", params={"agent_id": agent_id, "path": "file.txt"}, headers={**admin, "X-Sage-View-User": alice_id}).status_code == 403
    response = client.delete("/api/workspace/files", params=params, headers=alice)
    assert response.status_code == 200
    assert not (root / "file.txt").exists()
    assert (own_root / "file.txt").read_text() == "owner"


def test_web_delete_blocks_busy_workspace(client, service, monkeypatch):
    headers, user_id = identity(client, "alice")
    agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
    root = service.paths.workspace_dir(user_id, agent_id)
    (root / "keep.txt").write_text("keep")
    monkeypatch.setattr("app.v2.server.routers.files.require_idle", AsyncMock(side_effect=busy()))
    response = client.delete("/api/workspace/files", params={"agent_id": agent_id, "path": "keep.txt"}, headers=headers)
    assert response.status_code == 409
    assert (root / "keep.txt").exists()
