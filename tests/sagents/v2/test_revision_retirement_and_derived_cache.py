"""Cancelled retention cleanup cannot republish half-closed resources."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.sdk_fixture import build_registered_app
from tests.sagents.v2.test_loaded_agents import command, context, model, package
from tests.sagents.v2.test_mysql_loading_efficiency import snapshot
from tests.sagents.v2.test_mysql_session_store_matrix import CONTEXT, command as session_command
from tests.sagents.v2.test_redis_mysql_session_store import Archive, store as redis_store


def another_package(name):
    original = package()
    return original.model_copy(update={'metadata':original.metadata.model_copy(update={'id':name})})


async def expiring_agent(app, resource):
    await app.load_agent(package())
    agent = await app.load_agent(another_package('test.retiring'))
    agent._application._owned_resources.append(resource)
    catalog = app._loaded_agents
    catalog._last_used[(agent.package_id, agent.version)] -= catalog.revision_idle_seconds + 1
    return agent


class ClosingGate:
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.closed = False

    async def close(self):
        self.entered.set()
        await self.release.wait()
        self.closed = True


async def cancel_load_during_retirement(app, gate):
    task = asyncio.create_task(app.load_agent(another_package('test.trigger-retirement')))
    await asyncio.wait_for(gate.entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancelled_load_keeps_retirement_isolated_and_old_handle_can_restore(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    gate, waiting = ClosingGate(), None
    try:
        agent = await expiring_agent(app, gate)
        original_application = agent._application
        await cancel_load_during_retirement(app, gate)
        catalog = app._loaded_agents
        key = agent.package_id, agent.version
        assert key not in catalog.revisions, 'cancelled cleanup published a half-closed revision'
        assert key in catalog._retiring
        waiting = asyncio.create_task(app.entrypoint().run_stream(command(agent, 'old-handle'), context(), agent=agent))
        await asyncio.sleep(0)
        assert not waiting.done()
        gate.release.set()
        stream = await asyncio.wait_for(waiting, 3)
        try:
            assert (await stream.wait()).state.value == 'completed'
            assert stream.handle.resolved_spec_hash == agent.composition_hash
        finally:
            await stream.detach()
        assert original_application._closed and gate.closed
        assert not catalog._retiring
    finally:
        gate.release.set()
        if waiting is not None:
            await asyncio.gather(waiting, return_exceptions=True)
        await app.close()


@pytest.mark.asyncio
async def test_failed_retirement_stays_isolated_and_retries_before_restoring(tmp_path):
    class FailsOnce:
        def __init__(self):
            self.attempts = 0
        async def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError('temporary teardown failure')
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    resource = FailsOnce()
    try:
        agent = await expiring_agent(app, resource)
        original_application = agent._application
        catalog = app._loaded_agents
        with pytest.raises(RuntimeError, match='failed to close'):
            await catalog.prune_revisions()
        key = agent.package_id, agent.version
        assert key not in catalog.revisions
        assert key in catalog._retiring
        stream = await app.entrypoint().run_stream(command(agent, 'retry-retirement'), context(), agent=agent)
        try:
            assert (await stream.wait()).state.value == 'completed'
        finally:
            await stream.detach()
        assert resource.attempts == 2 and original_application._closed
        assert not catalog._retiring
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_app_shutdown_joins_retirement_left_by_cancelled_loader(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    gate, closing = ClosingGate(), None
    try:
        agent = await expiring_agent(app, gate)
        original_application = agent._application
        await cancel_load_during_retirement(app, gate)
        closing = asyncio.create_task(app.close())
        await asyncio.sleep(0)
        assert not closing.done()
        gate.release.set()
        await asyncio.wait_for(closing, 3)
        assert app._closed and original_application._closed and gate.closed
        assert not app._loaded_agents._retiring
        assert not app._owned_resources
    finally:
        gate.release.set()
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        await app.close()


@pytest.mark.asyncio
async def test_cancelled_old_handle_waiter_does_not_cancel_retirement(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    gate = ClosingGate()
    try:
        agent = await expiring_agent(app, gate)
        await cancel_load_during_retirement(app, gate)
        catalog = app._loaded_agents
        key = agent.package_id, agent.version
        retirement = catalog._retiring[key].task
        waiter = asyncio.create_task(catalog.restored(agent))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not retirement.done()
        assert key not in catalog.revisions
        gate.release.set()
        restored = await asyncio.wait_for(catalog.restored(agent), 3)
        assert restored is not agent
        assert restored.composition_hash == agent.composition_hash
        assert retirement.done() and not retirement.cancelled()
    finally:
        gate.release.set()
        await app.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('retire_via', ['prune', 'new-load'])
async def test_persistent_retirement_failure_is_owned_until_shutdown_retry(tmp_path, retire_via):
    class FailingResource:
        fail = True
        closed = False
        attempts = 0

        async def close(self):
            self.attempts += 1
            if self.fail:
                raise OSError('teardown unavailable')
            self.closed = True

    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    resource = FailingResource()
    try:
        agent = await expiring_agent(app, resource)
        original_application = agent._application
        key = agent.package_id, agent.version
        if retire_via == 'prune':
            with pytest.raises(RuntimeError, match='failed to close'):
                await app._loaded_agents.prune_revisions()
        else:
            await app.load_agent(another_package('test.healthy-trigger'))
        # The failing old revision stays owned, but unrelated new work must
        # still load and run through its own healthy resources.
        healthy = await app.load_agent(another_package('test.healthy-after-close-error'))
        assert resource.attempts == 1, 'unrelated admission retried quarantined teardown'
        stream = await app.entrypoint().run_stream(command(healthy, 'healthy'), context(), agent=healthy)
        try:
            assert (await stream.wait()).state.value == 'completed'
        finally:
            await stream.detach()
        with pytest.raises(RuntimeError, match='failed to close'):
            await app._loaded_agents.restored(agent)
        assert key not in app._loaded_agents.revisions
        assert original_application in app._owned_resources
        with pytest.raises(RuntimeError, match='failed to close'):
            await app.close()
        assert not app._closed
        assert original_application in app._owned_resources
        resource.fail = False
        await app.close()
        assert app._closed and original_application._closed and resource.closed
        assert not app._loaded_agents._retiring
        assert not app._owned_resources
    finally:
        resource.fail = False
        await app.close()


async def mysql_with_completed_session():
    handle, payload = await snapshot('derived-retention')
    payload['runs'][0]['state'] = 'completed'
    state = _MysqlSessionState('mysql://unused/test', max_cached_bytes=100 * 1024)
    state._ensure_ready = AsyncMock()
    state._install_session_locked(payload)
    cursor, connection = AsyncMock(), AsyncMock()
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection
    state._pool = Pool()
    return state, handle.session_id, cursor, connection


@pytest.mark.asyncio
async def test_mysql_derived_crud_keeps_only_the_durable_copy():
    state, sid, cursor, connection = await mysql_with_completed_session()
    value = {'text':'x' * (2 * 1024 * 1024)}
    await state.put_derived_state(sid, 'summary', 'last', value)
    assert not state._derived_state, 'MySQL reads SQL but retained an unbudgeted duplicate'
    assert any(json.loads(call.args[1][-1]) == value for call in cursor.execute.await_args_list if 'INSERT INTO' in call.args[0])
    connection.commit.assert_awaited_once()
    cursor.fetchone.return_value = (json.dumps(value),)
    assert await state.get_derived_state(sid, 'summary', 'last') == value
    await state.delete_derived_state(sid, 'summary', 'last')
    cursor.fetchone.return_value = None
    assert await state.get_derived_state(sid, 'summary', 'last') is None
    assert not state._derived_state


@pytest.mark.asyncio
async def test_failed_mysql_derived_write_does_not_leave_a_process_copy():
    state, sid, _cursor, connection = await mysql_with_completed_session()
    connection.commit.side_effect = OSError('database unavailable')
    with pytest.raises(OSError, match='database unavailable'):
        await state.put_derived_state(sid, 'summary', 'last', {'text':'not committed'})
    assert not state._derived_state
    connection.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_derived_state_stays_authoritative_after_mysql_cache_change():
    value = redis_store(fakeredis.aioredis.FakeRedis(decode_responses=True), Archive())
    try:
        created = await value.create_run(session_command('redis-derived'), CONTEXT)
        sid = created.handle.session_id
        await value.put_derived_state(sid, 'summary', 'last', {'text':'in Redis'})
        assert await value.get_derived_state(sid, 'summary', 'last') == {'text':'in Redis'}
        assert not value._derived_state
        await value.delete_derived_state(sid, 'summary', 'last')
        assert await value.get_derived_state(sid, 'summary', 'last') is None
    finally:
        await value.close()
