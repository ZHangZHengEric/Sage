"""Real MySQL connections are bounded without starving writes or leaking waits.

The existing loading and metadata suites cover data/query contracts. These cases
hold real connections to expose unbounded fan-out, admission cancellation, and
the legacy owner fallback that previously acquired a nested reader connection.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from anyio import CancelScope

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState, _SCHEMA_TABLES
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.official import builtin_extension_registry


@asynccontextmanager
async def mysql_store(**options):
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN", "").strip()
    if not dsn:
        pytest.skip("set SAGE_V2_TEST_MYSQL_DSN for real connection budget tests")
    store = _MysqlSessionState(
        dsn, table_prefix="budget_" + uuid4().hex[:10], **options
    )
    try:
        await store._ensure_ready()
        yield store
    finally:
        if store._pool is not None:
            async with store._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for table in reversed(_SCHEMA_TABLES):
                        await cursor.execute(f"DROP TABLE IF EXISTS {store._table(table)}")
                await connection.commit()
        await store.close()


async def connection_id(connection):
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT CONNECTION_ID()")
        return (await cursor.fetchone())[0]


async def waiting_connection(store, kind, attempted, completed):
    attempted.set()
    lease = store._reader_connection if kind == "reader" else store._writer_connection
    async with lease() as connection:
        completed.append(await connection_id(connection))


async def assert_waiting(task):
    # A real negative wait establishes that the operation reached admission and
    # remains blocked; the timeout does not cancel the operation under test.
    done, _ = await asyncio.wait({task}, timeout=0.05)
    if done:
        await task
        pytest.fail("connection acquisition bypassed the occupied budget")


def assert_busy(error):
    assert error.info.code == "session_store.mysql_busy"
    assert error.info.category == ErrorCategory.RATE_LIMITED
    assert error.info.retryable and error.info.safe_to_resume


@pytest.mark.parametrize(
    "options",
    [
        {"max_connections": 1},
        {"max_connections": 0},
        {"max_pending_connections": 0},
        {"connection_acquire_timeout_seconds": 0},
        {"connection_acquire_timeout_seconds": -1},
    ],
)
def test_connection_budget_rejects_invalid_parameters(options):
    with pytest.raises(ValueError):
        _MysqlSessionState("mysql://unused/test", **options)


@pytest.mark.parametrize("plugin", ["sage.session.mysql", "sage.session.redis-mysql"])
def test_registered_connection_budget_reaches_the_actual_mysql_pool(plugin):
    config = {"dsn": "mysql://unused/test", "max_connections": 3,
              "max_pending_connections": 7, "connection_acquire_timeout_seconds": 0.25}
    if plugin.endswith("redis-mysql"):
        config["redis_url"] = "redis://unused/0"
    registration = builtin_extension_registry().get(plugin)
    validated = registration.config_model.model_validate(config).model_dump(exclude_unset=True)
    store = registration.factory(ExtensionScopeContext(
        scope=ExtensionScope.PROCESS, scope_id="budget", config=validated,
    ), {})
    budget = (store._archive if plugin.endswith("redis-mysql") else store)._connection_budget
    assert budget.max_connections == 3
    assert budget.max_pending_connections == 7
    assert budget.connection_acquire_timeout_seconds == 0.25


async def test_readers_leave_writer_capacity_and_never_exceed_physical_budget():
    async with mysql_store(max_connections=3) as store:
        attempted, completed = asyncio.Event(), []
        async with store._reader_connection() as first:
            async with store._reader_connection() as second:
                reader_ids = {await connection_id(first), await connection_id(second)}
                assert len(reader_ids) == 2
                waiter = asyncio.create_task(
                    waiting_connection(store, "reader", attempted, completed)
                )
                try:
                    await attempted.wait()
                    await assert_waiting(waiter)
                    async with asyncio.timeout(1):
                        async with store._writer_connection() as writer:
                            assert await connection_id(writer) not in reader_ids
                    assert not completed
                    # Pool size includes idle and leased physical connections.
                    assert store._pool.size == 3
                finally:
                    waiter.cancel()
                    with suppress(asyncio.CancelledError):
                        await waiter
        async with store._reader_connection() as connection:
            assert await connection_id(connection)
        assert store._pool.size <= 3


async def test_acquisition_deadline_does_not_cancel_an_admitted_transaction():
    async with mysql_store(connection_acquire_timeout_seconds=0.02) as store:
        entered, finish = asyncio.Event(), asyncio.Event()

        async def transaction():
            async with store._writer_connection() as connection:
                entered.set()
                await finish.wait()
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    assert await cursor.fetchone() == (1,)
                await connection.commit()

        task = asyncio.create_task(transaction())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await assert_waiting(task)  # Longer than the acquisition deadline.
            finish.set()
            await asyncio.wait_for(task, 1)
        finally:
            finish.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def test_full_pending_queue_rejects_before_dispatch_and_recovers():
    async with mysql_store(
        max_connections=2,
        max_pending_connections=1,
        connection_acquire_timeout_seconds=2,
    ) as store:
        attempted, completed = asyncio.Event(), []
        async with store._reader_connection():
            waiter = asyncio.create_task(
                waiting_connection(store, "reader", attempted, completed)
            )
            try:
                await attempted.wait()
                await assert_waiting(waiter)
                # A saturated read queue cannot consume the reserved write slot.
                async with asyncio.timeout(0.5):
                    async with store._writer_connection() as connection:
                        assert await connection_id(connection)
                async with asyncio.timeout(0.5):
                    with pytest.raises(SageV2Error) as caught:
                        async with store._reader_connection():
                            pytest.fail("rejected reader dispatched")
                assert_busy(caught.value)
                assert not completed
            finally:
                waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiter
        async with store._reader_connection() as connection:
            assert await connection_id(connection)


@pytest.mark.parametrize("finish", ["deadline", "cancel"])
@pytest.mark.parametrize("kind", ["reader", "writer"])
async def test_pending_deadline_or_cancellation_returns_admission_capacity(finish, kind):
    async with mysql_store(
        max_connections=2,
        max_pending_connections=1,
        connection_acquire_timeout_seconds=0.15 if finish == "deadline" else 2,
    ) as store:
        attempted, completed = asyncio.Event(), []
        async with AsyncExitStack() as held:
            lease = store._reader_connection if kind == "reader" else store._writer_connection
            for _ in range(1 if kind == "reader" else 2):
                await held.enter_async_context(lease())
            waiter = asyncio.create_task(
                waiting_connection(store, kind, attempted, completed)
            )
            try:
                await attempted.wait()
                await assert_waiting(waiter)
                assert store._pool.size <= 2
                if finish == "cancel":
                    waiter.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiter
                else:
                    with pytest.raises(SageV2Error) as caught:
                        await asyncio.wait_for(waiter, 1)
                    assert_busy(caught.value)
                assert not completed
            finally:
                if not waiter.done():
                    waiter.cancel()
                    with suppress(asyncio.CancelledError):
                        await waiter
            # A fresh request must be admitted to the queue while the same
            # reader still holds its slot, proving no pending count leaked.
            replacement_attempted = asyncio.Event()
            replacement = asyncio.create_task(
                waiting_connection(store, kind, replacement_attempted, completed)
            )
            try:
                await replacement_attempted.wait()
                await assert_waiting(replacement)
            except BaseException:
                replacement.cancel()
                with suppress(asyncio.CancelledError):
                    await replacement
                raise
        await asyncio.wait_for(replacement, 1)
        assert len(completed) == 1
        assert store._pool.size <= 2


@pytest.mark.parametrize("cancellation", ["asyncio", "anyio"])
async def test_cancelled_reader_keeps_capacity_until_real_rollback_finishes(cancellation):
    async with mysql_store(max_connections=2) as store:
        entered, rollback_started, finish_rollback = asyncio.Event(), asyncio.Event(), asyncio.Event()
        scopes = []

        async def reader():
            with CancelScope() as scope:
                scopes.append(scope)
                async with store._reader_connection() as connection:
                    rollback = connection.rollback

                    async def delayed_rollback():
                        rollback_started.set()
                        try:
                            await finish_rollback.wait()
                            await rollback()
                        finally:
                            connection.rollback = rollback

                    connection.rollback = delayed_rollback
                    entered.set()
                    await asyncio.Event().wait()

        task = asyncio.create_task(reader())
        replacement = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if cancellation == "asyncio":
                task.cancel()
            else:
                scopes[0].cancel()
            await asyncio.wait_for(rollback_started.wait(), 1)
            if cancellation == "asyncio":
                task.cancel()
                task.cancel()
            await assert_waiting(task)
            attempted, completed = asyncio.Event(), []
            replacement = asyncio.create_task(waiting_connection(store, "reader", attempted, completed))
            await attempted.wait()
            await assert_waiting(replacement)
            assert not completed
            finish_rollback.set()
            if cancellation == "asyncio":
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            else:
                await asyncio.wait_for(task, 1)
            await asyncio.wait_for(replacement, 1)
            assert len(completed) == 1
            assert store._pool.size <= 2
        finally:
            finish_rollback.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if replacement is not None:
                replacement.cancel()
                with suppress(asyncio.CancelledError):
                    await replacement


async def test_legacy_metadata_owner_uses_one_reader_without_history_install_or_access_leak():
    async with mysql_store(
        max_connections=2, connection_acquire_timeout_seconds=0.2
    ) as store:
        owner = RequestContext(
            actor=ActorRef(principal_id="owner", principal_type="user", tenant_id="tenant")
        )
        stranger = owner.model_copy(
            update={"actor": owner.actor.model_copy(update={"principal_id": "stranger"})}
        )
        result = await store.create_run(
            StartRun(
                agent_id="agent", session_id="legacy", input=(),
                resolved_spec_hash="sha256:spec", idempotency_key="legacy",
            ),
            owner,
        )
        async with store._writer_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"UPDATE {store._table('sessions')} SET compact_state=JSON_SET("
                    "compact_state,'$.sessions[0].owner',CAST('null' AS JSON),"
                    "'$.runs[0].request_context',CAST('null' AS JSON)) WHERE session_id=%s",
                    ("legacy",),
                )
            await connection.commit()
        store._evict_session_locked("legacy")
        store._fetch_session = AsyncMock(side_effect=AssertionError("full aggregate fetched"))
        async with asyncio.timeout(1):
            rows = await store.authorized_run_metadata_page(["legacy"], owner, agent_id="agent")
            assert [row.run_id for row in rows] == [result.handle.run_id]
            assert not await store.authorized_run_metadata_page(["legacy"], stranger)
        assert not store._sessions and not store._runs
        assert store._pool.size <= 2
