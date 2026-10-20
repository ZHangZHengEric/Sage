"""Historical admitted Agent identity survives small metadata projections.

The existing metadata-page tests cover owner, order and raw Agent filtering.
These regressions protect the valid older Server composition identity, including
cold storage replay, and the observable A2A GetTask/ListTasks agreement.
"""

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from sagents.v2.contracts.commands import RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from sagents.v2.runtime.session.run_metadata import metadata_from_payload, metadata_from_run
from sagents.v2.runtime.session.state import SessionStoreCoordinator


CONTEXT = RequestContext(actor=ActorRef(
    principal_id="owner", principal_type="user", tenant_id="owner",
))


def legacy_command():
    # Use the real composition serializer: a catalog ID can legitimately differ
    # from the package's compiled graph identity, without an execution grant.
    from app.v2.server.catalog.records import AgentRecord
    from app.v2.server.conversations.composition import composition_metadata, load_composition

    agent = AgentRecord(id="catalog-a", name="Catalog Agent")
    package = agent.package.model_dump(mode="json")
    package["manifest"]["metadata"]["id"] = "compiled.package"
    agent = AgentRecord(id="catalog-a", name="Catalog Agent", package=package)
    command = StartRun(
        agent_id="compiled.package", session_id="legacy", input=(),
        idempotency_key="legacy", resolved_spec_hash="sha256:legacy",
        config=RunConfig(enabled_skills=(), metadata=composition_metadata(agent=agent, skills=(), mcp_servers=())),
    )
    assert "server_v2.execution" not in command.config.metadata
    assert load_composition(command, user_id="owner").agent.id == "catalog-a"
    return command


@pytest.mark.parametrize(("metadata", "parent", "expected"), [
    ({"server_v2.composition": {"agent": {"id": "catalog-a"}}}, None, "catalog-a"),
    ({"server_v2.execution": {"agent_id": "granted"},
      "server_v2.composition": {"agent": {"id": "catalog-a"}}}, None, "granted"),
    ({}, None, "compiled.package"),
    ({"server_v2.execution": {"agent_id": "granted"},
      "server_v2.composition": {"agent": {"id": "catalog-a"}}}, "parent", "compiled.package"),
], ids=["legacy-composition", "execution-precedence", "raw-fallback", "child-admitted-agent"])
def test_metadata_identity_preserves_root_precedence_and_child_admission(metadata, parent, expected):
    command = StartRun(agent_id="compiled.package", session_id="session", input=(),
        idempotency_key="start", resolved_spec_hash="sha256:spec", parent_run_id=parent,
        config=RunConfig(metadata=metadata))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = SimpleNamespace(session_id="session", run_id="run", created_at=now, state=RunState.QUEUED)
    typed = metadata_from_run(row, command)
    payload, _ = metadata_from_payload({
        "sessions": [{"session_id": "session", "created_at": now.isoformat(),
                      "owner": CONTEXT.actor.model_dump(mode="json")}],
        "runs": [{"session_id": "session", "run_id": "run", "created_at": now.isoformat(),
                  "state": "queued", "start_command": command.model_dump(mode="json")}],
    })
    assert (typed.agent_id, typed.admitted_agent_id) == (expected, "compiled.package")
    assert [(value.agent_id, value.admitted_agent_id) for value in payload] == [(expected, "compiled.package")]


