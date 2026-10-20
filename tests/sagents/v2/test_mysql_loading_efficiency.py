"""Cold Session loading must not rebuild unrelated live state."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager
import json
import os

import pytest

from sagents.v2.runtime.session.mysql_state import _MysqlSessionState
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.events import RunEventData
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
from uuid import uuid4


@pytest.fixture
def mysql_dsn():
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN", "").strip()
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN to run live MySQL tests")
    return dsn


async def snapshot(key):
    source = SessionStoreCoordinator()
    created = await source.create_run(command(key), CONTEXT)
    return created.handle, await source.export_session_state(created.handle.session_id)


async def test_install_preserves_unrelated_live_row_identity_and_never_exports_global_state():
    first, payload = await snapshot("first")
    second, other = await snapshot("second")
    state = _MysqlSessionState("mysql://unused/test")
    state._install_session_locked(payload)
    live_row = state._runs[first.run_id]
    live_events = state._run_events[first.run_id]
    state._dump_state_locked = lambda: pytest.fail("cold load serialized unrelated Sessions")
    state._install_session_locked(other)
    assert state._runs[first.run_id] is live_row
    assert state._run_events[first.run_id] is live_events
    assert (await state.get_run(second.run_id)).session_id == second.session_id


async def test_different_cold_sessions_fetch_concurrently_and_same_session_fetches_once():
    first, a = await snapshot("first")
    second, b = await snapshot("second")
    state = _MysqlSessionState("mysql://unused/test")
    state._ensure_ready = AsyncMock()
    arrivals, release = set(), asyncio.Event()
    counts = {}

    async def fetch(sid):
        counts[sid] = counts.get(sid, 0) + 1
        arrivals.add(sid)
        if len(arrivals) == 2:
            release.set()
        await release.wait()
        return {first.session_id: a, second.session_id: b}[sid]

    state._fetch_session = fetch
    await asyncio.wait_for(asyncio.gather(
        state._ensure_session_loaded(first.session_id),
        state._ensure_session_loaded(second.session_id),
        state._ensure_session_loaded(first.session_id),
    ), 1)
    assert counts == {first.session_id: 1, second.session_id: 1}
    assert len(state._runs) == 2


async def test_authorized_history_page_reads_only_the_page_without_installing_session():
    handle, payload = await snapshot("history")
    state = _MysqlSessionState("mysql://unused/test")
    cursor, connection = AsyncMock(), AsyncMock()
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    cursor.fetchone.return_value = (
        json.dumps(CONTEXT.actor.model_dump(mode="json")), 3,
    )
    cursor.fetchall.return_value = [(json.dumps(payload["run_events"][handle.run_id][-1]),)]

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    state._pool = Pool()
    state._fetch_session = AsyncMock(side_effect=AssertionError("history installed entire aggregate"))
    page = await AuthorizedSessionAccess(state).read_session_event_page(
        handle.session_id, CONTEXT, after_sequence=2, limit=1,
    )
    assert page.total == 3 and page.after_sequence == 2
    assert len(page.events) == 1 and page.events[0].session_sequence == 3
    assert not state._sessions
    statements = cursor.execute.await_args_list
    assert any("LIMIT %s" in call.args[0] and call.args[1] == (handle.session_id, 2, 3, 1)
               for call in statements)


async def test_idle_session_cache_evicts_only_unpinned_stopped_sessions_and_reloads():
    a, payload = await snapshot("first")
    b, other = await snapshot("second")
    state = _MysqlSessionState("mysql://unused/test", max_cached_sessions=1)
    state._ensure_ready = AsyncMock()
    state._fetch_session = AsyncMock(side_effect=lambda sid: {a.session_id: payload, b.session_id: other}[sid])
    # Terminal fixtures retain their canonical log while becoming cache-eligible.
    for value in (payload, other):
        value["runs"][0]["state"] = "completed"
    async with state._session_cache.operation():
        await state.get_session(a.session_id)
        await state.get_session(b.session_id)
        assert len(state._sessions) == 2, "both Sessions are pinned by this operation"
    assert len(state._sessions) == 1
    remaining = next(iter(state._sessions))
    evicted = a.session_id if remaining == b.session_id else b.session_id
    restored = await state.get_session(evicted)
    assert restored.last_sequence == 3
    assert len(state._sessions) == 1


async def test_real_mysql_history_pages_and_latest_journal_command(mysql_dsn):
    prefix = "review_" + uuid4().hex[:12]
    store = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
    try:
        created = await store.create_run(command("first"), CONTEXT)
        running = await store.commit_run(run_id=created.handle.run_id,
            expected_revision=created.handle.run_revision, expected_states={RunState.QUEUED},
            new_state=RunState.RUNNING, drafts=(EventDraft(type="run.started", data=RunEventData(state="running")),),
            context=CONTEXT, idempotency_key="running")
        completed = await store.commit_run(run_id=created.handle.run_id,
            expected_revision=running.run.revision, expected_states={RunState.RUNNING},
            new_state=RunState.COMPLETED, drafts=(EventDraft(type="run.completed", data=RunEventData(state="completed")),),
            context=CONTEXT, idempotency_key="completed")
        second_command = command("second").model_copy(update={"session_id": created.handle.session_id})
        await store.create_run(second_command, CONTEXT)
        await store.close()
        store = MysqlSessionStore(mysql_dsn, table_prefix=prefix)
        access = AuthorizedSessionAccess(store)
        page = await access.read_session_event_page(created.handle.session_id, CONTEXT, limit=2)
        assert len(page.events) == 2
        assert page.events[-1].session_sequence == page.total
        assert page.total > completed.session.last_sequence
        assert not store._coordinator._sessions
        latest = await access.latest_session_start_command(created.handle.session_id, CONTEXT)
        assert latest == second_command
        assert not store._coordinator._sessions
        stranger = CONTEXT.model_copy(update={"actor": CONTEXT.actor.model_copy(update={"principal_id": "stranger"})})
        with pytest.raises(SageV2Error, match="actor does not own"):
            await access.read_session_event_page(created.handle.session_id, stranger, limit=2)
    finally:
        await store.close()


async def test_active_session_is_not_evicted_to_meet_idle_cache_capacity():
    a, payload = await snapshot("active")
    b, other = await snapshot("stopped")
    other["runs"][0]["state"] = "completed"
    state = _MysqlSessionState("mysql://unused/test", max_cached_sessions=1)
    state._ensure_ready = AsyncMock()
    state._fetch_session = AsyncMock(side_effect=lambda sid: {a.session_id: payload, b.session_id: other}[sid])
    await state.get_session(a.session_id)
    await state.get_session(b.session_id)
    assert a.session_id in state._sessions
    assert state._runs[a.run_id].state == RunState.QUEUED
    assert len(state._sessions) == 1


@pytest.mark.parametrize('operation', ['get', 'put', 'delete'])
async def test_derived_query_keeps_session_pinned_until_database_work_finishes(operation):
    a, payload = await snapshot('derived')
    b, other = await snapshot('other')
    for value in (payload, other):
        value['runs'][0]['state'] = 'completed'
    state = _MysqlSessionState('mysql://unused/test', max_cached_sessions=1)
    state._ensure_ready = AsyncMock()
    state._fetch_session = AsyncMock(side_effect=lambda sid: {a.session_id: payload, b.session_id: other}[sid])
    cursor, connection = AsyncMock(), AsyncMock()
    cursor.fetchone.return_value = None
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection
    state._pool = Pool()
    original = state._ensure_session_loaded
    loaded, release = asyncio.Event(), asyncio.Event()
    async def pause_loaded(sid, **kwargs):
        await original(sid, **kwargs)
        if sid == a.session_id and asyncio.current_task().get_name() == 'derived-query':
            loaded.set()
            await release.wait()
    state._ensure_session_loaded = pause_loaded
    call = getattr(state, f'{operation}_derived_state')
    args = (a.session_id, 'todo', 'plan') + (({'step': 1},) if operation == 'put' else ())
    task = asyncio.create_task(call(*args), name='derived-query')
    try:
        await asyncio.wait_for(loaded.wait(), 1)
        await state.get_session(b.session_id)
        assert a.session_id in state._sessions, 'another request evicted a Session in use'
    finally:
        release.set()
        await task
    assert len(state._sessions) <= 1
    assert not state._session_cache.users


async def test_derived_only_reads_apply_the_session_cache_capacity():
    state = _MysqlSessionState('mysql://unused/test', max_cached_sessions=1)
    state._ensure_ready = AsyncMock()
    cursor, connection = AsyncMock(), AsyncMock()
    cursor.fetchone.return_value = None
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection
    state._pool = Pool()
    payloads = {}
    for key in ('first', 'second', 'third'):
        handle, value = await snapshot(key)
        value['runs'][0]['state'] = 'completed'
        payloads[handle.session_id] = value
    state._fetch_session = AsyncMock(side_effect=lambda sid: payloads[sid])
    for sid in payloads:
        await state.get_derived_state(sid, 'todo', 'plan')
        assert len(state._sessions) <= 1


async def test_cancelled_subscription_setup_releases_its_retained_session():
    from sagents.v2.contracts.run_state import EventCursor
    handle, payload = await snapshot('subscribe')
    payload['runs'][0]['state'] = 'completed'
    state = _MysqlSessionState('mysql://unused/test', cache_idle_seconds=0)
    state._install_session_locked(payload)
    stream = state.subscribe_events(EventCursor(run_id=handle.run_id))
    async with state._lock:
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await stream.aclose()
    await state._session_cache.prune()
    assert not state._session_cache.users
    assert handle.session_id not in state._sessions


async def test_subscription_can_be_closed_by_a_different_task_without_retained_pins():
    from sagents.v2.contracts.run_state import EventCursor
    handle, payload = await snapshot('cross-task')
    payload['runs'][0]['state'] = 'completed'
    state = _MysqlSessionState('mysql://unused/test', cache_idle_seconds=0)
    state._install_session_locked(payload)
    stream = state.subscribe_events(EventCursor(run_id=handle.run_id))
    event = await asyncio.create_task(anext(stream))
    assert event.run_id == handle.run_id
    assert handle.session_id in state._sessions
    assert state._session_cache.users[handle.session_id] == 1
    await asyncio.create_task(stream.aclose())
    assert not state._session_cache.users
    assert handle.session_id not in state._sessions


async def test_cache_eviction_drops_only_session_memory_and_idle_synchronization():
    handle, payload = await snapshot('evict-projection')
    payload['runs'][0]['state'] = 'completed'
    state = _MysqlSessionState('mysql://unused/test', cache_idle_seconds=0)
    state._install_session_locked(payload)
    state._derived_state[(handle.session_id, 'todo', 'plan')] = {'large': 'x' * 100_000}
    state._derived_state[('unrelated', 'todo', 'plan')] = {'keep': True}
    state._session_locks[handle.session_id] = asyncio.Lock()
    state._subscribers[handle.run_id] = set()
    state.forget_session = AsyncMock(side_effect=AssertionError('eviction deleted durable projection'))
    await state._session_cache.prune()
    assert (handle.session_id, 'todo', 'plan') not in state._derived_state
    assert state._derived_state[('unrelated', 'todo', 'plan')] == {'keep': True}
    assert handle.session_id not in state._session_locks
    assert handle.run_id not in state._subscribers
    state.forget_session.assert_not_awaited()


async def test_forced_reload_eviction_preserves_in_use_lock_and_subscriber_identity():
    handle, payload = await snapshot('recover')
    state = _MysqlSessionState('mysql://unused/test')
    state._install_session_locked(payload)
    lock = state._session_locks[handle.session_id] = asyncio.Lock()
    subscriber = object()
    state._subscribers[handle.run_id] = {subscriber}
    async with state._session_cache.operation():
        state._session_cache.pin(handle.session_id)
        async with lock:
            state._evict_session_locked(handle.session_id)
            assert state._session_locks[handle.session_id] is lock
            assert state._subscribers[handle.run_id] == {subscriber}
            state._install_session_locked(payload)
    assert state._session_locks[handle.session_id] is lock
    assert state._subscribers[handle.run_id] == {subscriber}


async def test_real_mysql_eviction_keeps_durable_projection_and_attachment(mysql_dsn):
    prefix = 'cache_' + uuid4().hex[:12]
    store = MysqlSessionStore(mysql_dsn, table_prefix=prefix, cache_idle_seconds=0)
    try:
        created = await store.create_run(command('projection-attachment'), CONTEXT)
        sid, rid = created.handle.session_id, created.handle.run_id
        running = await store.commit_run(run_id=rid, expected_revision=created.handle.run_revision,
            expected_states={RunState.QUEUED}, new_state=RunState.RUNNING,
            drafts=(EventDraft(type='run.started', data=RunEventData(state='running')),),
            context=CONTEXT, idempotency_key='running')
        await store.commit_run(run_id=rid, expected_revision=running.run.revision,
            expected_states={RunState.RUNNING}, new_state=RunState.COMPLETED,
            drafts=(EventDraft(type='run.completed', data=RunEventData(state='completed')),),
            context=CONTEXT, idempotency_key='completed')
        assert not store._sessions
        value = {'plan': 'durable projection'}
        await store.put_derived_state(sid, 'todo', 'plan', value)
        assert not store._sessions and not store._derived_state
        assert await store.get_derived_state(sid, 'todo', 'plan') == value
        assert await store.get_run_context(rid) == CONTEXT
        async def content():
            yield b'durable attachment'
        await store.put_attachment(sid, artifact_id='proof', media_type='text/plain', content=content(), context=CONTEXT)
        reference, stream = await store.get_attachment(sid, 'proof', context=CONTEXT)
        assert not store._sessions
        async def consume():
            return b''.join([chunk async for chunk in stream])
        assert await asyncio.create_task(consume()) == b'durable attachment'
        assert reference.size_bytes == len(b'durable attachment')
        assert not store._attachment_payloads
    finally:
        await store.close()
