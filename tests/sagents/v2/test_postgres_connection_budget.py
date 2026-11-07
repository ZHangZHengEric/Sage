"""Cancellation and saturation must never leak PostgreSQL connection capacity."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.postgres.connections import (
    PostgresConnectionBudget,
)

pytest.importorskip("psycopg_pool")


def fake_pool(*, rollback_error=None, release_error=None):
    connection = SimpleNamespace(
        closed=False, rollback=AsyncMock(side_effect=rollback_error), close=AsyncMock()
    )
    pool = SimpleNamespace(
        getconn=AsyncMock(return_value=connection),
        putconn=AsyncMock(side_effect=release_error),
    )
    return connection, pool, AsyncMock(return_value=pool)


@pytest.mark.parametrize("stage", ["rollback", "release"])
async def test_cleanup_error_preserves_inflight_cancellation(stage):
    failure = RuntimeError("cleanup failed")
    connection, pool, ready = fake_pool(**{f"{stage}_error": failure})
    budget = PostgresConnectionBudget(max_connections=2)
    cancellation = asyncio.CancelledError("shutdown")
    with pytest.raises(asyncio.CancelledError) as caught:
        async with budget.connection(ready, reader=True):
            raise cancellation
    assert caught.value is cancellation
    assert "cleanup failed" in str(cancellation.__notes__)
    pool.putconn.assert_awaited_once_with(connection)
    if stage == "rollback":
        connection.close.assert_awaited_once()
    _, _, replacement = fake_pool()
    async with asyncio.timeout(1):
        async with budget.connection(replacement, reader=True):
            async with budget.connection(replacement, reader=False):
                pass


async def test_reader_saturation_reserves_writer_capacity_and_bounds_queue():
    _, _, ready = fake_pool()
    budget = PostgresConnectionBudget(
        max_connections=2,
        max_pending_connections=1,
        connection_acquire_timeout_seconds=0.1,
    )
    async with budget.connection(ready, reader=True):
        started = asyncio.Event()

        async def wait_for_read():
            started.set()
            async with budget.connection(ready, reader=True):
                pytest.fail("second reader bypassed read budget")

        waiting = asyncio.create_task(wait_for_read())
        await started.wait()
        async with budget.connection(ready, reader=False):
            pass
        with pytest.raises(SageV2Error) as full:
            async with budget.connection(ready, reader=True):
                pass
        assert full.value.info.code == "session_store.postgres_busy"
        with pytest.raises(SageV2Error) as timeout:
            await waiting
        assert timeout.value.info.retryable and timeout.value.info.safe_to_resume
    assert budget._waiting == 0
    async with budget.connection(ready, reader=True):
        pass


async def test_repeated_cancellation_waits_for_rollback_before_releasing_capacity():
    connection, pool, ready = fake_pool()
    entered, cleanup_started, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def rollback():
        cleanup_started.set()
        await release.wait()

    connection.rollback.side_effect = rollback
    budget = PostgresConnectionBudget(max_connections=2)

    async def operation():
        async with budget.connection(ready, reader=True):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    await cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    pool.putconn.assert_not_awaited()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    pool.putconn.assert_awaited_once()
    assert budget._read_slots._value == 1 and budget._slots._value == 2


async def test_live_query_cancellation_returns_usable_connection():
    import os
    from uuid import uuid4
    from sagents.v2.runtime.session.plugins.postgres import PostgresSessionStore

    dsn = os.environ.get("SAGE_V2_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_POSTGRES_DSN for live cancellation test")
    store = PostgresSessionStore(
        dsn, table_prefix="cancel_" + uuid4().hex[:12], max_connections=2
    )
    entered = asyncio.Event()

    async def query():
        async with store._reader_connection() as connection:
            entered.set()
            await connection.execute("SELECT pg_sleep(30)")

    try:
        task = asyncio.create_task(query())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with store._writer_connection() as connection:
            assert (await (await connection.execute("SELECT 42")).fetchone())[0] == 42
        assert store._connection_budget._waiting == 0
    finally:
        async with store._writer_connection() as connection:
            for table in (
                "attachments",
                "derived_state",
                "start_idempotency",
                "locations",
                "run_events",
                "session_mutations",
                "sessions",
            ):
                await connection.execute(f"DROP TABLE IF EXISTS {store._table(table)}")
            await connection.commit()
        await store.close()
