"""Trusted workspace reclamation probes must not hydrate unrelated history."""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from sagents.v2.runtime.session.mysql_state import _MysqlSessionState
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT
from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store


@pytest.mark.parametrize("durable", [False, True])
async def test_target_tree_probe_includes_children_but_not_unrelated_runs(tmp_path, durable):
    state = FilesystemSessionStore(tmp_path) if durable else SessionStoreCoordinator()
    try:
        parent = await state.create_run(command("root"), CONTEXT)
        await state.create_run(command("other"), CONTEXT)
        await state.create_run(command("child").model_copy(update={"parent_run_id": parent.handle.run_id}), CONTEXT)
        assert await state.has_nonterminal_session_trees([parent.handle.session_id])
        assert not await state.has_nonterminal_session_trees(["missing"])
        # Exercise a cold reopened filesystem index, including parent topology.
        if durable:
            await state.close()
            state = FilesystemSessionStore(tmp_path)
            assert await state.has_nonterminal_session_trees([parent.handle.session_id])
    finally:
        if durable:
            await state.close()


@pytest.mark.parametrize("busy", [True, False])
async def test_mysql_probe_reads_only_latest_state_projection(busy):
    state = _MysqlSessionState("mysql://unused/test")
    cursor, connection = AsyncMock(), AsyncMock()
    cursor.fetchone.return_value = (1,) if busy else None
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    @asynccontextmanager
    async def reader():
        yield connection
    state._reader_connection = reader
    state._fetch_session = AsyncMock(side_effect=AssertionError("workspace probe installed full history"))
    assert await state.has_nonterminal_session_trees(["root"]) is busy
    statement = cursor.execute.await_args.args[0]
    assert "RECURSIVE" in statement and "JSON_TABLE" in statement
    assert "run_events" not in statement
    assert "LIMIT 1" in statement
    assert not state._sessions


async def test_redis_probe_checks_unarchived_hot_run_before_archive():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive.has_nonterminal_session_trees = AsyncMock(return_value=False)
    archive.list_workspace_descendant_ids = AsyncMock(return_value=[])
    state = redis_store(redis, archive)
    try:
        root = await state.create_run(command("root"), CONTEXT)
        assert archive.writes == 0
        assert await state.has_nonterminal_session_trees([root.handle.session_id])
        archive.has_nonterminal_session_trees.assert_not_awaited()
    finally:
        await state.close()


@pytest.mark.parametrize("live", [False, True])
async def test_redis_probe_does_not_revisit_hot_terminal_child_in_stale_archive(live):
    import os
    from uuid import uuid4
    from redis.asyncio import Redis
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.runtime.session.plugins.redis_mysql import RedisMysqlSessionStore
    from tests.sagents.v2.test_redis_mysql_session_store import transition
    url = os.environ.get("SAGE_V2_TEST_REDIS_URL")
    if live and not url:
        pytest.skip("set SAGE_V2_TEST_REDIS_URL for live workspace probe")
    redis = Redis.from_url(url, decode_responses=True) if live else fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive.list_workspace_descendant_ids = AsyncMock(return_value=[])
    archive.has_nonterminal_session_trees = AsyncMock(return_value=True)
    archive.has_nonterminal_sessions = AsyncMock(return_value=False)
    prefix = "workspace-probe:" + uuid4().hex
    state = RedisMysqlSessionStore("mysql://unused/test", redis_url=url or "redis://unused/0", key_prefix=prefix)
    state._redis, state._archive = redis, archive
    if not live:
        redis.info = AsyncMock(side_effect=lambda _: {"maxmemory_policy": "noeviction", "aof_enabled": 1})
    archive_entered = asyncio.Event()
    async def idle_archive():
        archive_entered.set()
        await asyncio.Event().wait()
    state._archive_loop = idle_archive
    try:
        root = await state.create_run(command("root"), CONTEXT)
        await asyncio.wait_for(archive_entered.wait(), 3)
        assert not state._worker.done()
        await transition(state, root, RunState.CANCELLED, "cancel-root")
        child = await state.create_run(command("child").model_copy(update={"parent_run_id": root.handle.run_id}), CONTEXT)
        assert await state.has_nonterminal_session_trees([root.handle.session_id]), "unarchived child blocks deletion"
        await transition(state, child, RunState.CANCELLED, "cancel-child")
        # A cold archived root can have a resident child whose newer terminal
        # state has not yet reached MySQL. Its old archive must not win.
        await redis.srem(state._key("resident"), root.handle.session_id)
        assert not await state.has_nonterminal_session_trees([root.handle.session_id])
        archive.has_nonterminal_sessions.assert_awaited_once_with([root.handle.session_id])
        archive.has_nonterminal_sessions.reset_mock()
        await redis.sadd(state._key("suspended"), child.handle.session_id)
        assert await state.has_nonterminal_session_trees([root.handle.session_id])
        archive.has_nonterminal_sessions.assert_not_awaited()
    finally:
        await state.close()
        if live:
            cleanup = Redis.from_url(url, decode_responses=True)
            try:
                keys = [key async for key in cleanup.scan_iter(match=prefix + ":*")]
                if keys:
                    await cleanup.delete(*keys)
            finally:
                await cleanup.aclose()


