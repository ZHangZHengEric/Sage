"""Managed context preserves its roster while reading only direct-child heads.

Existing managed context tests establish delegation/restart semantics. This
regression additionally forbids aggregate APIs and checks admitted Agent names,
long whitespace prefixes, all direct children and the latest command/state.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from sagents.v2.agent.multi_agent import AgentDescriptor, AgentMode, AgentRegistry
from sagents.v2.agent.multi_agent.context import AgentRosterContextProvider
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT


async def populate(store):
    parent_request = command('parent')
    parent = (await store.create_run(parent_request, CONTEXT)).handle
    async def child(key, *, parent_id=parent.run_id, mode='delegation', sid=None, task='first'):
        value = command(key).model_copy(update={'agent_id':'qualified.worker', 'session_id':sid,
            'parent_run_id':parent_id, 'invocation_mode':mode,
            'config':command(key).config.model_copy(update={'metadata':{
                'task_name':task, 'server_v2.execution':{'agent_id':'workspace-parent'}}})})
        return (await store.create_run(value, CONTEXT)).handle
    async def cancel(handle, key):
        current = await store.get_run(handle.run_id)
        await store.commit_run(run_id=handle.run_id, expected_revision=current.revision,
            expected_states={current.state}, new_state=RunState.CANCELLED, drafts=(), context=CONTEXT,
            idempotency_key=key)
    first = await child('first')
    nested = await child('nested', parent_id=first.run_id)
    second = await child('second', task='second')
    flow = await child('flow', mode='flow')
    await cancel(flow, 'stop-flow')
    await child('flow-follow', sid=flow.session_id, mode='delegation')
    await cancel(first, 'stop-first')
    latest = await child('follow', sid=first.session_id, task=' ' * 600 + 'latest\n  title with several words after whitespace')
    await cancel(latest, 'stop-follow')
    return parent_request, parent, first, second, nested, flow


@pytest.mark.parametrize('backend', ['memory', 'filesystem'])
async def test_managed_context_preserves_complete_output_without_aggregate_reads(tmp_path, backend):
    store = SessionStoreCoordinator() if backend == 'memory' else FilesystemSessionStore(tmp_path / 'state')
    request, parent, first, second, nested, flow = await populate(store)
    if backend == 'filesystem':
        await store.close()
        store = FilesystemSessionStore(tmp_path / 'state')
        store._ensure_session_loaded = AsyncMock(side_effect=AssertionError('context installed execution aggregate'))
        store._read_session_aggregate = lambda *_: (_ for _ in ()).throw(AssertionError('context decoded complete aggregate'))
    for method in ('get_run', 'list_descendant_sessions', 'list_session_runs', 'get_start_command'):
        setattr(store, method, AsyncMock(side_effect=AssertionError('context used aggregate API ' + method)))
    registry = AgentRegistry((AgentDescriptor(agent_id='qualified.worker', name='Worker', description='work', instructions='work'),),
                             aliases={'worker':'qualified.worker'})
    provider = AgentRosterContextProvider(registry, AgentMode.FIBRE, session_store=store)
    try:
        for _ in range(2):
            segments = await provider.segments(request, run_id=parent.run_id)
            managed = next(segment for segment in segments if segment.segment_id == 'managed_sessions')
            assert json.loads(managed.content.splitlines()[-2]) == [
                {'agent_id':'worker', 'session_id':first.session_id, 'state':'cancelled', 'task':'latest title with se'},
                {'agent_id':'worker', 'session_id':second.session_id, 'state':'queued', 'task':'second'},
            ]
            assert nested.session_id not in managed.content and flow.session_id not in managed.content
        if backend == 'filesystem':
            assert not store._sessions
    finally:
        closer = getattr(store, 'close', None)
        if closer:
            await closer()


def test_child_heads_keep_session_order_and_run_identity_tiebreakers():
    from sagents.v2.runtime.session.child_heads import child_heads
    from sagents.v2.runtime.session.run_metadata import RunMetadata
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    def row(sid, rid, session_day, run_day, state):
        return RunMetadata(sid, rid, now + timedelta(days=run_day), state, 'worker',
                           'delegation', rid, 'worker', now + timedelta(days=session_day), 'parent')
    early_last = row('early', 'run-z', 0, 9, RunState.FAILED)
    early_first = row('early', 'run-a', 0, 9, RunState.CANCELLED)
    later = row('later', 'run-b', 1, 1, RunState.QUEUED)
    heads = child_heads([later, early_last, early_first])
    assert [head.first.session_id for head in heads] == ['early', 'later']
    assert heads[0].first == early_first and heads[0].latest == early_last


async def test_managed_context_keeps_every_direct_child_across_metadata_batches():
    state = SessionStoreCoordinator()
    request = command('root')
    parent = (await state.create_run(request, CONTEXT)).handle
    expected = []
    for index in range(130):
        child = await state.create_run(command(str(index)).model_copy(update={
            'agent_id':'worker', 'parent_run_id':parent.run_id, 'invocation_mode':'delegation'}), CONTEXT)
        expected.append(child.handle.session_id)
    provider = AgentRosterContextProvider(AgentRegistry(), AgentMode.TEAM, session_store=state)
    managed = next(segment for segment in await provider.segments(request, run_id=parent.run_id)
                   if segment.segment_id == 'managed_sessions')
    assert [row['session_id'] for row in json.loads(managed.content.splitlines()[-2])] == expected


async def test_real_mysql_managed_heads_return_only_direct_first_latest_metadata(monkeypatch):
    from aiomysql.cursors import Cursor
    from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
    from sagents.v2.runtime.session.plugins.mysql.state import _SCHEMA_TABLES
    dsn = os.environ.get('SAGE_V2_TEST_MYSQL_DSN')
    if not dsn:
        pytest.skip('set SAGE_V2_TEST_MYSQL_DSN for real metadata projection')
    prefix = 'managed_' + uuid4().hex[:10]
    value = MysqlSessionStore(dsn, table_prefix=prefix, max_cached_sessions=2)
    try:
        request, parent, first, second, nested, flow = await populate(value)
        await value.close()
        value = MysqlSessionStore(dsn, table_prefix=prefix, max_cached_sessions=2)
        await value._coordinator._ensure_ready()
        value._coordinator._fetch_session = AsyncMock(side_effect=AssertionError('heads fetched aggregate'))
        value._coordinator._run_metadata_rows = AsyncMock(side_effect=AssertionError('heads transferred all Run rows'))
        sizes = []
        fetchall = Cursor.fetchall
        async def measured(cursor):
            result = await fetchall(cursor)
            query = cursor._executed
            if 'first_position' in (query.decode() if isinstance(query, bytes) else query):
                sizes.append(len(result))
            return result
        monkeypatch.setattr(Cursor, 'fetchall', measured)
        provider = AgentRosterContextProvider(AgentRegistry(), AgentMode.TEAM, session_store=value)
        for _ in range(2):
            managed = next(segment for segment in await provider.segments(request, run_id=parent.run_id)
                           if segment.segment_id == 'managed_sessions')
            rows = json.loads(managed.content.splitlines()[-2])
            assert rows == [
                {'agent_id':'qualified.worker', 'session_id':first.session_id, 'state':'cancelled', 'task':'latest title with se'},
                {'agent_id':'qualified.worker', 'session_id':second.session_id, 'state':'queued', 'task':'second'},
            ]
        assert sizes == [5, 5]  # two first/latest pairs and one single-Run child
        assert not value._coordinator._sessions
    finally:
        if value._coordinator._pool is not None:
            async with value._coordinator._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for table in reversed(_SCHEMA_TABLES):
                        await cursor.execute(f'DROP TABLE IF EXISTS {value._coordinator._table(table)}')
                await connection.commit()
        await value.close()


@pytest.mark.parametrize('live', [False, True])
async def test_unarchived_redis_managed_heads_do_not_install_cold_aggregates(live):
    import fakeredis.aioredis
    from redis.asyncio import Redis
    from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    url = os.environ.get('SAGE_V2_TEST_REDIS_URL')
    if live and not url:
        pytest.skip('set SAGE_V2_TEST_REDIS_URL for real Redis metadata projection')
    archive = Archive()
    archive.list_direct_child_session_ids = AsyncMock(return_value=[])
    prefix = 'managed-heads:' + uuid4().hex
    if live:
        value = RedisMysqlSessionStore('mysql://unused/test', redis_url=url, key_prefix=prefix)
        value._archive = archive
        async def idle_archive():
            import asyncio
            await asyncio.Event().wait()
        value._archive_loop = idle_archive
    else:
        value = redis_store(fakeredis.aioredis.FakeRedis(decode_responses=True), archive)
    try:
        request, parent, first, second, nested, flow = await populate(value)
        from sagents.v2.runtime.session.contracts import EventDraft
        from sagents.v2.contracts.events import RunEventData
        current = await value.get_run(second.run_id)
        await value.commit_run(run_id=second.run_id, expected_revision=current.revision,
            expected_states={current.state}, new_state=RunState.RUNNING,
            drafts=(EventDraft(type='run.started', data=RunEventData(state='running', reason='x' * 1_048_576)),),
            context=CONTEXT, idempotency_key='large-history')
        for sid in tuple(value._sessions):
            value._evict_session_locked(sid)
        value._ensure_session_loaded = AsyncMock(side_effect=AssertionError('heads installed Redis aggregate'))
        original = {name:getattr(value, name) for name in ('_fetch_session', '_decode_hot', '_replay_mutations')}
        for name in original:
            def forbidden(*_, method=name, **kwargs):
                raise AssertionError('heads reconstructed aggregate through ' + method)
            setattr(value, name, forbidden)
        provider = AgentRosterContextProvider(AgentRegistry(), AgentMode.FIBRE, session_store=value)
        for _ in range(2):
            managed = next(segment for segment in await provider.segments(request, run_id=parent.run_id)
                           if segment.segment_id == 'managed_sessions')
            assert json.loads(managed.content.splitlines()[-2]) == [
                {'agent_id':'qualified.worker', 'session_id':first.session_id, 'state':'cancelled', 'task':'latest title with se'},
                {'agent_id':'qualified.worker', 'session_id':second.session_id, 'state':'running', 'task':'second'},
            ]
        assert not value._sessions
    finally:
        if 'original' in locals():
            for name, method in original.items():
                setattr(value, name, method)
        await value.close()
        if live:
            redis = Redis.from_url(url, decode_responses=True)
            try:
                keys = [key async for key in redis.scan_iter(match=prefix + ':*')]
                if keys:
                    await redis.delete(*keys)
            finally:
                await redis.aclose()


async def test_real_postgres_managed_heads_preserve_context_without_aggregate_load():
    from sagents.v2.runtime.session.plugins.postgres import PostgresSessionStore
    dsn = os.environ.get('SAGE_V2_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('set SAGE_V2_TEST_POSTGRES_DSN for real PostgreSQL metadata projection')
    schema = 'managed_' + uuid4().hex[:10]
    value = PostgresSessionStore(dsn, schema=schema)
    try:
        request, parent, first, second, nested, flow = await populate(value)
        await value.close()
        value = PostgresSessionStore(dsn, schema=schema)
        await value._coordinator._ensure_ready()
        value._coordinator._fetch_session = AsyncMock(side_effect=AssertionError('heads fetched PostgreSQL aggregate'))
        value._coordinator._ensure_session_loaded = AsyncMock(side_effect=AssertionError('heads installed PostgreSQL aggregate'))
        provider = AgentRosterContextProvider(AgentRegistry(), AgentMode.TEAM, session_store=value)
        for _ in range(2):
            managed = next(segment for segment in await provider.segments(request, run_id=parent.run_id)
                           if segment.segment_id == 'managed_sessions')
            assert json.loads(managed.content.splitlines()[-2]) == [
                {'agent_id':'qualified.worker', 'session_id':first.session_id, 'state':'cancelled', 'task':'latest title with se'},
                {'agent_id':'qualified.worker', 'session_id':second.session_id, 'state':'queued', 'task':'second'},
            ]
        assert not value._coordinator._sessions
    finally:
        if value._coordinator._pool is not None:
            async with value._coordinator._pool.acquire() as connection:
                await connection.execute(f'DROP SCHEMA {schema} CASCADE')
        await value.close()
