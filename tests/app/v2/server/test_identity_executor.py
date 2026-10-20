import asyncio
import threading

import pytest

from app.v2.server.identity.passwords import PasswordExecutor
from sagents.v2.contracts.errors import SageV2Error


@pytest.mark.asyncio
async def test_password_work_is_bounded_even_after_request_cancellation():
    executor = PasswordExecutor(workers=1, queued=1)
    started, release = threading.Event(), threading.Event()
    def blocked():
        started.set()
        release.wait(5)
        return 'done'
    first = asyncio.create_task(executor.run(blocked))
    try:
        await asyncio.to_thread(started.wait, 2)
        second = asyncio.create_task(executor.run(lambda: 'queued'))
        await asyncio.sleep(0)
        with pytest.raises(SageV2Error) as busy:
            await executor.run(lambda: 'overflow')
        assert busy.value.info.category.value == 'rate_limited'
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(SageV2Error):
            await executor.run(lambda: 'still full')
        release.set()
        assert await second == 'queued'
        assert await executor.run(lambda: 'after') == 'after'
    finally:
        release.set()
        await executor.close()
    with pytest.raises(SageV2Error):
        await executor.run(lambda: 'closed')


@pytest.mark.asyncio
async def test_identity_hash_and_verify_execute_off_the_event_loop(monkeypatch):
    from app.v2.server.identity import service as identity_module
    from tests.app.v2.server.fakes import MemoryUserStore
    service = identity_module.IdentityService(MemoryUserStore(), jwt_secret='test-secret', jwt_expire_hours=1)
    main_thread = threading.get_ident()
    operations = []
    hash_password, verify_password = identity_module.hash_password, identity_module.verify_password
    def recorded_hash(password):
        operations.append(('hash', threading.get_ident()))
        return hash_password(password)
    def recorded_verify(password, stored):
        operations.append(('verify', threading.get_ident()))
        return verify_password(password, stored)
    monkeypatch.setattr(identity_module, 'hash_password', recorded_hash)
    monkeypatch.setattr(identity_module, 'verify_password', recorded_verify)
    try:
        registered = await service.register('alice', 'secret1')
        assert (await service.authenticate('alice', 'secret1')).user_id == registered.user_id
        with pytest.raises(SageV2Error) as invalid:
            await service.authenticate('alice', 'wrong-pass')
        assert invalid.value.info.category.value == 'authentication'
        assert [name for name, _ in operations] == ['hash', 'verify', 'verify']
        assert all(worker != main_thread for _, worker in operations)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_cancelled_close_still_drains_work_and_shuts_down_the_pool(monkeypatch):
    executor = PasswordExecutor(workers=1, queued=0)
    started, release, shutdown = threading.Event(), threading.Event(), threading.Event()
    original_shutdown = executor._pool.shutdown
    shutdown_calls = []
    def record_shutdown(*args, **kwargs):
        shutdown_calls.append(True)
        shutdown.set()
        return original_shutdown(*args, **kwargs)
    monkeypatch.setattr(executor._pool, 'shutdown', record_shutdown)
    def blocked():
        started.set()
        release.wait(5)
        return 'finished'
    work = asyncio.create_task(executor.run(blocked))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        closing = asyncio.create_task(executor.close())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not shutdown.is_set()
        second_close = asyncio.create_task(executor.close())
        await asyncio.sleep(0)
        second_close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second_close
        assert not shutdown.is_set()
        with pytest.raises(SageV2Error):
            await executor.run(lambda: 'cannot reopen during close')
        release.set()
        assert await work == 'finished'
        assert await asyncio.to_thread(shutdown.wait, 2), 'cancelled close abandoned pool shutdown'
    finally:
        release.set()
        await executor.close()
    await executor.close()
    assert shutdown_calls == [True]


def test_same_host_can_close_and_start_again_with_working_password_authentication(tmp_path):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import make_test_service, register_and_login
    host = make_test_service(tmp_path)
    app = create_app(host)
    with TestClient(app) as client:
        register_and_login(client, 'before-restart')
    with TestClient(app) as client:
        response = client.post('/api/auth/login', json={'username': 'before-restart', 'password': 'secret1'})
        assert response.status_code == 200, response.text
        register_and_login(client, 'after-restart')
        admin = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin12345'})
        assert admin.status_code == 200, admin.text