async def test_redis_workspace_page_reads_global_parent_metadata_once():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive.list_workspace_descendant_ids = AsyncMock(return_value=[])
    archive.has_nonterminal_sessions = AsyncMock(return_value=False)
    state = redis_store(redis, archive)
    try:
        await state._ensure_ready()
        original = redis.hgetall
        async def parents(*args):
            return await original(*args)
        redis.hgetall = AsyncMock(side_effect=parents)
        roots = [f"root-{number}" for number in range(200)]
        assert not await state.has_nonterminal_session_trees(roots)
        redis.hgetall.assert_awaited_once_with(state._key("parents"))
        archive.list_workspace_descendant_ids.assert_awaited_once_with(sorted(roots))
    finally:
        await state.close()


async def test_live_mysql_workspace_probe_uses_current_journal_and_child_index():
    import os
    from uuid import uuid4
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.runtime.session.mysql_state import _SCHEMA_TABLES
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN for live workspace projection")
    state = _MysqlSessionState(dsn, table_prefix="workspace_" + uuid4().hex[:10])
    try:
        root = await state.create_run(command("root"), CONTEXT)
        child = await state.create_run(command("child").model_copy(update={"parent_run_id": root.handle.run_id}), CONTEXT)
        assert await state.list_workspace_descendant_ids([root.handle.session_id, "absent-root"]) == [child.handle.session_id]
        async def move(handle, target, key):
            current = await state.get_run(handle.run_id)
            await state.commit_run(run_id=handle.run_id, expected_revision=current.revision,
                expected_states={current.state}, new_state=target, drafts=(), context=CONTEXT,
                idempotency_key=key)
        await move(root.handle, RunState.RUNNING, "root-running")
        await move(root.handle, RunState.COMPLETED, "root-completed")
        assert await state.has_nonterminal_session_trees([root.handle.session_id]), "queued child must keep its root workspace busy"
        await move(child.handle, RunState.CANCELLED, "child-cancelled")
        stranger = await state.create_run(command("unrelated"), CONTEXT)
        # Every target aggregate may be cold: the SQL projection is complete.
        state._fetch_session = AsyncMock(side_effect=AssertionError("live probe fetched historical events"))
        assert not await state.has_nonterminal_session_trees([root.handle.session_id])
        assert await state.has_nonterminal_session_trees([stranger.handle.session_id])
        # Capture the adapter's actual recursive statement for a real optimizer
        # check, rather than forcing an index in an unrelated single-table SQL.
        reader = state._reader_connection
        recorded_cursor, recorded_connection = AsyncMock(), MagicMock()
        recorded_cursor.fetchone.return_value = None
        recorded_connection.cursor.return_value.__aenter__.return_value = recorded_cursor
        @asynccontextmanager
        async def record_reader():
            yield recorded_connection
        state._reader_connection = record_reader
        try:
            await state.has_nonterminal_session_trees([root.handle.session_id])
            statement, parameters = recorded_cursor.execute.await_args.args
        finally:
            state._reader_connection = reader
        async with state._reader_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"SHOW INDEX FROM {state._table('sessions')}")
                assert any(row[2] == "sessions_parent_id" for row in await cursor.fetchall())
                await cursor.execute("EXPLAIN " + statement, parameters)
                rows = await cursor.fetchall()
                child_plan = [row for row in rows if row[2] == "child"]
                assert child_plan and child_plan[0][5] == "sessions_parent_id", rows
    finally:
        if state._pool is not None:
            async with state._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for table in reversed(_SCHEMA_TABLES):
                        await cursor.execute(f"DROP TABLE IF EXISTS {state._table(table)}")
                await connection.commit()
        await state.close()
