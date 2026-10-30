"""RSI checkpoints share the managed package inventory, scoped to an owner."""

import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.schema import create_host_schema
from app.v2.server.packages.repository import DatabasePackageStore


@pytest.fixture
async def store(tmp_path):
    from app.v2.server.optimization.repository import RsiRepository

    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    await create_host_schema(database)
    try:
        yield RsiRepository(DatabasePackageStore(database))
    finally:
        await database.stop()


async def test_request_id_is_idempotent_and_owner_agent_scoped(store):
    first, created = await store.create("alice", "agent", "request", "digest", {"id": "run-1"})
    again, duplicate = await store.create("alice", "agent", "request", "digest", {"id": "run-2"})
    assert created and not duplicate and first == again
    with pytest.raises(ValueError, match="conflict"):
        await store.create("alice", "agent", "request", "changed", {"id": "run-3"})
    with pytest.raises(ValueError, match="not found"):
        await store.get("bob", "agent", "run-1")
    with pytest.raises(ValueError, match="not found"):
        await store.get("alice", "other", "run-1")
    assert [r["id"] for r in await store.list("alice", "agent")] == ["run-1"]
    assert await store.list("bob", "agent") == []


async def test_lease_prevents_duplicate_execution_and_stale_writes(store):
    await store.create("alice", "agent", "request", "digest", {"id": "run", "status": "queued"})
    claimed = await store.claim("alice", "agent", "run", "host-a", now=100)
    assert claimed["status"] == "running"
    with pytest.raises(ValueError, match="conflict"):
        await store.claim("alice", "agent", "run", "host-b", now=101)
    claimed = await store.claim("alice", "agent", "run", "host-b", now=200)
    with pytest.raises(ValueError, match="lease"):
        await store.update("alice", "agent", "run", "host-a", {"status": "completed"})
    await store.update("alice", "agent", "run", "host-b", {"status": "interrupted"})
    assert (await store.get("alice", "agent", "run"))["status"] == "interrupted"
