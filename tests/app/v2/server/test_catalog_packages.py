"""Database, immutable inventory, admission and actual sandbox use one package."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.v2.server.catalog.orm import AgentRow
from app.v2.server.catalog.packages import package_owner
from app.v2.server.catalog.repository import DatabaseCatalogStore
from app.v2.server.catalog.records import AgentRecord
from app.v2.server.packages.repository import DatabasePackageStore
from app.v2.server.skills.orm import AgentSkillSelectionRow
from app.v2.server.skills.records import AgentSkillBinding
from app.v2.server.skills.repository import DatabaseSkillStore
from app.v2.server.main import create_app
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.identity.orm import UserRow, ApiKeyRow
from app.v2.server.conversations.orm import ThreadRow
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
    old_ref = agent.package.content_hash
    edited = agent.with_configuration(name="After", sandbox={"network": "unrestricted"})
    await store.update_agent("alice", edited)
    async with store.database.transaction() as db:
        row = await db.get(AgentRow, agent.id)
        assert row.package_ref == edited.package.content_hash
        row.instructions = "obsolete compatibility column"
        row.tools = ["not-a-tool"]
    reloaded = await DatabaseCatalogStore(store.database).get("alice")
    current = next(a for a in reloaded.agents if a.id == agent.id)
    assert current.name == "After" and current.instructions == "original"
    assert current.tools == ["file_read"] and current.sandbox.network == "unrestricted"
    old = await store.packages.get(package_owner("alice"), old_ref)
    assert old.manifest.agents[agent.id].name == "Before"
    assert old.manifest.agents[agent.id].sandbox.network == "none"


async def test_legacy_migration_preserves_ids_models_tools_bindings_and_is_idempotent(
    store, tmp_path
):
    agent = AgentRecord(
        id="agent_legacy",
        name="Legacy",
        instructions="keep",
        model_id="my-model",
        tools=["file_write"],
    )
    await store.create_agent("alice", agent)
    workspace = tmp_path / "tenants/alice/agent_legacy/workspace"
    workspace.mkdir(parents=True)
    (workspace / "keep.txt").write_text("unchanged")
    async with store.database.transaction() as db:
        row = await db.get(AgentRow, agent.id)
        row.package_ref = None
        db.add(
            ThreadRow(
                thread_id="existing-session",
                user_id="alice",
                title="keep",
                agent_id=agent.id,
                updated_at="before",
            )
        )
        db.add(
            ApiKeyRow(
                key_id="key",
                owner_user_id="alice",
                agent_id=agent.id,
                name="keep",
                key_hash="hash",
                scopes="a2a:invoke",
                created_at="before",
                revoked_at="",
            )
        )
        db.add(
            AgentSkillSelectionRow(
                owner_user_id="alice",
                agent_id=agent.id,
                skill_name="demo",
                source_skill_id="skill-demo",
                position=0,
            )
        )
    await store.migrate_packages()
    first = next(a for a in (await store.get("alice")).agents if a.id == agent.id)
    assert first.id == agent.id and first.model_id == "my-model"
    assert first.instructions == "keep" and first.tools == ["file_write"]
    assert first.skills == ["demo"] and first.sandbox.network == "none"
    await store.migrate_packages()
    second = next(a for a in (await store.get("alice")).agents if a.id == agent.id)
    assert second.package == first.package
    async with store.database.session() as db:
        binding = await db.scalar(
            select(AgentSkillSelectionRow).where(
                AgentSkillSelectionRow.agent_id == agent.id
            )
        )
        assert binding.source_skill_id == "skill-demo" and binding.position == 0
        assert (await db.get(ThreadRow, "existing-session")).agent_id == agent.id
        key = await db.get(ApiKeyRow, "key")
        assert (
            key.agent_id == agent.id and key.key_hash == "hash" and key.revoked_at == ""
        )
    assert (workspace / "keep.txt").read_text() == "unchanged"


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
    provider = host.execution.sandbox_provider
    original = provider.provision

    async def capture(spec, context, *, run_id):
        specs.append(spec)
        return await original(spec, context, run_id=run_id)

    monkeypatch.setattr(provider, "provision", capture)
    with TestClient(create_app(host)) as client:
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
        assert all(spec.filesystem.allowed_roots == ("/workspace",) for spec in specs)

        # Corrupting the old columns must not change the configuration source.
        async def persisted():
            owner = await host.catalog.agent_owner(agent_id)
            catalog = await DatabaseCatalogStore(host.database).get(owner)
            return next(a for a in catalog.agents if a.id == agent_id)

        saved = client.portal.call(persisted)
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


async def test_missing_inventory_fails_closed_instead_of_using_legacy_columns(store):
    agent = (await store.get("alice")).agents[0]
    async with store.database.transaction() as db:
        row = await db.get(AgentRow, agent.id)
        row.package_ref = "f" * 64
    with pytest.raises(ValueError, match="package is missing"):
        await store.get("alice")


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
