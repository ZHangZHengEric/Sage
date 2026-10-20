"""Bounded, owner-checked list views read existing state without execution hydration."""
from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from sagents.v2.runtime.session.state import SessionStoreCoordinator


OWNER = RequestContext(actor=ActorRef(principal_id='owner', principal_type='user', tenant_id='tenant'))


@pytest.mark.parametrize('durable', [False, True])
async def test_views_filter_runs_events_and_preserve_owner_without_loading_history(tmp_path, durable):
    store = FilesystemSessionStore(tmp_path) if durable else SessionStoreCoordinator()
    try:
        run_ids = []
        for sid in ['first', 'second']:
            created = await store.create_run(StartRun(agent_id='agent', session_id=sid, input=(),
                resolved_spec_hash='sha256:spec', idempotency_key=sid), OWNER)
            run_ids.append(created.handle.run_id)
        if durable:
            await store.close()
            store = FilesystemSessionStore(tmp_path)
            store._ensure_session_loaded = AsyncMock(side_effect=AssertionError('execution aggregate installed'))
            store._read_session_aggregate = lambda *_: (_ for _ in ()).throw(AssertionError('entire history read'))
        access = AuthorizedSessionAccess(store)
        views = await access.read_session_views({'first':OWNER,'second':OWNER,'missing':OWNER}, run_ids=[run_ids[0]])
        assert list(views) == ['first', 'second']
        assert [v.run.run_id for v in views['first']] == run_ids[:1]
        assert views['first'][0].command.agent_id == 'agent'
        assert views['first'][0].events == ()
        assert views['second'] == ()
        history = await access.read_session_views({'first':OWNER,'second':OWNER}, include_events=True, run_ids=run_ids[:1])
        assert history['first'][0].events[0].type == 'run.accepted'
        assert history['second'] == ()
        assert await access.read_session_views({'first':OWNER}, suspended_only=True) == {'first':()}
        if durable:
            assert not store._sessions and not store._runs
    finally:
        if durable:
            await store.close()


async def test_views_owner_checks_tenant_principal_type_and_skip_inaccessible():
    store = SessionStoreCoordinator()
    await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
    access = AuthorizedSessionAccess(store)
    for actor in (OWNER.actor.model_copy(update={'tenant_id':'other'}), OWNER.actor.model_copy(update={'principal_type':'service'})):
        wrong = OWNER.model_copy(update={'actor':actor})
        with pytest.raises(SageV2Error):
            await access.read_session_views({'s':wrong})
        assert await access.read_session_views({'s':wrong},skip_inaccessible=True) == {}
    with pytest.raises(ValueError):
        await store.read_session_views([str(i) for i in range(201)])


async def test_hot_redis_views_preserve_events_without_hydrating_execution():
    import fakeredis.aioredis
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    archive = Archive()
    archive.read_session_views = AsyncMock(side_effect=AssertionError('hot state read stale archive'))
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = redis_store(redis,archive)
    try:
        result = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
        store._evict_session_locked('s')
        store._ensure_session_loaded = AsyncMock(side_effect=AssertionError('execution installed'))
        views = await AuthorizedSessionAccess(store).read_session_views({'s':OWNER},include_events=True)
        assert views['s'][0].run.run_id == result.handle.run_id
        assert views['s'][0].events[0].type == 'run.accepted'
        assert not store._sessions and not store._runs
    finally:
        await store.close()


async def test_mysql_cold_views_batch_all_sessions_and_only_selected_history():
    from contextlib import asynccontextmanager
    from sagents.v2.runtime.session.plugins.mysql.read_views import MysqlSessionReadQueries
    memory = SessionStoreCoordinator()
    run_ids = []
    for index in range(20):
        created = await memory.create_run(StartRun(agent_id='a',session_id=f's{index}',input=(),
            resolved_spec_hash='sha256:spec',idempotency_key=f's{index}'),OWNER)
        run_ids.append(created.handle.run_id)
    payloads = {sid: await memory.export_session_state(sid) for sid in memory._sessions}
    base_rows = [(sid,payload,payload['sessions'][0]['revision'],payload['sessions'][0]['last_sequence']) for sid,payload in payloads.items()]
    class Cursor:
        def __init__(self):
            self.queries = []
            self.responses = []
        async def __aenter__(self):
            return self
        async def __aexit__(self,*_):
            return None
        async def execute(self,statement,params=()):
            if not statement.startswith('SET TRANSACTION'):
                self.queries.append((statement,params))
        async def fetchall(self):
            return self.responses.pop(0)
    cursor = Cursor()
    class Connection:
        async def begin(self):
            pass
        def cursor(self):
            return cursor
    class Store(MysqlSessionReadQueries):
        @asynccontextmanager
        async def _reader_connection(self):
            yield Connection()
        def _table(self,name):
            return name
    store = Store()
    # MySQL's compact projection excludes events: its event table is canonical.
    for _,payload,*_ in base_rows:
        payload.pop('run_events',None)
    cursor.responses = [base_rows,[]]
    views = await store.read_session_views(list(payloads))
    assert len(views) == 20
    assert len(cursor.queries) == 2
    assert all(not view.runs[0].events for view in views.values())
    cursor.responses = [base_rows,[],[('s0',run_ids[0],event.model_dump(mode='json')) for event in memory._run_events[run_ids[0]]]]
    cursor.queries.clear()
    views = await store.read_session_views(list(payloads),include_events=True,run_ids=run_ids[:1])
    assert views['s0'].runs[0].events[0].type == 'run.accepted'
    assert all(not view.runs for sid,view in views.items() if sid != 's0')
    assert len(cursor.queries) == 3
    assert 'run_id IN (%s)' in cursor.queries[-1][0]
    assert cursor.queries[-1][1][-1] == run_ids[0]


