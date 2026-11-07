"""Real PostgreSQL archive locks must survive commits and release on every exit."""

import asyncio
import os
from uuid import uuid4

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.postgres.distributed_archive import (
    DistributedPostgresSessionArchive,
)


@pytest.fixture
async def archives():
    dsn = os.environ.get("SAGE_V2_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_POSTGRES_DSN to verify PostgreSQL session locks")
    prefix = "guard_" + uuid4().hex[:12]
    first, second = [
        DistributedPostgresSessionArchive(dsn, table_prefix=prefix) for _ in range(2)
    ]
    try:
        yield first, second
    finally:
        cleanup = DistributedPostgresSessionArchive(dsn, table_prefix=prefix)
        try:
            async with cleanup._writer_connection() as connection:
                for name in (
                    "attachments",
                    "derived_state",
                    "start_idempotency",
                    "locations",
                    "run_events",
                    "session_mutations",
                    "sessions",
                ):
                    await connection.execute(
                        f"DROP TABLE IF EXISTS {cleanup._table(name)}"
                    )
                await connection.commit()
        finally:
            for archive in (first, second, cleanup):
                await archive.close()


async def pid(connection):
    return (await (await connection.execute("SELECT pg_backend_pid()")).fetchone())[0]


async def test_session_lock_pins_one_connection_across_commits_and_blocks_other_owner(
    archives,
):
    first, second = archives
    entered = asyncio.Event()

    async def contender():
        async with second.session_guard("same"):
            entered.set()

    async with first.session_guard("same"):
        async with first._writer_connection() as connection:
            owner = await pid(connection)
            await connection.commit()
        async with first._reader_connection() as connection:
            assert await pid(connection) == owner
            await connection.commit()
        waiting = asyncio.create_task(contender())
        try:
            assert not (await asyncio.wait({waiting}, timeout=0.08))[0]
            assert not entered.is_set()
            # Different Session guards do not serialize unrelated SQL writers.
            async with second.session_guard("other"):
                pass
        finally:
            if waiting.done():
                await waiting
    await asyncio.wait_for(waiting, timeout=2)
    assert entered.is_set()


async def test_busy_archive_rejects_body_and_discards_its_connection_without_unlocking_owner(
    archives,
):
    first, second = archives
    second.lock_wait_seconds = 0.05
    async with first.session_guard("same"):
        with pytest.raises(SageV2Error) as caught:
            async with second.session_guard("same"):
                pytest.fail("busy archive entered guarded body")
        assert caught.value.info.code == "session_store.archive_busy"
        assert caught.value.info.retryable
        # Failed contenders cannot release the actual owner's advisory lock.
        with pytest.raises(SageV2Error):
            async with second.session_guard("same"):
                pytest.fail("owner lock was released by a failed contender")
    async with second.session_guard("same"):
        pass


async def test_cancelled_archive_releases_lock_and_sql_capacity(archives):
    first, second = archives
    entered = asyncio.Event()

    async def owner():
        async with first.session_guard("cancelled"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with second.session_guard("cancelled"):
        async with second._writer_connection() as connection:
            assert await pid(connection)


async def test_ambiguous_unlock_closes_connection_before_returning_pool_slot(
    archives, monkeypatch
):
    first, second = archives
    connection = None
    with pytest.raises(RuntimeError, match="unlock response lost"):
        async with first.session_guard("ambiguous"):
            async with first._writer_connection() as connection:
                original_cursor = connection.cursor

                class BrokenCursor:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        return False

                    async def execute(self, statement, params):
                        raise RuntimeError("unlock response lost")

                monkeypatch.setattr(connection, "cursor", lambda: BrokenCursor())
    assert connection.closed
    monkeypatch.setattr(connection, "cursor", original_cursor)
    async with second.session_guard("ambiguous"):
        pass
