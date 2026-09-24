from __future__ import annotations

import asyncio
from pydantic import SecretStr
import pytest

from app.server_v2.catalog.records import ModelRecord
from app.server_v2.runtime.model_pool import ExceptionGroup, ModelClientPool
from sagents.v2.contracts.errors import SageV2Error


def record(name="model", key="secret"):
    return ModelRecord(id=name, model="demo", api_key=SecretStr(key))


class Client:
    def __init__(self):
        self.closed = False

    async def close(self):
        assert not self.closed
        self.closed = True


async def close(client):
    await client.close()


@pytest.mark.asyncio
async def test_parallel_and_sequential_runs_share_one_client():
    made = []

    async def factory(record):
        await asyncio.sleep(0)
        made.append(Client())
        return made[-1]

    pool = ModelClientPool(factory, close, max_clients=2)
    leases = await asyncio.gather(*(pool.acquire("alice", record()) for _ in range(50)))
    assert len(made) == 1
    assert (await pool.snapshot())["active_leases"] == 50
    await asyncio.gather(*(lease.close() for lease in leases))
    again = await pool.acquire("alice", record())
    assert again.provider is made[0]
    await again.close()
    assert not made[0].closed
    await pool.close()
    await pool.close()
    assert made[0].closed


@pytest.mark.asyncio
async def test_owner_and_rotated_credential_have_distinct_clients():
    async def factory(record):
        return Client()

    pool = ModelClientPool(factory, close, max_clients=3)
    a = await pool.acquire("alice", record())
    b = await pool.acquire("bob", record())
    changed = await pool.acquire("alice", record(key="new-secret"))
    assert len({id(x.provider) for x in (a, b, changed)}) == 3
    assert not a.provider.closed
    assert all("secret" not in key for key in pool._entries)
    await asyncio.gather(*(lease.close() for lease in (a, b, changed)))
    await pool.close()


@pytest.mark.asyncio
async def test_only_idle_clients_are_evicted_and_all_busy_has_backpressure():
    async def factory(record):
        return Client()

    pool = ModelClientPool(factory, close, max_clients=2)
    a = await pool.acquire("alice", record("a"))
    b = await pool.acquire("alice", record("b"))
    with pytest.raises(SageV2Error) as caught:
        await pool.acquire("alice", record("c"))
    assert caught.value.info.code == "server.model_pool_full"
    assert caught.value.info.retryable
    await b.close()
    c = await pool.acquire("alice", record("c"))
    assert b.provider.closed
    assert not a.provider.closed
    assert (await pool.snapshot())["clients"] == 2
    await a.close()
    await c.close()
    await pool.close()


@pytest.mark.asyncio
async def test_cancelling_one_initialization_waiter_preserves_other_users():
    gate = asyncio.Event()
    entered = asyncio.Event()
    client = Client()

    async def factory(record):
        entered.set()
        await gate.wait()
        return client

    pool = ModelClientPool(factory, close, max_clients=1)
    a = asyncio.create_task(pool.acquire("alice", record()))
    b = asyncio.create_task(pool.acquire("alice", record()))
    try:
        await entered.wait()
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        assert (await pool.snapshot())["active_leases"] == 1
        gate.set()
        lease = await b
        assert lease.provider is client
        assert not client.closed
        await lease.close()
    finally:
        gate.set()
        await asyncio.gather(a, b, return_exceptions=True)
        await pool.close()
    assert client.closed


@pytest.mark.asyncio
async def test_initialization_failure_does_not_poison_the_cache():
    attempts = 0

    async def factory(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("initialization failed")
        return Client()

    pool = ModelClientPool(factory, close, max_clients=1)
    with pytest.raises(ValueError):
        await pool.acquire("alice", record())
    lease = await pool.acquire("alice", record())
    assert attempts == 2
    await lease.close()
    await pool.close()


@pytest.mark.asyncio
async def test_shutdown_waits_for_borrowers_and_continues_after_observer_cancel():
    async def factory(record):
        return Client()

    pool = ModelClientPool(factory, close)
    lease = await pool.acquire("alice", record())
    shutdown = asyncio.create_task(pool.close())
    await asyncio.sleep(0)
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    assert not lease.provider.closed
    with pytest.raises(RuntimeError, match="closed"):
        await pool.acquire("alice", record())
    await lease.close()
    await pool.close()
    assert lease.provider.closed


@pytest.mark.asyncio
async def test_eviction_keeps_physical_capacity_until_close_finishes():
    gate = asyncio.Event()
    closing = asyncio.Event()
    made = []

    async def factory(record):
        made.append(Client())
        return made[-1]

    async def slow_close(client):
        closing.set()
        await gate.wait()
        await client.close()

    pool = ModelClientPool(factory, slow_close, max_clients=1)
    lease = await pool.acquire("alice", record("a"))
    await lease.close()
    replacement = asyncio.create_task(pool.acquire("alice", record("b")))
    try:
        await closing.wait()
        assert len(made) == 1
        with pytest.raises(SageV2Error):
            await pool.acquire("alice", record("c"))
        gate.set()
        second = await replacement
        assert len(made) == 2
        assert made[0].closed
        await second.close()
    finally:
        gate.set()
        await asyncio.gather(replacement, return_exceptions=True)
        await pool.close()


@pytest.mark.asyncio
async def test_cleanup_failure_still_attempts_other_clients():
    made = []

    async def factory(record):
        made.append(Client())
        return made[-1]

    async def failing_close(client):
        await client.close()
        if client is made[0]:
            raise ValueError("close failed")

    pool = ModelClientPool(factory, failing_close)
    for name in ("a", "b"):
        lease = await pool.acquire("alice", record(name))
        await lease.close()
    with pytest.raises(ExceptionGroup):
        await pool.close()
    assert all(client.closed for client in made)


@pytest.mark.asyncio
async def test_mixed_concurrent_runs_release_every_lease_and_bound_clients():
    made = []

    async def factory(record):
        await asyncio.sleep(0)
        client = Client()
        made.append(client)
        return client

    pool = ModelClientPool(factory, close, max_clients=8)
    seen = set()

    async def run(index):
        lease = await pool.acquire(f"user-{index % 8}", record())
        try:
            seen.add(id(lease.provider))
            await asyncio.sleep(0)
            if index % 7 == 0:
                raise asyncio.CancelledError
            if index % 11 == 0:
                raise ValueError("simulated model failure")
            assert not lease.provider.closed
        finally:
            await lease.close()

    for wave in range(40):
        results = await asyncio.gather(
            *(run(wave * 32 + i) for i in range(32)), return_exceptions=True
        )
        assert all(
            result is None or isinstance(result, (ValueError, asyncio.CancelledError))
            for result in results
        )
        status = await pool.snapshot()
        assert status["active_leases"] == 0
        assert status["clients"] == status["constructions"] == 8
    assert len(seen) == len(made) == 8
    await pool.close()
    assert all(client.closed for client in made)
