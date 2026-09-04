from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from tests.app.server_v2.conftest import make_test_service, register_and_login


def _client(tmp_path):
    service = make_test_service(tmp_path)
    return TestClient(create_app(service=service)), service


def test_publish_bind_and_keep_relative_artifact_path(tmp_path):
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/skills",
            json={
                "name": "demo",
                "content": "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
            },
            headers=headers,
        )
        assert created.status_code == 200
        skill = created.json()["data"]
        assert skill["artifact_path"].startswith("users/")
        assert "/" != skill["artifact_path"][0] or skill["artifact_path"].startswith("users/")
        assert not skill["artifact_path"].startswith("/")

        bound = client.put(
            "/api/agents/main/skills",
            json={"names": ["demo"]},
            headers=headers,
        )
        assert bound.status_code == 200
        listed = client.get("/api/agents/main/skills", headers=headers)
        assert listed.status_code == 200
        assert [item["name"] for item in listed.json()["data"]] == ["demo"]
        assert listed.json()["data"][0]["workspace_status"] == "missing"


def test_workspace_write_does_not_change_catalog_artifact(tmp_path):
    client, service = _client(tmp_path)
    with client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/skills",
            json={
                "name": "demo",
                "content": "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
            },
            headers=headers,
        ).json()["data"]
        client.put("/api/agents/main/skills", json={"names": ["demo"]}, headers=headers)
        written = client.put(
            "/api/workspace/skills/demo",
            json={"content": "---\nname: demo\ndescription: local\n---\n\n# Local\n"},
            headers=headers,
        )
        assert written.status_code == 200
        assert written.json()["data"]["status"] == "modified"
        catalog_text = (
            service.paths.data_root
            / "skills"
            / created["artifact_path"]
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "# Demo" in catalog_text
        assert "# Local" not in catalog_text
