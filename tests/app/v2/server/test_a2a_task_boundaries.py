"""A2A Task authorization and stable pages without unrelated event hydration."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.v2.server.conversations.a2a.service import A2AService
from app.v2.server.identity.keys import ApiKeyRecord
from app.v2.server.identity.context import RequestContexts
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.session.access import AuthorizedSessionAccess
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from tests.app.v2.server.fakes import MemoryThreadIndex


def service(store, threads):
    context = RequestContexts('en').for_user('owner')
    return A2AService(threads=threads, catalog=None, admission=None,
        runs=SimpleNamespace(cancel_run=AsyncMock()),
        application=SimpleNamespace(runtime=SimpleNamespace(session_store=store)),
        session_access=AuthorizedSessionAccess(store), context_for=lambda *_: context,
        language='en', public_base_url='')


async def create(store, threads, session_id, agent_id, key, *, input_items=()):
    context = RequestContexts('en').for_user('owner')
    result = await store.create_run(StartRun(agent_id=agent_id, session_id=session_id,
        input=input_items, resolved_spec_hash='sha256:test', idempotency_key=key), context)
    await threads.upsert(session_id, 'owner', agent_id=agent_id)
    return result.handle.run_id


@pytest.mark.parametrize('operation', ['get_task', 'subscribe_task', 'cancel_task'])
async def test_bound_key_cannot_read_subscribe_or_cancel_another_agent(operation):
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    run_id = await create(store, threads, 'private', 'agent-b', 'private')
    api = service(store, threads)
    key = ApiKeyRecord(key_id='key-a', owner_user_id='owner', agent_id='agent-a')
    with pytest.raises(SageV2Error, match='task not found'):
        await getattr(api, operation)(run_id, key)
    api._runs.cancel_run.assert_not_awaited()


async def test_list_is_agent_scoped_and_does_not_materialize_unrelated_history():
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    hidden = await create(store, threads, 'hidden', 'agent-b', 'hidden')
    own = await create(store, threads, 'own', 'agent-a', 'own')
    api = service(store, threads)
    original = store.read_events
    async def read(run_id, **options):
        assert run_id != hidden, 'another Agent Task history was read'
        return await original(run_id, **options)
    store.read_events = read
    threads.list_for = AsyncMock(side_effect=AssertionError('all owner threads loaded'))
    store.list_session_runs = AsyncMock(side_effect=AssertionError('full Session runs loaded'))
    tasks, token = await api.list_tasks(ApiKeyRecord(key_id='key-a', owner_user_id='owner', agent_id='agent-a'))
    assert [task.id for task in tasks] == [own]
    assert not token


@pytest.mark.parametrize('history_length', [0, 1])
async def test_task_page_matches_individual_tasks_without_per_task_event_reads(history_length):
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    run_ids = [await create(store, threads, f'session-{i}', 'agent-a', f'key-{i}',
                           input_items=tuple(InputItem(role='user', content=(TextBlock(text=f'{i}:{j}'),))
                                             for j in range(2)))
               for i in range(12)]
    api = service(store, threads)
    key = ApiKeyRecord(key_id='key-a', owner_user_id='owner', agent_id='agent-a')
    expected = {rid: (await api.get_task(rid, key, history_length=history_length)).SerializeToString()
                for rid in run_ids}
    store.read_events = AsyncMock(side_effect=AssertionError('Task page fetched events per Run'))
    page, token = await api.list_tasks(key, history_length=history_length)
    assert not token
    assert {task.id: task.SerializeToString() for task in page} == expected


async def test_list_cursor_does_not_repeat_tasks_when_a_new_thread_arrives():
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    older = await create(store, threads, 'older', 'agent-a', 'older')
    newer = await create(store, threads, 'newer', 'agent-a', 'newer')
    api = service(store, threads)
    key = ApiKeyRecord(key_id='key-a', owner_user_id='owner', agent_id='agent-a')
    first, cursor = await api.list_tasks(key, page_size=1)
    assert [task.id for task in first] == [newer] and cursor
    await create(store, threads, 'arriving', 'agent-a', 'arriving')
    second, cursor = await api.list_tasks(key, page_size=1, page_token=cursor)
    assert [task.id for task in second] == [older]
    assert not cursor


@pytest.mark.parametrize('mutation', ['touch-current','delete-current'])
async def test_cursor_continues_runs_in_its_original_thread_order(mutation):
    from sagents.v2.contracts.run_state import SessionConcurrencyMode
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    expected = {}
    for sid in ('older','newer'):
        ids = []
        for index in range(5):
            context = RequestContexts('en').for_user('owner')
            result = await store.create_run(StartRun(agent_id='a',session_id=sid,input=(),
                session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
                resolved_spec_hash='sha256:test',idempotency_key=sid+str(index)),context)
            ids.append(result.handle.run_id)
        await threads.upsert(sid,'owner',agent_id='a')
        expected[sid] = ids
    api = service(store,threads)
    key = ApiKeyRecord(key_id='key',owner_user_id='owner',agent_id='a')
    first, token = await api.list_tasks(key,page_size=2)
    assert [task.id for task in first] == expected['newer'][:2]
    if mutation == 'touch-current':
        await threads.upsert('newer','owner',agent_id='a')
        rest = expected['newer'][2:] + expected['older']
    else:
        await threads.remove('newer','owner')
        rest = expected['older']
    seen = []
    for _ in range(10):
        page, token = await api.list_tasks(key,page_size=2,page_token=token)
        seen.extend(task.id for task in page)
        if not token:
            break
    assert not token
    assert seen == rest
    assert len(seen) == len(set(seen))


async def test_state_and_context_filters_cross_an_entire_empty_thread_batch_without_truncation():
    from a2a.types.a2a_pb2 import TaskState
    from sagents.v2.contracts.events import RunEventData
    from sagents.v2.runtime.session.contracts import EventDraft
    from sagents.v2.contracts.run_state import RunState
    store, threads = SessionStoreCoordinator(), MemoryThreadIndex()
    selected = await create(store,threads,'oldest','a','oldest')
    current = await store.get_run(selected)
    await store.commit_run(run_id=selected,expected_revision=current.revision,
        expected_states={current.state},new_state=RunState.CANCELLED,
        drafts=(EventDraft(type='run.cancelled',data=RunEventData(state=RunState.CANCELLED)),),
        context=RequestContexts('en').for_user('owner'),idempotency_key='cancel')
    for number in range(205):
        await create(store,threads,f'empty-{number:03d}','a',f'empty-{number:03d}')
    api = service(store,threads)
    key = ApiKeyRecord(key_id='key',owner_user_id='owner',agent_id='a')
    page, token = await api.list_tasks(key,state=TaskState.TASK_STATE_CANCELED,page_size=1)
    assert [task.id for task in page] == [selected] and not token
    assert page[0].status.state == TaskState.TASK_STATE_CANCELED
    by_context, token = await api.list_tasks(key,context_id='oldest',page_size=1)
    assert [task.SerializeToString() for task in by_context] == [task.SerializeToString() for task in page]
    assert not token
    assert await api.list_tasks(key,context_id='missing') == ([], '')


@pytest.mark.parametrize('value', ['not-base64','W10=','WyJ2MiJd','djE6MDow'])
async def test_bad_cursor_is_a_validation_error(value):
    from sagents.v2.contracts.errors import ErrorCategory
    api = service(SessionStoreCoordinator(),MemoryThreadIndex())
    with pytest.raises(SageV2Error) as caught:
        await api.list_tasks(ApiKeyRecord(key_id='key',owner_user_id='owner',agent_id='a'),page_token=value)
    assert caught.value.info.category == ErrorCategory.VALIDATION
