from io import BytesIO
from zipfile import ZipFile

from tests.app.v2.server.conftest import register_and_login


def _skill_zip(name="project-guide"):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", f"---\nname: {name}\ndescription: Project guide\n---\n# Guide\n")
        archive.writestr("references/example.txt", "reference\n")
    return buffer.getvalue()


def _upload(client, path, machine, prompt, *files):
    return client.put(path, headers=machine, data={"prompt": prompt}, files=[
        ("files", (name, body, "application/zip")) for name, body in files
    ])


def test_agent_guidance_zip_batch_resolves_agent_and_is_idempotent(client, service):
    owner_token = register_and_login(client)
    owner = {"Authorization": f"Bearer {owner_token}"}
    agent = client.get("/api/agents", headers=owner).json()["data"][0]
    agent_id = agent["id"]
    machine = {}
    path = f"/api/agents/{agent_id}/guidance"
    zipped = _skill_zip()

    assert _upload(client, "/api/agents/agent_other/guidance", machine,
                   "Create projects safely.", ("project-guide.zip", zipped)).status_code == 404

    first = _upload(client, path, machine, "Create projects safely.",
                    ("project-guide.zip", zipped), ("broken.zip", b"not a zip"))
    assert first.status_code == 200, first.text
    assert first.json()["data"]["success_count"] == 1
    assert first.json()["data"]["failed_count"] == 1
    updated = client.get(f"/api/agents/{agent_id}", headers=owner).json()["data"]
    assert updated["instructions"] == "Create projects safely."
    assert "project-guide" in updated["skills"]
    records = client.get("/api/skills", headers=owner).json()["data"]
    record = next(item for item in records if item["name"] == "project-guide")

    workspace = service.paths.workspace_dir("existing-tenant", agent_id) / "skills" / "project-guide"
    workspace.mkdir(parents=True)
    (workspace / "SKILL.md").write_text("old\n")
    (workspace / "extra.txt").write_text("old extra\n")
    second = _upload(client, path, machine, "Create projects safely.", ("project-guide.zip", zipped))
    assert second.status_code == 200, second.text
    assert (workspace / "SKILL.md").read_text().startswith("---\nname: project-guide")
    assert (workspace / "references" / "example.txt").read_text() == "reference\n"
    assert not (workspace / "extra.txt").exists()
    third = _upload(client, path, machine, "Create projects safely.", ("project-guide.zip", zipped))
    assert third.status_code == 200, third.text
    assert third.json()["data"]["results"][0]["changed"] is False
    records_after = client.get("/api/skills", headers=owner).json()["data"]
    assert next(item for item in records_after if item["name"] == "project-guide")["version_id"] == record["version_id"]


def test_agent_guidance_rejects_unknown_agent_without_creating_owner(client):
    response = _upload(client, "/api/agents/agent_missing/guidance", {},
                       "x", ("guide.zip", _skill_zip("guide")))
    assert response.status_code == 404
