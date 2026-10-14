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
    root = service.paths.workspace_dir(alice_id)
    (root / "项目").mkdir()
    (root / "项目" / "说明.txt").write_text("hello 世界", encoding="utf-8")
    (root / "项目" / "empty").mkdir()
    other = service.paths.workspace_dir(bob_id)
    (other / "private.txt").write_text("Bob private")
    (root / "outside").symlink_to(other, target_is_directory=True)
    (root / "file-link").symlink_to(other / "private.txt")

    response = client.get("/api/workspace/files", headers=alice)
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["data"]] == ["项目"]
    assert all(not item["path"].startswith("/") for item in response.json()["data"])
    listing = client.get("/api/workspace/files", params={"path": "项目"}, headers=alice).json()["data"]
    assert [item["is_directory"] for item in listing] == [True, False]
    content = client.get("/api/workspace/download", params={"path": "项目/说明.txt"}, headers=alice)
    assert content.content.decode() == "hello 世界"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert content.headers["cache-control"] == "no-store"
    assert client.get("/api/workspace/download", params={"path": "项目/说明.txt"}, headers=bob).status_code == 404
    for path in ["../private.txt", "/etc/passwd", "a/../../private", "a\\b"]:
        assert client.get("/api/workspace/download", params={"path": path}, headers=alice).status_code == 400
    for path in ["outside/private.txt", "file-link"]:
        assert client.get("/api/workspace/download", params={"path": path}, headers=alice).status_code == 404
    folder = client.get("/api/workspace/download", headers=alice)
    with ZipFile(BytesIO(folder.content)) as archive:
        assert "workspace/项目/说明.txt" in archive.namelist()
        assert "workspace/项目/empty/" in archive.namelist()
        assert not any("outside" in name or "file-link" in name for name in archive.namelist())
    assert client.get("/api/workspace/files", headers={**bob, "X-Sage-View-User": alice_id}).status_code == 403


@pytest.mark.timeout(30)
def test_session_zip_exports_real_session_folder_for_admin(client, service):
    alice, _ = identity(client, "alice")
    assert client.post("/api/agent", json=_run_input(), headers=alice).status_code == 200
    assert client.get("/api/threads/thread-1/download", headers=alice).status_code == 403
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.get("/api/threads/thread-1/download", headers=headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "thread-1/state.json" in names
        assert "thread-1/session.json" in names
        assert any(name.startswith("thread-1/runs/") and name.endswith(".json") for name in names)
        assert all(name.startswith("thread-1/") for name in names)
    assert client.get("/api/threads/missing/download", headers=headers).status_code == 404
