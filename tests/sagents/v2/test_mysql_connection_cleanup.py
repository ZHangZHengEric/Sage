"""Connection cleanup must preserve cancellation during server shutdown."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import aiomysql
from pymysql.err import InterfaceError

from sagents.v2.runtime.session.plugins.mysql.connections import MysqlConnectionBudget


def connection_pool(connection=None, *, rollback_error=None, release_error=None):
    if connection is None:
        connection = SimpleNamespace(
            closed=False, rollback=AsyncMock(side_effect=rollback_error), close=Mock(),
        )
    lease = MagicMock()
    lease.__aenter__ = AsyncMock(return_value=connection)
    lease.__aexit__ = AsyncMock(return_value=False, side_effect=release_error)
    pool = SimpleNamespace(acquire=Mock(return_value=lease))
    return connection, lease, AsyncMock(return_value=pool)


@pytest.mark.parametrize("reader", [True, False])
async def test_cancelled_query_releases_closed_connection_without_rollback(reader):
    # Use the real driver with a transport double and a pending packet read.
    # This exercises aiomysql's query cancellation and socket closure directly.
    connection = aiomysql.Connection(loop=asyncio.get_running_loop())
    setattr(connection, '_reader', asyncio.StreamReader())
    connection._writer = Mock()
    connection.rollback = AsyncMock(wraps=connection.rollback)
    _, lease, ready_pool = connection_pool(connection)
    budget = MysqlConnectionBudget(max_connections=2)
    entered = asyncio.Event()

    async def query():
        async with budget.connection(ready_pool, reader=reader):
            entered.set()
            await connection.query("SELECT 1")

    task = asyncio.create_task(query())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert connection.closed
    connection.rollback.assert_not_awaited()
    lease.__aexit__.assert_awaited_once()
    # A new reader can be admitted: neither physical nor read capacity leaked.
    replacement, _, ready_replacement = connection_pool()
    _, _, ready_writer = connection_pool()
    async with asyncio.timeout(1):
        async with budget.connection(ready_replacement, reader=True) as acquired:
            assert acquired is replacement
            async with budget.connection(ready_writer, reader=False):
                pass


@pytest.mark.parametrize("stage", ["rollback", "release"])
async def test_cleanup_failure_does_not_replace_inflight_cancellation(stage):
    failure = InterfaceError("cleanup failed")
    connection, lease, ready_pool = connection_pool(**{f"{stage}_error": failure})
    budget = MysqlConnectionBudget(max_connections=2)
    cancellation = asyncio.CancelledError("server shutdown")

    with pytest.raises(asyncio.CancelledError) as caught:
        async with budget.connection(ready_pool, reader=True):
            raise cancellation

    assert caught.value is cancellation
    assert any("cleanup failed" in note for note in cancellation.__notes__)
    lease.__aexit__.assert_awaited_once()
    if stage == "rollback":
        connection.close.assert_called_once()


@pytest.mark.parametrize("stage", ["rollback", "release"])
async def test_cleanup_failure_without_cancellation_remains_visible(stage):
    failure = InterfaceError("cleanup failed")
    _, lease, ready_pool = connection_pool(**{f"{stage}_error": failure})
    budget = MysqlConnectionBudget(max_connections=2)

    with pytest.raises(InterfaceError) as caught:
        async with budget.connection(ready_pool, reader=True):
            pass

    assert caught.value is failure
    lease.__aexit__.assert_awaited_once()
