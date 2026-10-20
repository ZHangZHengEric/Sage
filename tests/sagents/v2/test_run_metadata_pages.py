"""Authorized small Run pages never install historical execution aggregates."""
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState, _SCHEMA_TABLES
from sagents.v2.contracts.principals import RequestContext, ActorRef


@pytest.mark.parametrize('backend', ['memory', 'filesystem', 'mysql'])
async def test_metadata_pages_preserve_order_filter_owner_and_no_history_install(tmp_path, backend):
    dsn = os.environ.get('SAGE_V2_TEST_MYSQL_DSN')
    if backend in {'mysql'} and not dsn:
        pytest.skip('set SQL DSN for live metadata SQL')
    store = (_MysqlSessionState(dsn, table_prefix='metadata_'+uuid4().hex[:10]) if backend == 'mysql' else
             FilesystemSessionStore(tmp_path) if backend == 'filesystem' else SessionStoreCoordinator())
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    other = RequestContext(actor=ActorRef(principal_id='other',principal_type='user',tenant_id='other'))
    expected = []
    try:
        for sid, actor, agent in [('first',owner,'a'),('second',owner,'a'),('private',other,'a'),('foreign-agent',owner,'b')]:
            for index in range(3):
                result = await store.create_run(StartRun(agent_id=agent,session_id=sid,input=(),
                    session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                    resolved_spec_hash='sha256:spec',idempotency_key=sid+str(index)), actor)
                if sid in {'first','second'}:
                    expected.append(result.handle.run_id)
        before = await store.get_run(expected[0])
        await store.commit_run(run_id=before.run_id,expected_revision=before.revision,
            expected_states={before.state},new_state=RunState.CANCELLED,drafts=(),context=owner,idempotency_key='cancel-first')
        if backend == 'filesystem':
            await store.close()
            store = FilesystemSessionStore(tmp_path)
            store._read_session_aggregate = lambda *_: (_ for _ in ()).throw(AssertionError('typed entire history decoded'))
            store._ensure_session_loaded = AsyncMock(side_effect=AssertionError('aggregate installed'))
        if backend in {'mysql'}:
            store._fetch_session = AsyncMock(side_effect=AssertionError('aggregate installed'))
        ids = ['first','second','private','foreign-agent']
        page = await store.authorized_run_metadata_page(ids,owner,agent_id='a',limit=4,states=(RunState.QUEUED,))
        assert [row.run_id for row in page] == expected[1:5]
        last = page[-1]
        rest = await store.authorized_run_metadata_page(ids,owner,agent_id='a',limit=4,
            after=(last.session_id,last.created_at.isoformat(),last.run_id))
        assert [row.run_id for row in rest] == expected[5:]
        cancelled = await store.authorized_run_metadata_page(ids,owner,agent_id='a',states=(RunState.CANCELLED,))
        assert [row.run_id for row in cancelled] == expected[:1]
        assert not await store.authorized_run_metadata_page(ids,owner,agent_id='a',states=(RunState.COMPLETED,))
    finally:
        if backend == 'mysql' and store._pool is not None:
            async with store._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for table in reversed(_SCHEMA_TABLES):
                        await cursor.execute(f'DROP TABLE IF EXISTS {store._table(table)}')
                await connection.commit()
        if backend != 'memory':
            await store.close()


async def test_redis_uncached_large_history_metadata_is_batched_without_aggregate_replay():
    import fakeredis.aioredis
    from sagents.v2.contracts.commands import InputItem
    from sagents.v2.contracts.items import TextBlock
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive._run_metadata_batch = AsyncMock(side_effect=AssertionError('hot state queried stale archive'))
    store = redis_store(redis, archive)
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    try:
        result = await store.create_run(StartRun(agent_id='a',session_id='hot',
            input=(InputItem(role='user',content=(TextBlock(text='x'*(1024*1024)),)),),
            resolved_spec_hash='sha256:spec',idempotency_key='hot'),owner)
        store._evict_session_locked('hot')
        for name in ('_fetch_session','_decode_hot','_replay_mutations','_ensure_session_loaded'):
            setattr(store,name,AsyncMock(side_effect=AssertionError('full execution history used')))
        page = await store.authorized_run_metadata_page(['hot'],owner,agent_id='a')
        assert [row.run_id for row in page] == [result.handle.run_id]
        assert not store._sessions and not store._runs
    finally:
        await store.close()


async def test_redis_missing_resident_metadata_never_falls_back_to_stale_archive():
    import fakeredis.aioredis
    from sagents.v2.contracts.errors import SageV2Error
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive._run_metadata_batch = AsyncMock(return_value=((),{}))
    store = redis_store(redis, archive)
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    try:
        await store.create_run(StartRun(agent_id='a',session_id='lost',input=(),resolved_spec_hash='sha256:spec',idempotency_key='lost'),owner)
        store._evict_session_locked('lost')
        await redis.delete(store._session_key('lost'))
        with pytest.raises(SageV2Error,match='Unarchived Redis Session data is missing'):
            await store.authorized_run_metadata_page(['lost'],owner)
        archive._run_metadata_batch.assert_not_awaited()
    finally:
        await store.close()


