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
        json={
            "name": "files",
            "protocol": "streamable_http",
            "url": "https://mcp.example.com/files",
        },
        headers=headers,
    )
    assert created.status_code == 200
    listed = client.get("/api/mcp", headers=headers)
    assert [item["name"] for item in listed.json()["data"]] == ["files"]


def test_an_unreachable_mcp_transport_is_refused_before_it_reaches_a_chat(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    stdio = client.post(
        "/api/mcp",
        json={"name": "local", "protocol": "stdio", "command": "npx"},
        headers=headers,
    )
    no_url = client.post(
        "/api/mcp",
        json={"name": "broken", "protocol": "sse"},
        headers=headers,
    )

    assert stdio.status_code == 422
    assert no_url.status_code == 422
    assert "URL" in no_url.json()["message"]
    assert client.get("/api/mcp", headers=headers).json()["data"] == []
