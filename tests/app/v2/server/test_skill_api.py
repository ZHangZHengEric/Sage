import io
import zipfile

from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from app.v2.server.skills.files import inspect_skill_zip
from tests.app.v2.server.conftest import make_test_service, register_and_login


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _client(tmp_path):
    service = make_test_service(tmp_path)
    return TestClient(create_app(service=service)), service


def test_publish_bind_and_keep_relative_artifact_path(tmp_path):
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
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
        assert "dimension" not in skill
        assert skill["owner_user_id"]
        assert skill["artifact_path"].startswith("users/")
        assert "/" != skill["artifact_path"][0] or skill["artifact_path"].startswith(
            "users/"
        )
        assert not skill["artifact_path"].startswith("/")

        bound = client.put(
            f"/api/agents/{agent_id}/skills",
            json={"names": ["demo"]},
            headers=headers,
        )
        assert bound.status_code == 200
        listed = client.get(f"/api/agents/{agent_id}/skills", headers=headers)
        assert listed.status_code == 200
        assert [item["name"] for item in listed.json()["data"]] == ["demo"]
        assert listed.json()["data"][0]["workspace_status"] == "missing"


def test_workspace_write_does_not_change_catalog_artifact(tmp_path):
    client, service = _client(tmp_path)
    with client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
        created = client.post(
            "/api/skills",
            json={
                "name": "demo",
                "content": "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
            },
            headers=headers,
        ).json()["data"]
        client.put(
            f"/api/agents/{agent_id}/skills", json={"names": ["demo"]}, headers=headers
        )
        written = client.put(
            f"/api/workspace/skills/demo?agent_id={agent_id}",
            json={"content": "---\nname: demo\ndescription: local\n---\n\n# Local\n"},
            headers=headers,
        )
        assert written.status_code == 200
        assert written.json()["data"]["status"] == "modified"
        catalog_text = (
            service.paths.data_root / "skills" / created["artifact_path"] / "SKILL.md"
        ).read_text(encoding="utf-8")
        assert "# Demo" in catalog_text
        assert "# Local" not in catalog_text


def test_inspect_zip_unwraps_wrapper_folder_and_rejects_traversal():
    wrapped = _zip_bytes(
        {
            "demo/SKILL.md": "---\nname: demo\ndescription: From zip\n---\n\n# Demo\n",
            "demo/notes.txt": "keep",
        }
    )
    package = inspect_skill_zip(wrapped, filename="demo.zip")
    assert package.name == "demo"
    assert set(package.files) == {"SKILL.md", "notes.txt"}

    sneaky = io.BytesIO()
    with zipfile.ZipFile(sneaky, "w") as archive:
        archive.writestr("../SKILL.md", "---\nname: evil\ndescription: no\n---\n")
    try:
        inspect_skill_zip(sneaky.getvalue(), filename="evil.zip")
    except SageV2Error as exc:
        assert exc.info.category == ErrorCategory.VALIDATION
    else:
        raise AssertionError("zip slip should be rejected")


def test_upload_zip_batch_partial_success(tmp_path):
    good = _zip_bytes(
        {"writer/SKILL.md": "---\nname: writer\ndescription: Writer\n---\n\n# Writer\n"}
    )
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/skills/upload",
            files=[
                ("files", ("writer.zip", good, "application/zip")),
                ("files", ("notes.txt", b"not a zip", "text/plain")),
            ],
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["success_count"] == 1
        assert payload["failed_count"] == 1
        assert payload["skills"][0]["name"] == "writer"
        assert payload["skills"][0]["artifact_path"].startswith("users/")
        assert payload["results"][1]["success"] is False
        listed = client.get("/api/skills", headers=headers)
        assert [item["name"] for item in listed.json()["data"]] == ["writer"]


def test_skill_file_browser_lists_and_reads_nested_text_and_binary(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("writer/SKILL.md", "---\nname: writer\ndescription: Writer\n---\n# Writer\n")
        archive.writestr("writer/references/guide.md", "# Guide\nDetails\n")
        archive.writestr("writer/assets/pixel.png", b"\x89PNG\r\n\x1a\n\x00")
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        uploaded = client.post(
            "/api/skills/upload",
            files=[("files", ("writer.zip", payload.getvalue(), "application/zip"))],
            headers=headers,
        )
        skill_id = uploaded.json()["data"]["skills"][0]["skill_id"]
        base = f"/api/skills/{skill_id}/files"
        listed = client.get(base, headers=headers)
        assert listed.status_code == 200
        assert {item["path"] for item in listed.json()["data"]} == {
            "SKILL.md", "references/guide.md", "assets/pixel.png"
        }
        guide = client.get(f"{base}/references/guide.md", headers=headers)
        assert guide.status_code == 200
        assert guide.content == b"# Guide\nDetails\n"
        image = client.get(f"{base}/assets/pixel.png", headers=headers)
        assert image.content == b"\x89PNG\r\n\x1a\n\x00"
        assert image.headers["x-content-type-options"] == "nosniff"
        other = register_and_login(client, "bob")
        assert client.get(base, headers={"Authorization": f"Bearer {other}"}).status_code == 404
        client.cookies.clear()
        assert client.get(base).status_code == 401
        assert client.get(f"{base}/references/missing.md", headers=headers).status_code == 404


def test_publish_rejects_removed_dimension(tmp_path):
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        response = client.post(
            "/api/skills",
            json={"name": "demo", "content": "# Demo", "dimension": "system"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422
