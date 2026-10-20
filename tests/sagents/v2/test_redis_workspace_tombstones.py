"""Deleted canonical roots remain cleanup-safe while the SQL archive lags.

Workspace probe tests cover hot/cold descendants; these cases add acknowledged
Redis deletion before archive completion and retain descendants of missing roots.
"""
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from sagents.v2.contracts.run_state import RunState
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT
from tests.sagents.v2.test_redis_mysql_session_store import Archive, store, transition


@pytest.mark.parametrize('resident', [False, True])
async def test_deleted_tree_ignores_stale_archive_and_resident_tombstones(resident):
    redis, archive = fakeredis.aioredis.FakeRedis(decode_responses=True), Archive()
    archive.has_nonterminal_sessions = AsyncMock(return_value=True)
    state = store(redis, archive)
    try:
        root = await state.create_run(command('root'), CONTEXT)
        child = await state.create_run(command('child').model_copy(update={'parent_run_id':root.handle.run_id}), CONTEXT)
        ids = [root.handle.session_id, child.handle.session_id]
        archive.list_workspace_descendant_ids = AsyncMock(return_value=ids[1:])
        await transition(state, child, RunState.CANCELLED, 'child-cancelled')
        await transition(state, root, RunState.CANCELLED, 'root-cancelled')
        await state.delete_session(root.handle.session_id)
        for sid in ids:
            assert await redis.hget(state._session_key(sid), 'deleted') == '1'
        if not resident:
            await redis.srem(state._key('resident'), *ids)
        assert not await state.has_nonterminal_session_trees([ids[0]])
        archive.has_nonterminal_sessions.assert_not_awaited()
    finally:
        await state.close()


@pytest.mark.parametrize('hot', [False, True])
async def test_deleted_root_does_not_hide_a_live_descendant_through_cold_topology(hot):
    redis, archive = fakeredis.aioredis.FakeRedis(decode_responses=True), Archive()
    state = store(redis, archive)
    try:
        await state._ensure_ready()
        await redis.hset(state._session_key('deleted-root'), mapping={'deleted':'1'})
        await redis.sadd(state._key('resident'), 'deleted-root')
        archive.list_workspace_descendant_ids = AsyncMock(side_effect=lambda ids: ['cold-bridge'] if 'deleted-root' in ids else [])
        if hot:
            child = await state.create_run(command('hot-child'), CONTEXT)
            await redis.hset(state._key('parents'), child.handle.session_id, 'cold-bridge')
            archive.has_nonterminal_sessions = AsyncMock(return_value=False)
        else:
            archive.has_nonterminal_sessions = AsyncMock(side_effect=lambda ids: 'cold-bridge' in ids)
        assert await state.has_nonterminal_session_trees(['deleted-root'])
        if not hot:
            assert 'deleted-root' not in archive.has_nonterminal_sessions.await_args.args[0]
    finally:
        await state.close()
