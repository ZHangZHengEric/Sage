from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import make_test_service, register_and_login
from tests.app.v2.server.test_agent_guidance import _skill_zip


def test_history_diff_rollback_and_agent_pin_api(tmp_path):
    host = make_test_service(tmp_path)
    with TestClient(create_app(service=host)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        agent = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
        first = client.post("/api/skills", json={"name": "demo", "content": "# First"}, headers=headers).json()["data"]
        skill_id = first["skill_id"]
        second = client.put(f"/api/skills/{skill_id}", json={"content": "# Second",
            "expected_version_id": first["version_id"]}, headers=headers).json()["data"]
        history = client.get(f"/api/skills/{skill_id}/versions?limit=1", headers=headers)
        assert history.status_code == 200
        assert [item["revision"] for item in history.json()["data"]] == [2]
        version = client.get(f"/api/skills/{skill_id}/versions/{first['version_id']}", headers=headers)
        assert version.json()["data"]["content"] == "# First\n"
        diff = client.get(f"/api/skills/{skill_id}/diff", params={"from_version": first["version_id"],
            "to_version": second["version_id"]}, headers=headers)
        assert diff.status_code == 200 and "+# Second" in diff.json()["data"]["files"][0]["diff"]
        client.put(f"/api/agents/{agent}/skills", json={"names": ["demo"]}, headers=headers)
        pinned = client.put(f"/api/agents/{agent}/skills/{skill_id}/version",
            json={"version_id": first["version_id"]}, headers=headers)
        assert pinned.status_code == 200 and pinned.json()["data"]["version_policy"] == "pinned"
        workspace = host.paths.workspace_dir("external-tenant", agent) / "skills/demo"
        workspace.mkdir(parents=True)
        (workspace / "SKILL.md").write_text("# Local\n")
        synced = client.put(f"/api/agents/{agent}/guidance", headers=headers, data={"sync_bound": "true"})
        assert synced.json()["data"]["success_count"] == 1
        assert (workspace / "SKILL.md").read_text() == "# First\n"
        # Upload synchronization must not replace a pinned workspace with newer files.
        upload = client.put(f"/api/agents/{agent}/guidance", headers=headers,
            data={"prompt": "Keep prompt"}, files=[("files", ("demo.zip", _skill_zip("demo"), "application/zip"))])
        assert upload.json()["data"]["failed_count"] == 1
        assert client.get(f"/api/skills/{skill_id}", headers=headers).json()["data"]["version_id"] == second["version_id"]
        restored = client.post(f"/api/skills/{skill_id}/rollback", json={"version_id": first["version_id"],
            "expected_version_id": second["version_id"]}, headers=headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["data"]["revision"] == 3
        assert client.put(f"/api/skills/{skill_id}", json={"content": "# Stale",
            "expected_version_id": second["version_id"]}, headers=headers).status_code == 409
        assert client.post(f"/api/skills/{skill_id}/rollback", json={"version_id": first["version_id"],
            "expected_version_id": second["version_id"]}, headers=headers).status_code == 409
        assert client.get(f"/api/agents/{agent}/skills", headers=headers).json()["data"][0]["version_id"] == first["version_id"]
        assert client.put(f"/api/agents/{agent}/skills/{skill_id}/version", json={"version_id": None},
            headers=headers).json()["data"]["revision"] == 3
        other = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
        assert client.get(f"/api/skills/{skill_id}/versions", headers=other).status_code != 200
        assert client.put(f"/api/agents/{agent}/skills/{skill_id}/version", json={"version_id": None},
            headers=other).status_code != 200
