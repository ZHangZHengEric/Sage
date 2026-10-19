from unittest.mock import patch

from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_admin import admin_login


def test_editor_resources_are_lightweight_scoped_and_never_discover_tools(client, monkeypatch):
    alice = {'Authorization': f'Bearer {register_and_login(client, "alice")}'}
    bob = {'Authorization': f'Bearer {register_and_login(client, "bob")}'}
    uid = client.get('/api/auth/session', headers=alice).json()['data']['user_id']
    client.post('/api/models', headers=alice, json={'model': 'alice-model', 'api_key': 'secret-alice'})
    client.post('/api/skills', headers=alice, json={
        'name': 'research', 'content': '---\nname: research\ndescription: Research\n---\nprivate body',
    })
    client.post('/api/mcp', headers=alice, json={'name': 'notes', 'url': 'https://example.com/mcp'})
    def no_discovery(*args):
        raise AssertionError('editor must not discover remote tools')
    monkeypatch.setattr(client.app.state.service.catalog.mcp_plugins, 'get', no_discovery)
    own = client.get('/api/agents/editor-resources', headers=alice)
    assert own.status_code == 200, own.text
    data = own.json()['data']
    assert data['models'][0]['model'] == 'alice-model'
    assert set(data['models'][0]) == {'id', 'model', 'is_default'}
    assert data['skills'][0]['name'] == 'research'
    assert data['external_tool_groups'] == [{'source': 'mcp', 'name': 'notes', 'tools': []}]
    assert data['plugins']['configurable']
    assert all('input_schema' not in tool for tool in data['tools'])
    assert 'secret-alice' not in own.text and 'private body' not in own.text
    assert client.get('/api/agents/editor-resources', headers=bob).json()['data']['models'] == []
    assert client.get('/api/agents/editor-resources', headers={**bob, 'X-Sage-View-User': uid}).status_code == 403
    admin = {'Authorization': f'Bearer {admin_login(client)}', 'X-Sage-View-User': uid}
    assert client.get('/api/agents/editor-resources', headers=admin).json()['data'] == data
    assert client.get('/api/agents/editor-resources?include_plugins=false', headers=alice).json()['data']['plugins'] is None


def test_detail_reads_one_agent_without_loading_the_catalog(client):
    headers = {'Authorization': f'Bearer {register_and_login(client)}'}
    agent = client.post('/api/agents', headers=headers, json={'name': 'Writer'}).json()['data']
    with patch.object(client.app.state.service.catalog.store, 'get', side_effect=AssertionError('full catalog read')):
        response = client.get(f'/api/agents/{agent["id"]}', headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['data']['name'] == 'Writer'


def test_approval_options_keep_real_remote_keys_without_schemas(client, monkeypatch):
    from types import SimpleNamespace
    from sagents.v2.tool.contracts import ToolDefinition

    async def list_tools(*, run_id):
        return (ToolDefinition(name='mcp_notes_read', description='Read notes', input_schema={},
                               approval_key='mcp:notes:read.remote'),)
    monkeypatch.setattr(client.app.state.service.catalog.mcp_plugins, 'get',
                        lambda *args: SimpleNamespace(list_tools=list_tools))
    headers = {'Authorization': f'Bearer {register_and_login(client)}'}
    response = client.get('/api/tools/options', headers=headers)
    assert response.status_code == 200, response.text
    tool = next(tool for tool in response.json()['data'] if tool['name'] == 'mcp_notes_read')
    assert tool['approval_key'] == 'mcp:notes:read.remote'
    assert 'input_schema' not in tool


async def test_database_detail_does_not_read_unrelated_agent_packages(tmp_path):
    from sqlalchemy import event
    from app.v2.server.database import Database, DatabaseSettings
    from app.v2.server.database.schema import create_host_schema
    from app.v2.server.catalog.repository import DatabaseCatalogStore
    from app.v2.server.catalog.records import AgentRecord
    from app.v2.server.identity.orm import UserRow

    database = Database(DatabaseSettings(url=f'sqlite+aiosqlite:///{tmp_path}/host.db'))
    await database.start()
    try:
        await create_host_schema(database)
        async with database.transaction() as session:
            session.add(UserRow(user_id='alice', username='alice', password_hash='unused', role='user'))
        store = DatabaseCatalogStore(database)
        await store.create_agent('alice', AgentRecord(id='writer', name='Writer'))
        await store.create_agent('alice', AgentRecord(id='other', name='Other'))
        queries = []
        async with database.session() as session:
            engine = session.bind
        event.listen(engine.sync_engine, 'before_cursor_execute',
                     lambda conn, cursor, sql, params, ctx, many: queries.append((sql, params)))
        with patch.object(store, 'get', side_effect=AssertionError('full catalog read')):
            agent = await store.get_agent('alice', 'writer')
        assert agent.name == 'Writer'
        assert len(queries) == 2
        assert all('FOR UPDATE' not in sql.upper() for sql, _ in queries)
        assert 'writer' in str(queries[0][1])
        queries.clear()
        assert (await store.editor_catalog('alice')).agents == []
        assert len(queries) == 1
        assert 'managed_records' not in queries[0][0]
    finally:
        await database.stop()


def test_plugin_definitions_are_reused_for_the_running_host(client, monkeypatch):
    from app.v2.server.catalog import plugins

    headers = {'Authorization': f'Bearer {register_and_login(client)}'}
    with patch.object(plugins, 'plugin_options', wraps=plugins.plugin_options) as options:
        first = client.get('/api/plugins', headers=headers).json()['data']
        second = client.get('/api/agents/editor-resources', headers=headers).json()['data']['plugins']
        assert first == second
        assert options.call_count == 1


async def test_editor_resource_groups_use_cached_scoped_connections_only():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.v2.server.catalog.service import CatalogService

    catalog = SimpleNamespace(models=[], mcp_servers=[
        SimpleNamespace(name="文书_资料", tools=["mcp_notes_read"], disabled=False),
        SimpleNamespace(name="disabled", tools=["mcp_disabled_read"], disabled=True),
    ], a2a_agents=[SimpleNamespace(name="研究助手", skills=["a2a_research_search"], disabled=False)])
    store = SimpleNamespace(editor_catalog=AsyncMock(return_value=catalog))
    skills = SimpleNamespace(list_visible=AsyncMock(return_value=[]))
    service = CatalogService(store, mcp_plugins=None, a2a_plugins=None, skills=skills)
    resources = await service.editor_resources("alice")
    assert resources["external_tool_groups"] == [
        {"source": "mcp", "name": "文书_资料", "tools": ["mcp_notes_read"]},
        {"source": "a2a", "name": "研究助手", "tools": ["a2a_research_search"]},
    ]
    assert resources["external_tools"] == ["mcp_notes_read", "a2a_research_search"]
    store.editor_catalog.assert_awaited_once_with("alice")
    skills.list_visible.assert_awaited_once_with(user_id="alice", role="user")