@pytest.fixture(params=["memory", "filesystem", "mysql", "redis"])
async def identity_store(request, tmp_path):
    backend = request.param
    prefix = "identity_" + uuid4().hex[:10]
    mysql_dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN")
    redis_url = os.environ.get("SAGE_V2_TEST_REDIS_URL")
    if backend == "mysql" and not mysql_dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN for real MySQL metadata identity")
    if backend == "redis" and not (mysql_dsn and redis_url):
        pytest.skip("set MySQL and Redis test URLs for unarchived cold Redis metadata identity")
    from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState, _SCHEMA_TABLES
    from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore

    if backend == "memory":
        store = SessionStoreCoordinator()
    elif backend == "filesystem":
        store = FilesystemSessionStore(tmp_path / "state")
    elif backend == "mysql":
        store = _MysqlSessionState(mysql_dsn, table_prefix=prefix)
    else:
        store = RedisMysqlSessionStore(mysql_dsn, table_prefix=prefix, redis_url=redis_url,
            key_prefix=prefix, archive_interval_seconds=3600)

        async def idle_archive():
            await asyncio.Event().wait()

        store._archive_loop = idle_archive
    try:
        yield backend, store, tmp_path / "state"
    finally:
        if backend != "memory":
            await store.close()
        if backend in {"mysql", "redis"}:
            cleanup = _MysqlSessionState(mysql_dsn, table_prefix=prefix)
            try:
                await cleanup._ensure_ready()
                async with cleanup._writer_connection() as connection:
                    async with connection.cursor() as cursor:
                        for table in reversed(_SCHEMA_TABLES):
                            await cursor.execute(f"DROP TABLE IF EXISTS {cleanup._table(table)}")
                    await connection.commit()
            finally:
                await cleanup.close()
        if backend == "redis":
            from redis.asyncio import Redis
            client = Redis.from_url(redis_url, decode_responses=True)
            try:
                keys = [key async for key in client.scan_iter(match=f"{prefix}:*")]
                if keys:
                    await client.delete(*keys)
            finally:
                await client.aclose()


async def test_legacy_composition_agent_remains_visible_in_cold_metadata_pages(identity_store):
    backend, store, path = identity_store
    result = await store.create_run(legacy_command(), CONTEXT)
    if backend == "filesystem":
        await store.close()
        reader = FilesystemSessionStore(path)
        reader._read_session_aggregate = lambda *_: pytest.fail("full Session history decoded")
        reader._ensure_session_loaded = AsyncMock(side_effect=AssertionError("aggregate installed"))
    else:
        reader = store
        if backend in {"mysql", "redis"}:
            store._evict_session_locked("legacy")
            store._fetch_session = AsyncMock(side_effect=AssertionError("full Session history fetched"))
        if backend == "redis":
            assert await store._archive.revision("legacy") is None
            store._archive._run_metadata_batch = AsyncMock(side_effect=AssertionError("unarchived state read from MySQL"))
    try:
        rows = await reader.authorized_run_metadata_page(["legacy"], CONTEXT, agent_id="catalog-a")
        assert [(row.run_id, row.agent_id, row.admitted_agent_id) for row in rows] == [
            (result.handle.run_id, "catalog-a", "compiled.package"),
        ]
        assert not await reader.authorized_run_metadata_page(["legacy"], CONTEXT, agent_id="foreign")
    finally:
        if reader is not store:
            await reader.close()


async def test_a2a_legacy_task_get_and_list_share_the_authorized_catalog_agent():
    from app.v2.server.conversations.a2a.service import A2AService
    from app.v2.server.identity.keys import ApiKeyRecord
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess
    from tests.app.v2.server.fakes import MemoryThreadIndex

    store = SessionStoreCoordinator()
    run_id = (await store.create_run(legacy_command(), CONTEXT)).handle.run_id
    threads = MemoryThreadIndex()
    await threads.upsert("legacy", "owner", agent_id="catalog-a")
    api = A2AService(threads=threads, catalog=None, admission=None, runs=None, application=None,
        session_access=AuthorizedSessionAccess(store), context_for=lambda *_: CONTEXT,
        language="en", public_base_url="")
    own = ApiKeyRecord(key_id="own", owner_user_id="owner", agent_id="catalog-a")
    foreign = own.model_copy(update={"key_id": "foreign", "agent_id": "other-agent"})
    with pytest.raises(SageV2Error, match="task not found"):
        await api.get_task(run_id, foreign)
    assert await api.list_tasks(foreign) == ([], "")
    expected = await api.get_task(run_id, own)
    actual, cursor = await api.list_tasks(own)
    assert [task.SerializeToString() for task in actual] == [expected.SerializeToString()]
    assert not cursor
