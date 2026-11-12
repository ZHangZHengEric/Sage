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


def test_plugin_catalog_reports_skill_contracts_and_host_implementation(tmp_path):
    with _client(tmp_path)[0] as client:
        token = register_and_login(client)
        response = client.get("/api/plugins", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        contracts = response.json()["data"]["contracts"]
        provider = contracts["skill.provider"]
        assert provider["required_members"] == ["list_skills", "get_skill", "fetch"]
        assert {"id": "skill.search", "members": ["search_skills"], "required_when": "search_skills"} in provider["features"]
        server = next(plugin for plugin in provider["implementations"] if plugin["id"] == "com.sage.server.run.skill-provider")
        assert {"id": "skill.search", "status": "declared"} in server["features"]


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


def test_default_skill_visibility_roundtrips_in_the_agent_package(tmp_path):
    with _client(tmp_path)[0] as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        resources = client.get("/api/agents/editor-resources", headers=headers).json()["data"]
        assert any(tool["name"] == "search_skills" and not tool["default"] for tool in resources["tools"])
        response = client.post("/api/agents", headers=headers, json={
            "name": "Research", "tools": ["search_skills"],
        })
        assert response.status_code == 200
        agent_id = response.json()["data"]["id"]
        assert client.post("/api/skills", headers=headers, json={
            "name": "demo",
            "content": "---\nname: demo\ndescription: Demo\n---\n# Demo",
        }).status_code == 200
        url = f"/api/agents/{agent_id}/skills"
        assert client.put(url, headers=headers, json={
            "names": ["demo"], "default_visible_skills": ["other"],
        }).status_code == 422
        assert client.put(url, headers=headers, json={
            "names": ["demo"], "default_visible_skills": ["demo"], "default_visible_skills_limit": 25,
        }).status_code == 200
        detail = client.get(f"/api/agents/{agent_id}", headers=headers).json()["data"]
        assert detail["default_visible_skills"] == ["demo"]
        assert detail["default_visible_skills_limit"] == 25
        assert detail["package"]["manifest"]["agents"][agent_id]["default_visible_skills"] == ["demo"]
        assert detail["package"]["manifest"]["agents"][agent_id]["default_visible_skills_limit"] == 25
        assert client.put(url, headers=headers, json={"names": ["demo"]}).status_code == 200
        assert client.get(f"/api/agents/{agent_id}", headers=headers).json()["data"]["default_visible_skills"] == ["demo"]
        assert client.put(url, headers=headers, json={"names": []}).status_code == 200
        assert client.get(f"/api/agents/{agent_id}", headers=headers).json()["data"]["default_visible_skills"] == []
        assert client.put(url, headers=headers, json={"names": [], "default_visible_skills": None}).status_code == 200
        assert client.get(f"/api/agents/{agent_id}", headers=headers).json()["data"]["default_visible_skills"] is None


def test_skill_binding_package_failure_keeps_previous_settings(tmp_path, monkeypatch):
    import pytest

    client, host = _client(tmp_path)
    with client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
        url = f"/api/agents/{agent_id}/skills"
        assert client.post("/api/skills", headers=headers, json={
            "name": "demo", "content": "---\nname: demo\ndescription: Demo\n---\nGuide\n",
        }).status_code == 200
        assert client.put(url, headers=headers, json={
            "names": ["demo"], "default_visible_skills": ["demo"],
        }).status_code == 200

        async def fail_save(*args, **kwargs):
            raise RuntimeError("injected package write failure")

        with monkeypatch.context() as patch:
            patch.setattr(host.catalog.store, "update_agent", fail_save)
            with pytest.raises(RuntimeError, match="injected package write failure"):
                client.put(url, headers=headers, json={"names": [], "default_visible_skills": []})

        bound = client.get(url, headers=headers).json()["data"]
        detail = client.get(f"/api/agents/{agent_id}", headers=headers).json()["data"]
        assert [item["name"] for item in bound] == ["demo"]
        assert detail["default_visible_skills"] == ["demo"]


def test_agent_editor_save_validates_skills_before_writing_any_fields(tmp_path):
    with _client(tmp_path)[0] as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        for name in ("alpha", "beta"):
            assert client.post("/api/skills", headers=headers, json={
                "name": name, "content": f"---\nname: {name}\ndescription: Guide\n---\nBody",
            }).status_code == 200
        skills = {"names": ["alpha", "beta"], "default_visible_skills": ["alpha", "beta"]}
        agent = client.post("/api/agents", headers=headers, json={
            "name": "Before", "tools": [], "skill_bindings": skills,
        }).json()["data"]
        url = f"/api/agents/{agent['id']}"
        failed = client.put(url, headers=headers, json={
            "name": "After", "tools": ["search_skills"],
            "skill_bindings": {**skills, "default_visible_skills_limit": 1},
        })
        assert failed.status_code == 422
        assert client.get(url, headers=headers).json()["data"] == agent
        succeeded = client.put(url, headers=headers, json={
            "name": "After", "tools": ["search_skills"],
            "skill_bindings": {"names": ["beta"], "default_visible_skills": ["beta"],
                               "default_visible_skills_limit": 1},
        })
        assert succeeded.status_code == 200
        assert succeeded.json()["data"]["default_visible_skills"] == ["beta"]
        assert client.get(url, headers=headers).json()["data"]["skills"] == ["beta"]
