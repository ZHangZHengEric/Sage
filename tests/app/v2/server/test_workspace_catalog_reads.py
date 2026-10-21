"""Workspace lists read only their catalog section, independent of user count."""

from typing import cast

from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.v2.server.catalog.orm import CatalogRow
from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.catalog.orm import AgentRow
from app.v2.server.runtime.policy import ExecutionPolicy
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_admin import admin_login


async def test_execution_policy_read_is_scoped_lightweight_and_observes_revocation(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    try:
        await create_host_schema(database)
        async with database.transaction() as session:
            session.add(AgentRow(id="agent", owner_user_id="alice", name="Agent",
                tools=[], execution_policy={"shell": "sandboxed"}, package_ref="missing-package"))
        store = DatabaseCatalogStore(database)
        statements = []
        async with database.session() as session:
            engine = session.bind
        event.listen(engine.sync_engine, "before_cursor_execute",
                     lambda conn, cursor, sql, params, ctx, many: statements.append(sql))
        with patch.object(store, "get", side_effect=AssertionError("must not load catalog")):
            assert await store.get_execution_policy("alice", "agent") == ExecutionPolicy(shell="sandboxed")
        assert len(statements) == 1
        assert "packages" not in statements[0].lower()
        assert "instructions" not in statements[0].lower()
        assert "FOR UPDATE" not in statements[0].upper()
        assert await store.get_execution_policy("bob", "agent") is None
        async with database.transaction() as session:
            row = await session.get(AgentRow, "agent")
            cast('AgentRow', row).execution_policy = {"shell": "deny"}
        assert (cast('ExecutionPolicy', await store.get_execution_policy("alice", "agent"))).shell == "deny"
        async with database.transaction() as session:
            await session.delete(await session.get(AgentRow, "agent"))
        assert await store.get_execution_policy("alice", "agent") is None
    finally:
        await database.stop()


@pytest.mark.parametrize("section", ["models", "mcp_servers", "a2a_agents"])
async def test_resource_listing_batches_reads_without_resolving_agents(tmp_path, section):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    try:
        await create_host_schema(database)
        async with database.transaction() as session:
            session.add_all([CatalogRow(user_id=owner, default_agent_id="", models=[{
                "id": "same-id", "model": owner, "api_key": "secret",
            }], mcp_servers=[{"name": owner, "url": "https://example.com/mcp", "api_key": "secret"}],
                a2a_agents=[{"name": owner, "url": "https://example.com/a2a", "api_key": "secret"}])
                for owner in ["alice", "bob"]])
        store = DatabaseCatalogStore(database)
        statements = []
        # Count statements through the active connection without relying on engine internals.
        async with database.session() as session:
            engine = session.bind
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, sql, params, ctx, many: statements.append(sql))
        with patch.object(store, "get", side_effect=AssertionError("must not load agents")):
            rows = (await store.list_all_models(["bob", "alice", "missing"]) if section == "models"
                    else await store.list_resources(["bob", "alice", "missing"], section))
        assert [owner for owner, _ in rows] == ["bob", "alice"]
        assert all("secret" not in str(item.public_dict()) for _, item in rows)
        assert len(statements) == 1
        assert "FOR UPDATE" not in statements[0].upper()
        assert " join " not in statements[0].lower()
        assert await store.list_resources([], section) == []
        assert len(statements) == 1
    finally:
        await database.stop()


def test_admin_workspace_resources_are_owned_scoped_and_secret_free(client):
    alice = {"Authorization": f"Bearer {register_and_login(client, 'alice')}"}
    client.post('/api/models', headers=alice, json={'model': 'alice-model', 'api_key': 'secret-alice'})
    for path in ['mcp', 'a2a-agents']:
        saved = client.post(f'/api/{path}', headers=alice, json={
            'name': 'same-name', 'url': 'https://example.com/api', 'api_key': 'secret-alice',
        })
        assert saved.status_code == 200, saved.text
    skill = client.post('/api/skills', headers=alice, json={
        'name': 'alice-skill', 'content': '---\nname: alice-skill\ndescription: example\n---\nprivate body',
    }).json()['data']
    admin = {"Authorization": f"Bearer {admin_login(client)}"}
    for path in ['models', 'mcp', 'a2a-agents', 'skills']:
        assert client.get(f'/api/admin/{path}', headers=alice).status_code == 403
        response = client.get(f'/api/admin/{path}', headers=admin)
        assert response.status_code == 200, response.text
        assert 'secret-alice' not in response.text
        if path in ['models', 'mcp', 'a2a-agents']:
            assert {row['username'] for row in response.json()['data']} == {'alice'}
    rows = client.get('/api/admin/skills', headers=admin).json()['data']
    row = next(row for row in rows if row['skill_id'] == skill['skill_id'])
    assert row['username'] == 'alice'
    assert row['user_id'] == skill['owner_user_id']
    assert 'private body' not in str(rows)
