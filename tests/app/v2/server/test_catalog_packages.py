"""Database, immutable inventory, admission and actual sandbox use one package."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from sagents.v2.agent.management.contracts import AgentPackageBundle

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.v2.server.catalog.orm import AgentRow
from app.v2.server.catalog.packages import package_owner
from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.catalog.records import AgentRecord
from app.v2.server.packages.repository import DatabasePackageStore
from app.v2.server.skills.records import AgentSkillBinding
from app.v2.server.skills.repository import DatabaseSkillStore
from app.v2.server.main import create_app
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.orm import UserRow
from sagents.v2.contracts.errors import SageV2Error
from tests.app.v2.server.test_external_chat import make_host
from tests.app.v2.server.conftest import register_and_login


@pytest.fixture
async def store(tmp_path):
    database = Database(
        DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/catalog.db")
    )
    await database.start()
    await create_host_schema(database)
    async with database.transaction() as db:
        db.add(
            UserRow(
                user_id="alice", username="alice", password_hash="test", role="user"
            )
        )
    try:
        yield DatabaseCatalogStore(database)
    finally:
        await database.stop()


async def test_package_is_persistent_authority_and_old_versions_remain_readable(store):
    agent = AgentRecord(
        id="agent_test", name="Before", instructions="original", tools=["file_read"]
    )
    await store.create_agent("alice", agent)
    old_ref = cast('AgentPackageBundle', agent.package).content_hash
    edited = agent.with_configuration(name="After", sandbox={"network": "unrestricted"})
    await store.update_agent("alice", edited)
    async with store.database.transaction() as db:
        row = await db.get(AgentRow, agent.id)
        assert row.package_ref == cast('AgentPackageBundle', edited.package).content_hash
        row.instructions = "obsolete compatibility column"
        row.tools = ["not-a-tool"]
    reloaded = await DatabaseCatalogStore(store.database).get("alice")
    current = next(a for a in reloaded.agents if a.id == agent.id)
    assert current.name == "After" and current.instructions == "original"
    assert current.tools == ["file_read"] and current.sandbox.network == "unrestricted"
    old = await store.packages.get(package_owner("alice"), old_ref)
    assert old.manifest.agents[agent.id].name == "Before"
    assert old.manifest.agents[agent.id].sandbox.network == "none"


async def test_skill_index_and_package_commit_and_rollback_together(store, monkeypatch):
    agent = (await store.get("alice")).agents[0]
    skills = DatabaseSkillStore(store.database)
    binding = AgentSkillBinding("alice", agent.id, "demo", "source", 0)
    await skills.replace_bindings(
        owner_user_id="alice", agent_id=agent.id, bindings=[binding]
    )
    current = (await store.get("alice")).agents[0]
    assert current.skills == ["demo"]
    ref = current.package.content_hash

    async def fail(*args, **kwargs):
        raise RuntimeError("simulated inventory failure")

    monkeypatch.setattr(DatabasePackageStore, "save_in_transaction", fail)
    with pytest.raises(RuntimeError, match="inventory failure"):
        await skills.replace_bindings(
            owner_user_id="alice", agent_id=agent.id, bindings=[]
        )
    assert (await skills.list_bindings(owner_user_id="alice", agent_id=agent.id))[
        0
    ].skill_name == "demo"
    assert (await store.get("alice")).agents[0].package.content_hash == ref


@pytest.mark.parametrize("requested", ["none", "unrestricted"])
@pytest.mark.parametrize("ceiling", ["none", "unrestricted"])
def test_existing_external_runs_use_persisted_package_sandbox(
    tmp_path, monkeypatch, requested, ceiling
):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, sandbox_network_mode=ceiling)
    specs = []
    with TestClient(create_app(host)) as client:
        from sagents.v2.runtime.execution.sandbox import LocalWorkspaceSandboxProvider
        original = LocalWorkspaceSandboxProvider.provision

        async def capture(provider, spec, context, *, run_id):
            specs.append(spec)
            return await original(provider, spec, context, run_id=run_id)

        monkeypatch.setattr(LocalWorkspaceSandboxProvider, "provision", capture)
        token = register_and_login(client)
        auth = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/agents",
            headers=auth,
            json={
                "name": "Shared",
                "instructions": "hello",
                "sandbox": {"network": requested},
            },
        )
        assert created.status_code == 200, created.text
        data = created.json()["data"]
        agent_id = data["id"]
        assert (
            data["package"]["manifest"]["agents"][agent_id]["sandbox"]["network"]
            == requested
        )
        # A legacy editor that omits sandbox must retain it.
        updated = client.put(
            f"/api/agents/{agent_id}", headers=auth, json={"name": "Renamed"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["sandbox"]["network"] == requested
        client.cookies.clear()
        client.headers["SAGE-AGENT-ID"] = agent_id
        key = client.post("/api/keys", headers=auth,
            json={"agent_id": agent_id, "name": "external-test"})
        assert key.status_code == 200, key.text
        client.headers["Authorization"] = "Bearer " + key.json()["data"]["api_key"]
        response = client.post(
            f"/api/agents/{agent_id}/runs",
            headers={"SAGE-TENANT-ID": "business-user"},
            json={
                "threadId": "thread",
                "runId": "run",
                "messages": [{"id": "message", "role": "user", "content": "hello"}],
            },
        )
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text
        expected = "unrestricted" if requested == ceiling == "unrestricted" else "none"
        assert specs and all(spec.network.mode.value == expected for spec in specs)
        assert all(spec.filesystem.allowed_roots == (spec.workspace_root,) for spec in specs)

        # Corrupting the old columns must not change the configuration source.
        async def persisted():
            owner = await host.catalog.agent_owner(agent_id)
            catalog = await DatabaseCatalogStore(host.database).get(cast(str, owner))
            return next(a for a in catalog.agents if a.id == agent_id)

        saved = cast('BlockingPortal', client.portal).call(persisted)
        assert saved.sandbox.network == requested


def test_network_validation_rejects_unsupported_modes(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    response = client.post(
        "/api/agents",
        headers=headers,
        json={"name": "Bad", "sandbox": {"network": "allowlist"}},
    )
    assert response.status_code == 422


async def test_package_reads_are_batched_for_a_catalog(store):
    from sqlalchemy import event

    for index in range(8):
        await store.create_agent(
            "alice", AgentRecord(id=f"agent_{index}", name=f"Agent {index}")
        )
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "managed_agent_records" in statement
        ):
            queries.append(statement)

    engine = store.database._engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        catalog = await store.get("alice")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(catalog.agents) == 9
    assert len(queries) == 1


async def test_run_catalog_reads_only_selected_package_without_locks(store):
    from sqlalchemy import event
    from sqlalchemy.dialects import mysql

    selected = AgentRecord(id="selected", name="Selected", instructions="canonical")
    unrelated = AgentRecord(id="unrelated", name="Unrelated")
    await store.create_agent("alice", selected)
    await store.create_agent("alice", unrelated)
    async with store.database.transaction() as db:
        (await db.get(AgentRow, unrelated.id)).package_ref = "missing-package"
        (await db.get(AgentRow, selected.id)).instructions = "obsolete projection"
    statements = []
    def capture(conn, cursor, sql, params, context, many):
        statements.append(str(context.compiled.statement.compile(dialect=mysql.dialect())))
    event.listen(store.database._engine.sync_engine, "before_cursor_execute", capture)
    try:
        catalog = await store.get_for_run("alice", selected.id)
    finally:
        event.remove(store.database._engine.sync_engine, "before_cursor_execute", capture)
    assert [agent.id for agent in catalog.agents] == [selected.id]
    assert catalog.agents[0].instructions == "canonical"
    assert len(statements) == 2
    assert all("FOR UPDATE" not in sql.upper() for sql in statements)
    assert not any("agent_skill_selections" in sql for sql in statements)
    assert (await store.get_for_run("alice")).agents[0].id == catalog.default_agent_id
    with pytest.raises(SageV2Error):
        await store.get_for_run("bob", selected.id)


async def test_run_catalog_resolves_live_members_and_preserves_frozen_revision(store):
    from app.v2.server.catalog.records import upsert_agent
    from app.v2.server.catalog.packages import bind_catalog_members, catalog_execution_grants

    child = AgentRecord(id="child", name="Child", instructions="before")
    await store.create_agent("alice", child)
    parent, _ = upsert_agent(await store.get("alice"), {
        "id": "parent", "name": "Parent", "agent_mode": "team",
        "available_sub_agent_ids": [child.id],
    })
    await store.create_agent("alice", parent)
    catalog = await store.get_for_run("alice", parent.id)
    assert {agent.id for agent in catalog.agents} == {parent.id, child.id}
    bundle = bind_catalog_members(catalog.agents[0], catalog)
    grants = catalog_execution_grants(bundle, catalog)
    assert grants[child.id]["agent_id"] == child.id
    await store.update_agent("alice", child.with_configuration(instructions="after"))
    refreshed = await store.get_for_run("alice", parent.id)
    assert next(agent for agent in refreshed.agents if agent.id == child.id).instructions == "after"
    assert bundle.dependencies[child.id].manifest.agents[child.id].instructions.inline == "before"
    async with store.database.transaction() as db:
        (await db.get(AgentRow, child.id)).owner_user_id = "other-owner"
    scoped = await store.get_for_run("alice", parent.id)
    with pytest.raises(SageV2Error, match="团队成员"):
        bind_catalog_members(scoped.agents[0], scoped)


async def test_run_catalog_initializes_default_and_fails_closed_on_missing_package(store):
    catalog = await store.get_for_run("alice")
    assert catalog.agents[0].id == catalog.default_agent_id
    async with store.database.transaction() as db:
        (await db.get(AgentRow, catalog.default_agent_id)).package_ref = "missing"
    with pytest.raises(ValueError, match="package is missing"):
        await store.get_for_run("alice")


async def test_missing_inventory_fails_closed_instead_of_using_legacy_columns(store):
    agent = (await store.get("alice")).agents[0]
    async with store.database.transaction() as db:
        row = await db.get(AgentRow, agent.id)
        row.package_ref = "f" * 64
    with pytest.raises(ValueError, match="package is missing"):
        await store.get("alice")


@pytest.mark.parametrize("reader", ["catalog", "agent", "summary", "run", "skill_binding"])
async def test_missing_package_reference_is_rejected_without_backfill(store, reader):
    agent = (await store.get("alice")).agents[0]
    async with store.database.transaction() as db:
        (await db.get(AgentRow, agent.id)).package_ref = ""
    with pytest.raises(ValueError, match="package is missing"):
        if reader == "catalog":
            await store.get("alice")
        elif reader == "agent":
            await store.get_agent("alice", agent.id)
        elif reader == "summary":
            await store.list_agent_summaries(["alice"])
        elif reader == "run":
            await store.get_for_run("alice", agent.id)
        else:
            await DatabaseSkillStore(store.database).replace_bindings(
                owner_user_id="alice", agent_id=agent.id,
                bindings=[AgentSkillBinding("alice", agent.id, "demo", "source", 0)],
            )
    async with store.database.session() as db:
        assert (await db.get(AgentRow, agent.id)).package_ref == ""
    assert await DatabaseSkillStore(store.database).list_bindings(
        owner_user_id="alice", agent_id=agent.id,
    ) == []


async def test_agent_edit_rolls_back_if_package_write_fails(store, monkeypatch):
    agent = (await store.get("alice")).agents[0]

    async def fail(*args, **kwargs):
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(DatabasePackageStore, "save_in_transaction", fail)
    with pytest.raises(RuntimeError, match="inventory unavailable"):
        await store.update_agent(
            "alice", agent.with_configuration(name="must not persist")
        )
    assert (await store.get("alice")).agents[0].package == agent.package


async def test_model_request_options_survive_database_reload(store):
    saved = await store.upsert_model("alice", {
        "model": "demo", "api_key": "database-test-key",
        "request": {"max_output_tokens": 4096, "temperature": 0, "top_p": 0.7, "extra": {"seed": 7}},
        "limits": {"context_window": 128000}, "capabilities": {"multimodal": True},
    })
    reloaded = await DatabaseCatalogStore(store.database).get("alice")
    model = next(item for item in reloaded.models if item.id == saved.id)
    assert model.request == saved.request
    assert model.limits == saved.limits
    assert model.capabilities == saved.capabilities
    assert model.api_key.get_secret_value() == "database-test-key"


async def test_external_scope_survives_database_reload_and_old_refs_remain_valid(store):
    import hashlib
    import json

    agent = AgentRecord(id='agent_scope', name='Scoped', external_tools=['mcp_read'])
    await store.create_agent('alice', agent)
    loaded = await DatabaseCatalogStore(store.database).get('alice')
    assert next(a for a in loaded.agents if a.id == agent.id).external_tools == ['mcp_read']
    disabled = agent.with_configuration(external_tools=[])
    await store.update_agent('alice', disabled)
    loaded = await DatabaseCatalogStore(store.database).get('alice')
    assert next(a for a in loaded.agents if a.id == agent.id).external_tools == []
    # Simulate the serialized bundle before external_tools existed.
    old = cast('AgentPackageBundle', disabled.package).model_dump(mode='json')
    for definition in old['manifest']['agents'].values():
        if not definition.get('preload_skills'):
            definition.pop('preload_skills', None)
    old_ref = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert cast('AgentPackageBundle', disabled.package).content_hash == old_ref