async def test_redis_metadata_resolves_a_committed_write_after_its_confirmation_is_lost():
    import fakeredis.aioredis
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = redis_store(redis, Archive())
    original_fetch = store._fetch_session
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    try:
        result = await store.create_run(StartRun(agent_id='a',session_id='uncertain',input=(),
            resolved_spec_hash='sha256:spec',idempotency_key='uncertain'),owner)
        before = await store.get_run(result.handle.run_id)
        original_transaction, original_get = store._retry_transaction, redis.hget

        async def lose_response(operation):
            await original_transaction(operation)
            raise OSError('EXEC confirmation lost')

        async def lose_confirmation(key, field):
            if field == 'commit_id':
                raise OSError('commit confirmation unavailable')
            return await original_get(key, field)

        store._retry_transaction = lose_response
        redis.hget = lose_confirmation
        with pytest.raises(OSError, match='confirmation unavailable'):
            await store.commit_run(run_id=before.run_id,expected_revision=before.revision,
                expected_states={before.state},new_state=RunState.CANCELLED,drafts=(),
                context=owner,idempotency_key='cancel-uncertain')
        store._retry_transaction, redis.hget = original_transaction, original_get
        assert 'uncertain' in store._recovery_required
        store._fetch_session = AsyncMock(side_effect=AssertionError('full aggregate recovery used'))
        rows = await store.authorized_run_metadata_page(['uncertain'],owner)
        assert [(row.run_id,row.state) for row in rows] == [(before.run_id,RunState.CANCELLED)]
        # A metadata read does not resolve the typed execution cache itself.
        store._fetch_session = original_fetch
        assert (await store.get_run(before.run_id)).state == RunState.CANCELLED
    finally:
        store._fetch_session = original_fetch
        await store.close()


@pytest.mark.parametrize('durable', [False, True])
async def test_legacy_metadata_authorization_uses_accepted_actor_when_owner_and_context_missing(tmp_path,durable):
    store = FilesystemSessionStore(tmp_path) if durable else SessionStoreCoordinator()
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    stranger = RequestContext(actor=ActorRef(principal_id='stranger',principal_type='user',tenant_id='owner'))
    try:
        result = await store.create_run(StartRun(agent_id='a',session_id='legacy',input=(),resolved_spec_hash='sha256:spec',idempotency_key='legacy'),owner)
        store._sessions['legacy'].owner = None
        store._runs[result.handle.run_id].request_context = None
        if durable:
            state = store._dump_state_locked()
            store._write_snapshot(store._session_dir('legacy') / 'state.json',state)
            await store.close()
            store = FilesystemSessionStore(tmp_path)
            store._ensure_session_loaded = AsyncMock(side_effect=AssertionError('legacy metadata installed aggregate'))
            store._read_session_aggregate = lambda *_: (_ for _ in ()).throw(AssertionError('typed history reader'))
        rows = await store.authorized_run_metadata_page(['legacy'],owner)
        assert [row.run_id for row in rows] == [result.handle.run_id]
        assert not await store.authorized_run_metadata_page(['legacy'],stranger)
    finally:
        if durable:
            await store.close()


async def test_cold_mysql_metadata_retains_legacy_owner_for_redis_archive_reads():
    dsn = os.environ.get('SAGE_V2_TEST_MYSQL_DSN')
    if not dsn:
        pytest.skip('set MySQL DSN for legacy archive metadata')
    from sagents.v2.runtime.session.run_metadata import RunMetadataQueries
    store = _MysqlSessionState(dsn,table_prefix='legacy_'+uuid4().hex[:10])
    owner = RequestContext(actor=ActorRef(principal_id='owner',principal_type='user',tenant_id='owner'))
    stranger = owner.model_copy(update={'actor':owner.actor.model_copy(update={'principal_id':'stranger'})})
    try:
        result = await store.create_run(StartRun(agent_id='a',session_id='legacy',input=(),
            resolved_spec_hash='sha256:spec',idempotency_key='legacy'),owner)
        async with store._writer_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(f"UPDATE {store._table('sessions')} SET compact_state=JSON_SET(compact_state,"
                    "'$.sessions[0].owner',CAST('null' AS JSON),'$.runs[0].request_context',CAST('null' AS JSON)) "
                    "WHERE session_id=%s",('legacy',))
            await connection.commit()
        store._evict_session_locked('legacy')
        # Redis's cold archive path consumes this batch before generic owner
        # authorization; it cannot use MySQL's separate authorized-page fallback.
        rows = await RunMetadataQueries.authorized_run_metadata_page(store,['legacy'],owner)
        assert [row.run_id for row in rows] == [result.handle.run_id]
        assert not await RunMetadataQueries.authorized_run_metadata_page(store,['legacy'],stranger)
        assert not store._sessions and not store._runs
    finally:
        if store._pool is not None:
            async with store._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for table in reversed(_SCHEMA_TABLES):
                        await cursor.execute(f'DROP TABLE IF EXISTS {store._table(table)}')
                await connection.commit()
        await store.close()


def test_metadata_replay_applies_state_patches_run_deletes_and_canonical_owner_precedence():
    from sagents.v2.runtime.session.metadata_replay import project_metadata_state,apply_metadata_delta
    from sagents.v2.runtime.session.run_metadata import metadata_from_payload
    def actor(name):
        return {'principal_id':name,'principal_type':'user','tenant_id':'tenant'}
    def row(rid,at,who):
        return {'session_id':'s','run_id':rid,'created_at':at,'state':'queued',
                'start_command':{'agent_id':'a'},'request_context':{'actor':actor(who)}}
    raw = {'sessions':[{'session_id':'s','owner':None,'created_at':'2026-01-01T00:00:00+00:00','revision':1}],
           'runs':[row('later','2026-01-02T00:00:00+00:00','wrong'),row('first','2026-01-01T00:00:00+00:00','owner')],
           'run_events':{'first':[{'type':'run.accepted','session_id':'s','session_sequence':1,'actor':actor('fallback')}]}}
    state = project_metadata_state(raw)
    state = apply_metadata_delta(state,{'patches':{'runs':[{'run_id':'first','state':'cancelled'}]},'deletes':{'runs':[['later']]}})
    rows, owners = metadata_from_payload(state)
    assert [(row.run_id,row.state) for row in rows] == [('first',RunState.CANCELLED)]
    assert owners['s']['principal_id'] == 'owner'
