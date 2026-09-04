from tests.app.server_v2.conftest import register_and_login


def test_create_update_and_list_agents(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/agents",
        json={
            "name": "Writer",
            "instructions": "Always answer in one sentence.",
        },
        headers=headers,
    )
    assert created.status_code == 200
    agent_id = created.json()["data"]["id"]
    listed = client.get("/api/agents", headers=headers)
    assert listed.status_code == 200
    names = {item["name"] for item in listed.json()["data"]}
    assert {"Main Assistant", "Writer"} <= names
    updated = client.put(
        f"/api/agents/{agent_id}",
        json={"name": "Editor", "instructions": "Edit, then answer."},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Editor"
    detail = client.get(f"/api/agents/{agent_id}", headers=headers)
    assert detail.json()["data"]["instructions"] == "Edit, then answer."


def test_create_mcp_server(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/mcp",
        json={"name": "files", "protocol": "stdio", "command": "npx"},
        headers=headers,
    )
    assert created.status_code == 200
    listed = client.get("/api/mcp", headers=headers)
    assert [item["name"] for item in listed.json()["data"]] == ["files"]