@pytest.mark.parametrize('durable',[False,True])
async def test_legacy_owner_fallback_remains_secure_in_session_views(tmp_path,durable):
    store = FilesystemSessionStore(tmp_path) if durable else SessionStoreCoordinator()
    try:
        created = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
        store._sessions['s'].owner = None
        store._runs[created.handle.run_id].request_context = None
        if durable:
            store._write_snapshot(store._session_dir('s') / 'state.json',store._dump_state_locked())
            await store.close()
            store = FilesystemSessionStore(tmp_path)
        access = AuthorizedSessionAccess(store)
        views = await access.read_session_views({'s':OWNER})
        assert views['s'][0].run.run_id == created.handle.run_id
        wrong = OWNER.model_copy(update={'actor':OWNER.actor.model_copy(update={'tenant_id':'other'})})
        with pytest.raises(SageV2Error):
            await access.read_session_views({'s':wrong})
    finally:
        if durable:
            await store.close()


async def test_projected_replay_preserves_suspension_patches_and_rejects_revision_gaps():
    from sagents.v2.runtime.session.plugins.mysql.read_views import replay_view_rows
    from sagents.v2.runtime.session.read_views import views_from_payload
    store = SessionStoreCoordinator()
    created = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
    state = store._dump_state_locked()
    head = dict(state['sessions'][0])
    revision = head['revision']
    head['revision'] += 1
    now = head['created_at']
    suspension = {'suspension_id':'susp','run_id':created.handle.run_id,'reason':'approval_required',
        'blocking_scope':'run','checkpoint_id':'cp','checkpoint_sequence':0,'resume_policy':'manual',
        'interaction_id':'interaction','requested_at':now}
    interaction = {'interaction_id':'interaction','run_id':created.handle.run_id,'interaction_type':'approval',
        'allowed_decisions':['approve','reject'],'payload':{'tool':'edit'},'requested_at':now}
    delta = {'upserts':{'sessions':[head],'suspensions':[suspension],'interactions':[interaction]},
        'patches':{'runs':[{'run_id':created.handle.run_id,'state':'suspended','suspension_id':'susp','revision':2}]}}
    replayed = replay_view_rows([('s',state,head['revision'],head['last_sequence'])],[('s',revision+1,delta)])
    view = views_from_payload(replayed['s'],suspended_only=True)['s'].runs[0]
    assert view.run.state == RunState.SUSPENDED
    assert view.suspension.interaction_id == 'interaction'
    assert view.interaction.payload == {'tool':'edit'}
    with pytest.raises(ValueError,match='revision gap'):
        replay_view_rows([('s',state,head['revision'],head['last_sequence'])],[('s',revision+2,delta)])


async def test_redis_views_batch_cold_archive_and_respect_hot_deletion():
    import fakeredis.aioredis
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    from sagents.v2.runtime.session.read_views import SessionReadView
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    archive = Archive()
    archive.read_session_views = AsyncMock(return_value={sid:SessionReadView(OWNER.actor,()) for sid in ['cold-a','cold-b']})
    store = redis_store(redis,archive)
    try:
        await store._ensure_ready()
        await redis.hset(store._session_key('deleted'),mapping={'deleted':'1'})
        views = await AuthorizedSessionAccess(store).read_session_views({sid:OWNER for sid in ['deleted','cold-a','cold-b']})
        assert views == {'cold-a':(),'cold-b':()}
        archive.read_session_views.assert_awaited_once_with(['cold-a','cold-b'])
        await redis.sadd(store._key('resident'),'lost')
        with pytest.raises(SageV2Error,match='Unarchived Redis Session data is missing'):
            await store.read_session_views(['lost'])
        assert archive.read_session_views.await_count == 1
    finally:
        await redis.srem(store._key('resident'),'lost')
        await store.close()


