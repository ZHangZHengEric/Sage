"""External SQL connection contracts for archive ownership across commits.

Redis ownership can expire while an archive is paused in MySQL. A named MySQL
lock must remain on the same physical connection across all Session writes,
and an uncertain lock release must never return that connection to the pool.
"""

import asyncio
from contextlib import asynccontextmanager
import re

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.mysql.distributed_archive import DistributedMysqlSessionArchive


class Connection:
    def __init__(self, *, acquire_result=1, release_result=1, release_error=None):
        self.acquire_result = acquire_result
        self.release_result = release_result
        self.release_error = release_error
        self.held = False
        self.closed = False
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def cursor(self):
        connection = self

        class Cursor:
            row = None

            async def execute(self, statement, params=()):
                connection.statements.append((statement, params))
                if "GET_LOCK(" in statement.upper():
                    connection.held = connection.acquire_result == 1
                    self.row = (connection.acquire_result,)
                elif "RELEASE_LOCK(" in statement.upper():
                    if connection.release_error is not None:
                        raise connection.release_error
                    if connection.release_result == 1:
                        connection.held = False
                    self.row = (connection.release_result,)
                else:
                    self.row = (1,)

            async def fetchone(self):
                return self.row

        yield Cursor()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True
        self.held = False


class Pool:
    def __init__(self, connection):
        self.connection = connection
        self.acquisitions = 0
        self.releases = []

    @asynccontextmanager
    async def acquire(self):
        self.acquisitions += 1
        try:
            yield self.connection
        finally:
            self.releases.append((self.connection.held, self.connection.closed))


def archive(connection=None, *, table_prefix="archive_guard", database="test"):
    connection = connection or Connection()
    value = DistributedMysqlSessionArchive(
        f"mysql://unused/{database}", table_prefix=table_prefix)
    value._pool = Pool(connection)
    return value, connection


def lock_statements(connection, operation):
    return [(statement, params) for statement, params in connection.statements
            if operation in statement.upper()]


@pytest.mark.asyncio
async def test_guard_reuses_one_physical_connection_and_keeps_mysql_lock_across_commits():
    value, connection = archive()
    async with value.session_guard("session-one"):
        assert connection.held
        for _ in range(2):
            async with value._writer_connection() as writer:
                assert writer is connection
                assert writer.held
                await writer.commit()
            assert connection.held, "commit must not release the Session's named lock"
        async with value._reader_connection() as reader:
            assert reader is connection
            async with reader.cursor() as cursor:
                await cursor.execute("SELECT 1")
                assert await cursor.fetchone() == (1,)
        assert connection.held
        assert value._pool.acquisitions == 1
        assert not lock_statements(connection, "RELEASE_LOCK(")
    acquired, = lock_statements(connection, "GET_LOCK(")
    released, = lock_statements(connection, "RELEASE_LOCK(")
    if len(acquired[1]) == 2:
        assert acquired[1][1] == 5
    else:
        assert re.search(r"GET_LOCK\s*\(\s*%s\s*,\s*5\s*\)", acquired[0], re.IGNORECASE)
    assert released[1][0] == acquired[1][0]
    assert connection.commits == 2
    assert not connection.held
    assert value._pool.releases == [(False, False)]


@pytest.mark.asyncio
async def test_lock_identity_is_stable_and_scoped_by_database_prefix_and_session():
    identities = []
    for database, prefix, session_id in (
        ("test", "same", "session-one"),
        ("test", "same", "session-one"),
        ("test", "other", "session-one"),
        ("other_database", "same", "session-one"),
        ("test", "same", "session-two"),
        ("test", "same", "超长会话" * 100),
    ):
        value, connection = archive(table_prefix=prefix, database=database)
        async with value.session_guard(session_id):
            pass
        acquired, = lock_statements(connection, "GET_LOCK(")
        name = acquired[1][0]
        assert isinstance(name, str) and 0 < len(name.encode()) <= 64
        identities.append(name)
    assert identities[0] == identities[1]
    assert len(set(identities[1:])) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [0, None], ids=["busy", "unavailable"])
async def test_unacquired_mysql_guard_rejects_body_and_returns_connection(result):
    value, connection = archive(Connection(acquire_result=result))
    entered = False
    with pytest.raises(SageV2Error) as busy:
        async with value.session_guard("session-one"):
            entered = True
    assert busy.value.info.code == "session_store.archive_busy"
    assert not entered
    assert not connection.held
    assert len(value._pool.releases) == 1


@pytest.mark.asyncio
async def test_guard_releases_the_mysql_lock_when_archive_body_raises():
    value, connection = archive()
    with pytest.raises(ValueError, match="archive interrupted"):
        async with value.session_guard("session-one"):
            assert connection.held
            raise ValueError("archive interrupted")
    assert len(lock_statements(connection, "RELEASE_LOCK(")) == 1
    assert value._pool.releases == [(False, False)]


@pytest.mark.asyncio
async def test_guard_releases_the_mysql_lock_when_the_archiving_task_is_cancelled():
    value, connection = archive()
    entered = asyncio.Event()

    async def archiving():
        async with value.session_guard("session-one"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(archiving())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert len(lock_statements(connection, "RELEASE_LOCK(")) == 1
    assert value._pool.releases == [(False, False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("result,error", [(0, None), (None, None), (1, OSError("connection lost"))],
                         ids=["not-released", "unknown-owner", "transport-error"])
async def test_uncertain_mysql_unlock_closes_connection_before_returning_it_to_pool(result, error):
    value, connection = archive(Connection(release_result=result, release_error=error))
    entered = False
    try:
        async with value.session_guard("session-one"):
            entered = True
            assert connection.held
    except (OSError, SageV2Error):
        pass
    assert entered
    assert connection.closed, "a pooled connection with uncertain named-lock ownership must be discarded"
    assert value._pool.releases == [(False, True)]
