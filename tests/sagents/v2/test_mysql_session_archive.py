import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from sagents.v2.runtime.session.mysql_archive import MysqlSessionArchive
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.contracts.run_state import RunState
from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT


async def payload():
    source = SessionStoreCoordinator()
    created = await source.create_run(command(), CONTEXT)
    await source.commit_run(run_id=created.handle.run_id, expected_revision=0,
        expected_states={RunState.QUEUED}, new_state=RunState.CANCELLED,
        drafts=(), context=CONTEXT, idempotency_key="cancel")
    return source._dump_session_state_locked(created.handle.session_id)


def archive(previous=None, offsets=()):
    cursor = AsyncMock()
    cursor.fetchone.return_value = previous
    cursor.fetchall.return_value = offsets
    connection = AsyncMock()
    connection.cursor = MagicMock()
    connection.cursor.return_value.__aenter__.return_value = cursor
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection
    value = MysqlSessionArchive("mysql://unused/test")
    value._pool = Pool()
    return value, connection, cursor


@pytest.mark.asyncio
async def test_archive_publishes_complete_recoverable_state_in_one_transaction():
    state = await payload()
    value, connection, cursor = archive()
    await value.archive_session(state, {"image": b"\x00\xff"})
    params = next(call.args[1] for call in cursor.execute.await_args_list if "INSERT INTO `sagent_sessions`" in call.args[0])
    saved = json.loads(params[-1])
    assert saved["runs"] == state["runs"]
    assert saved["command_results"] == state["command_results"]
    assert saved["sessions"] == state["sessions"]
    assert "run_events" not in saved
    assert any("UNHEX" in call.args[0] and call.args[1][-1] == "00ff" for call in cursor.execute.await_args_list)
    connection.commit.assert_awaited_once()
    connection.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("ahead", [0, 1])
async def test_retry_or_old_snapshot_cannot_replace_archived_revision(ahead):
    state = await payload()
    revision = state["sessions"][0]["revision"]
    value, connection, cursor = archive((revision + ahead,))
    await value.archive_session(state, {})
    assert len(cursor.execute.await_args_list) == 1
    connection.commit.assert_not_awaited()
    connection.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_archive_does_not_reinsert_already_archived_events():
    state = await payload()
    rid, events = next(iter(state["run_events"].items()))
    value, connection, cursor = archive((0,), ((rid, len(events)),))
    await value.archive_session(state, {})
    assert not any("run_events" in call.args[0] for call in cursor.executemany.await_args_list)
    connection.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sql_failure_rolls_back_entire_archive():
    value, connection, cursor = archive()
    cursor.execute.side_effect = OSError("database offline")
    with pytest.raises(OSError):
        await value.archive_session(await payload(), {})
    connection.commit.assert_not_awaited()
    connection.rollback.assert_awaited_once()