async def test_redis_views_recover_uncertain_committed_state_without_mutating_execution_cache():
    import fakeredis.aioredis
    from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = redis_store(redis,Archive())
    try:
        created = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
        before = await store.get_run(created.handle.run_id)
        await store.commit_run(run_id=before.run_id,expected_revision=before.revision,
            expected_states={before.state},new_state=RunState.CANCELLED,drafts=(),context=OWNER,idempotency_key='cancel')
        # Reproduce the rolled-back process cache after an uncertain EXEC acknowledgement.
        store._runs[before.run_id].state = before.state
        store._recovery_required.add('s')
        views = await store.read_session_views(['s'])
        assert views['s'].runs[0].run.state == RunState.CANCELLED
        assert store._runs[before.run_id].state == before.state
        store._recovery_required.clear()
    finally:
        await store.close()


@pytest.mark.parametrize('authorized',[False,True])
async def test_mysql_legacy_metadata_derives_many_owners_in_one_batch_on_same_connection(authorized):
    from contextlib import asynccontextmanager
    from sagents.v2.runtime.session.plugins.mysql.run_metadata import MysqlRunMetadataQueries
    from sagents.v2.runtime.session.read_views import SessionReadView
    ids = tuple(f'legacy-{i}' for i in range(20))
    class Cursor:
        responses = [[(sid,None) for sid in ids],[]]
        async def __aenter__(self):
            return self
        async def __aexit__(self,*_):
            pass
        async def execute(self,*_):
            pass
        async def fetchall(self):
            return self.responses.pop(0)
    cursor = Cursor()
    class Connection:
        async def begin(self):
            pass
        def cursor(self):
            return cursor
    connection = Connection()
    class Store(MysqlRunMetadataQueries):
        _fetch_session = AsyncMock(side_effect=AssertionError('legacy aggregate loaded per Session'))
        authorize_session_actor = AsyncMock(side_effect=AssertionError('legacy Session authorized with I/O'))
        _read_session_views_on_connection = AsyncMock(return_value={sid:SessionReadView(OWNER.actor,()) for sid in ids})
        _authorize_session_owner = staticmethod(SessionStoreCoordinator._authorize_session_owner)
        @asynccontextmanager
        async def _reader_connection(self):
            yield connection
        def _table(self,name):
            return name
    store = Store()
    if authorized:
        assert await store.authorized_run_metadata_page(ids,OWNER) == ()
    else:
        rows,owners = await store._run_metadata_batch(ids)
        assert rows == ()
        assert all(owners[sid] == OWNER.actor for sid in ids)
    store._read_session_views_on_connection.assert_awaited_once_with(connection,ids,run_ids=())


@pytest.mark.parametrize('reference',['suspension','interaction'])
@pytest.mark.parametrize('projected',[False,True])
async def test_views_preserve_errors_for_dangling_approval_references(reference,projected):
    from sagents.v2.runtime.session.read_views import views_from_payload
    from sagents.v2.contracts.checkpoint import Suspension
    from sagents.v2.contracts.common import utc_now
    store = SessionStoreCoordinator()
    created = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
    row = store._runs[created.handle.run_id]
    row.state = RunState.SUSPENDED
    row.suspension_id = 'susp'
    if reference == 'interaction':
        store._suspensions['susp'] = Suspension(suspension_id='susp',run_id=row.run_id,reason='approval_required',
            blocking_scope='run',checkpoint_id='checkpoint',checkpoint_sequence=0,interaction_id='question',
            resume_policy='manual',requested_at=utc_now())
    with pytest.raises(SageV2Error) as caught:
        if projected:
            views_from_payload(store._dump_state_locked(),suspended_only=True)
        else:
            await store.read_session_views(['s'],suspended_only=True)
    assert caught.value.info.code == reference + '.not_found'


@pytest.mark.parametrize('projected',[False,True])
async def test_approval_views_fail_on_missing_admission_header_without_loading_it(projected):
    from sagents.v2.runtime.session.read_views import views_from_payload
    store = SessionStoreCoordinator()
    created = await store.create_run(StartRun(agent_id='a',session_id='s',input=(),resolved_spec_hash='sha256:spec',idempotency_key='s'),OWNER)
    store._runs[created.handle.run_id].state = RunState.SUSPENDED
    store._runs[created.handle.run_id].start_command = None
    store.get_start_command = AsyncMock(side_effect=AssertionError('missing header loaded per Run'))
    with pytest.raises(SageV2Error) as caught:
        if projected:
            views_from_payload(store._dump_state_locked(),suspended_only=True)
        else:
            await store.read_session_views(['s'],suspended_only=True)
    assert caught.value.info.code == 'run.header_not_found'
    # General event views do not need an admission header.
    if projected:
        view = views_from_payload(store._dump_state_locked())['s'].runs[0]
    else:
        view = (await store.read_session_views(['s']))['s'].runs[0]
    assert view.command is None
