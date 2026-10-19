from tests.app.v2.server.conftest import register_and_login


def test_tool_directory_projects_real_definitions_without_executing_tools(client, monkeypatch):
    from types import SimpleNamespace
    from sagents.v2.tool.contracts import ToolDefinition
    from sagents.v2.tool.plugins.official import official_tool_definitions

    external = ToolDefinition(
        name="mcp_notes_read", description="Read an existing note.",
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    )
    async def list_tools(*, run_id):
        assert run_id == "catalog"
        return (external,)
    monkeypatch.setattr(client.app.state.service.catalog.mcp_plugins, "get", lambda *args: SimpleNamespace(list_tools=list_tools))
    token = register_and_login(client)
    response = client.get("/api/tools", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    rows = {item["name"]: item for item in response.json()["data"]}
    official = next(item for item in official_tool_definitions() if item.name == "file_read")
    for definition in (official, external):
        row = rows[definition.name]
        assert row["description"] == definition.description
        assert row["input_schema"] == definition.input_schema
        assert row["side_effect_level"] == definition.side_effect_level.value
        assert row["requires_approval"] == definition.requires_approval
    assert rows["file_read"]["default"] is True
    assert rows[external.name]["source"] == "mcp"


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


def test_client_cannot_choose_or_overwrite_an_agent_id(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    original = client.get('/api/agents', headers=headers).json()['data'][0]
    response = client.post('/api/agents', headers=headers,
                           json={'id': original['id'], 'name': 'Overwrite'})
    assert response.status_code == 422
    response = client.put(f"/api/agents/{original['id']}", headers=headers,
                          json={'id': 'renamed', 'name': 'Overwrite'})
    assert response.status_code == 422
    assert client.get('/api/agents', headers=headers).json()['data'][0] == original


def test_agent_external_tool_scope_roundtrips_and_preserves_omitted_updates(client):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post('/api/agents', headers=headers, json={
        'name': 'Scoped', 'external_tools': ['mcp_drive_read', 'a2a_peer_search'],
    })
    assert response.status_code == 200, response.text
    agent = response.json()['data']
    assert agent['external_tools'] == ['mcp_drive_read', 'a2a_peer_search']
    assert set(agent['external_tools']) <= set(agent['package']['manifest']['agents'][agent['id']]['tools'])
    assert 'external_tools' not in agent['package']['manifest']['agents'][agent['id']]
    url = f"/api/agents/{agent['id']}"
    updated = client.put(url, headers=headers, json={'name': 'Renamed'}).json()['data']
    assert updated['external_tools'] == agent['external_tools']
    for scope in ([], ["mcp_drive_read"]):
        updated = client.put(url, headers=headers, json={'name': 'Scoped', 'external_tools': scope})
        assert updated.status_code == 200, updated.text
        assert client.get(url, headers=headers).json()['data']['external_tools'] == scope


def test_mcp_tool_definitions_follow_explicit_admin_owner_scope(client, monkeypatch):
    from types import SimpleNamespace
    from sagents.v2.tool.contracts import ToolDefinition
    from tests.app.v2.server.test_admin import admin_login

    alice = {"Authorization": f"Bearer {register_and_login(client, 'alice')}"}
    bob = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    alice_id = client.get('/api/auth/session', headers=alice).json()['data']['user_id']
    bob_id = client.get('/api/auth/session', headers=bob).json()['data']['user_id']
    owners = []

    def plugin(user_id, records):
        owners.append(user_id)

        async def list_tools(*, run_id):
            return (ToolDefinition(name='mcp_read', description=f'Owner {user_id}', input_schema={}),)

        return SimpleNamespace(list_tools=list_tools)

    monkeypatch.setattr(client.app.state.service.catalog.mcp_plugins, 'get', plugin)
    admin = {"Authorization": f"Bearer {admin_login(client)}", 'X-Sage-View-User': alice_id}
    result = client.get('/api/tools', headers=admin)
    assert result.status_code == 200, result.text
    row = next(item for item in result.json()['data'] if item['source'] == 'mcp')
    assert row['description'] == f'Owner {alice_id}'
    assert owners[-1] == alice_id
    denied = client.get('/api/tools', headers={**bob, 'X-Sage-View-User': alice_id})
    assert denied.status_code == 403
    assert owners == [alice_id]
    own = client.get('/api/tools', headers=bob)
    assert own.status_code == 200
    assert owners[-1] == bob_id
