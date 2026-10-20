"""Accepted approvals survive request cancellation, but remain host-owned."""
import asyncio
from contextlib import AsyncExitStack

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import CompletingJudgeModel, register_and_login
from tests.app.v2.server.test_a2a_resume import _step
from tests.app.v2.server.test_external_chat import make_host


@pytest.fixture
def approval_case(tmp_path):
    host = make_host(tmp_path)
    host.execution.fallback_model = CompletingJudgeModel(ScriptedModelProvider((
        _step(1, '', 'file_write', {'file_path': 'approved.txt', 'content': 'kept'}),
        _step(2, 'done'),
    )))
    with TestClient(create_app(host)) as client:
        client.headers['Authorization'] = 'Bearer ' + register_and_login(client)
        assert client.put('/api/auth/execution-policy', json={'shell': 'ask'}).status_code == 200
        package = client.get('/api/agent-packages/template').json()['data']
        package['manifest']['agents']['assistant']['tools'] = ['file_write']
        response = client.post('/api/agent-package', json={
            'threadId': 'accepted-handoff', 'runId': 'first', 'agent_package': package,
            'messages': [{'id': 'm', 'role': 'user', 'content': 'write'}],
        })
        assert response.status_code == 200, response.text
        item = client.get('/api/approvals').json()['data']['items'][0]
        thread = client.get('/api/threads/accepted-handoff').json()['data']
        yield host, client, item, thread


async def settle_observers(host):
    async with asyncio.timeout(3):
        while host.execution._drives:
            await asyncio.sleep(.001)


async def decide(host, item, thread):
    return await host.conversations.decide_approval(item['run_id'], user_id=thread['user_id'],
        decision='approve_once', payload={}, expected=item['expected'])


