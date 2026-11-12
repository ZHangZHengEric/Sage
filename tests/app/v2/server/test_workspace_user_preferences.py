"""External preferences read and write the current tenant's Claw USER.md."""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.test_external_chat import make_host, setup_agent
from tests.app.v2.server.test_external_run_routes import _headers


def test_workspace_user_preferences_preserve_existing_file_and_scope(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        endpoint = f"/api/agents/{agent}/workspace/user-preferences"
        headers = _headers()
        file = host.paths.workspace_dir("tenant-a", agent) / "USER.md"
        file.write_text("# 已有偏好\n\n原有正文\n", encoding="utf-8")
        read = client.get(endpoint, headers=headers)
        assert read.status_code == 200
        document = read.json()["data"]
        assert document["text"] == file.read_text(encoding="utf-8")
        assert client.get(endpoint, headers=_headers("tenant-b")).json()["data"] == {
            "text": None, "revision": "missing",
        }
        content = "偏暖的配色\n"
        updated = client.put(endpoint, headers=headers, json={**document, "text": content})
        assert updated.status_code == 200, updated.text
        assert file.read_bytes() == content.encode()
        assert client.get(endpoint, headers=headers).json()["data"] == updated.json()["data"]
        assert client.put(endpoint, headers=headers, json={**document, "text": "过期"}).status_code == 409
        assert file.read_bytes() == content.encode()

        cleared = client.put(endpoint, headers=headers, json={**updated.json()["data"], "text": ""})
        assert cleared.status_code == 200
        assert file.read_bytes() == b""

        outside = tmp_path / "private.md"
        outside.write_text("private", encoding="utf-8")
        file.unlink()
        file.symlink_to(outside)
        assert client.get(endpoint, headers=headers).status_code == 422
        assert outside.read_text(encoding="utf-8") == "private"