@pytest.mark.parametrize('stage', ['accepting', 'workspace', 'loading'])
def test_accepted_approval_completes_after_request_is_cancelled(approval_case, tmp_path, stage):
    host, client, item, thread = approval_case

    async def interrupt():
        await settle_observers(host)
        entered, release = asyncio.Event(), asyncio.Event()
        runtime, application = host.application.runtime, host.application
        original_reply, original_load = runtime.reply_interaction, application.agent_for_run
        task = None
        try:
            async with AsyncExitStack() as stack:
                if stage == 'workspace':
                    await stack.enter_async_context(host.conversations.runs.workspace_guard(thread['user_id'], thread['agent_id']))
                elif stage == 'accepting':
                    async def reply(*args, **kwargs):
                        receipt = await original_reply(*args, **kwargs)
                        entered.set()
                        await release.wait()
                        return receipt
                    runtime.reply_interaction = reply
                else:
                    async def load(*args, **kwargs):
                        entered.set()
                        await release.wait()
                        return await original_load(*args, **kwargs)
                    application.agent_for_run = load
                task = asyncio.create_task(decide(host, item, thread))
                if stage == 'workspace':
                    async with asyncio.timeout(3):
                        while (await runtime.get_run(item['run_id'])).state.value != 'resuming':
                            await asyncio.sleep(.001)
                else:
                    await asyncio.wait_for(entered.wait(), 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                release.set()
            async with asyncio.timeout(3):
                while (await runtime.get_run(item['run_id'])).state.value == 'resuming':
                    await asyncio.sleep(.001)
                while (await runtime.get_run(item['run_id'])).state.value in {'running', 'queued'}:
                    await asyncio.sleep(.001)
            assert (await runtime.get_run(item['run_id'])).state.value == 'completed'
        finally:
            release.set()
            runtime.reply_interaction, application.agent_for_run = original_reply, original_load
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
    client.portal.call(interrupt)
    assert next(tmp_path.rglob('approved.txt')).read_text() == 'kept'


@pytest.mark.parametrize('stage', ['workspace', 'loading', 'driver'])
def test_host_shutdown_joins_accepted_handoff_and_sdk_execution(approval_case, stage):
    host, client, item, thread = approval_case

    async def shutdown():
        await settle_observers(host)
        entered, stopped = asyncio.Event(), asyncio.Event()
        application = host.application
        original_load = application.agent_for_run
        model = host.execution.fallback_model
        original_stream = model.stream
        task = None
        try:
            async with AsyncExitStack() as stack:
                if stage == 'workspace':
                    await stack.enter_async_context(host.conversations.runs.workspace_guard(thread['user_id'], thread['agent_id']))
                elif stage == 'loading':
                    async def load(*args, **kwargs):
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            stopped.set()
                    application.agent_for_run = load
                else:
                    async def stream(*args, **kwargs):
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                            async for event in original_stream(*args, **kwargs):
                                yield event
                        finally:
                            stopped.set()
                    model.stream = stream
                task = asyncio.create_task(decide(host, item, thread))
                if stage == 'workspace':
                    async with asyncio.timeout(3):
                        while (await application.runtime.get_run(item['run_id'])).state.value != 'resuming':
                            await asyncio.sleep(.001)
                else:
                    await asyncio.wait_for(entered.wait(), 3)
                if stage == 'driver':
                    assert (await task)['accepted'] is True
                else:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                await asyncio.wait_for(host.close(), 3)
                assert not host._tasks and not host.execution._tasks and not host.execution._drives
                if stage != 'workspace':
                    assert stopped.is_set()
                assert application._closed
        finally:
            application.agent_for_run, model.stream = original_load, original_stream
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
    client.portal.call(shutdown)


def test_shutdown_rejects_handoff_created_by_an_already_prechecked_request(approval_case):
    host, client, item, thread = approval_case

    async def shutdown_during_precheck():
        await settle_observers(host)
        prechecked, closing_entered = asyncio.Event(), asyncio.Event()
        finish_precheck, finish_identity = asyncio.Event(), asyncio.Event()
        runs, runtime = host.conversations.runs, host.application.runtime
        original_check, original_close = runs._check_execution_grant, host.identity.close
        async def check(*args):
            await original_check(*args)
            prechecked.set()
            await finish_precheck.wait()
        async def close_identity():
            closing_entered.set()
            await finish_identity.wait()
            await original_close()
        runs._check_execution_grant, host.identity.close = check, close_identity
        request, closing = None, None
        try:
            request = asyncio.create_task(decide(host, item, thread))
            await asyncio.wait_for(prechecked.wait(), 3)
            closing = asyncio.create_task(host.close())
            await asyncio.wait_for(closing_entered.wait(), 3)
            finish_precheck.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert (await runtime.get_run(item['run_id'])).state.value == 'suspended'
            assert not host.execution.driving(item['run_id'])
        finally:
            finish_precheck.set()
            finish_identity.set()
            runs._check_execution_grant, host.identity.close = original_check, original_close
            await asyncio.gather(*[task for task in (request, closing) if task is not None], return_exceptions=True)
    client.portal.call(shutdown_during_precheck)


def test_shutdown_joins_tasks_registered_during_its_cancellation_pass(approval_case):
    host, client, _item, _thread = approval_case

    async def shutdown_with_late_task():
        entered, late_entered = asyncio.Event(), asyncio.Event()
        late = []
        async def late_work():
            late_entered.set()
            await asyncio.Event().wait()
        async def initial_work():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                late.append(asyncio.create_task(late_work()))
                host._track(late[-1])
        initial = asyncio.create_task(initial_work())
        host._track(initial)
        try:
            await asyncio.wait_for(entered.wait(), 3)
            await asyncio.wait_for(host.close(), 3)
            assert initial.cancelled() and late[0].cancelled()
            assert not late_entered.is_set(), 'registered work executed after shutdown began'
            assert not host._tasks
        finally:
            for task in late:
                task.cancel()
            await asyncio.gather(initial, *late, return_exceptions=True)
    client.portal.call(shutdown_with_late_task)


def test_host_restart_can_accept_and_handoff_approval_again(approval_case):
    host, client, item, thread = approval_case

    async def restart():
        await settle_observers(host)
        await host.close()
        await host.start()
        assert (await decide(host, item, thread))['accepted'] is True
        async with asyncio.timeout(3):
            while (await host.application.runtime.get_run(item['run_id'])).state.value in {'resuming', 'running', 'queued'}:
                await asyncio.sleep(.001)
        assert (await host.application.runtime.get_run(item['run_id'])).state.value == 'completed'
    client.portal.call(restart)
