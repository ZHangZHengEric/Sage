"""Session advisory locks serialize archival across SQL transaction boundaries."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import time
import hashlib

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from .archive import PostgresSessionArchive
from .connections import finish_cleanup

_LOCK_ID = (
    "hashtextextended(current_database() || ':' || current_schema() || ':' || %s, 0)"
)


class DistributedPostgresSessionArchive(PostgresSessionArchive):
    lock_wait_seconds = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._archive_connection = ContextVar(
            "distributed_postgres_archive_connection", default=None
        )

    def _pinned_connection(self):
        value = self._archive_connection.get()
        return (
            value[1]
            if value is not None and value[0] is asyncio.current_task()
            else None
        )

    @asynccontextmanager
    async def _writer_connection(self):
        pinned = self._pinned_connection()
        if pinned is not None:
            yield pinned
        else:
            async with super()._writer_connection() as connection:
                yield connection

    @asynccontextmanager
    async def _reader_connection(self):
        pinned = self._pinned_connection()
        if pinned is not None:
            yield pinned
        else:
            async with super()._reader_connection() as connection:
                yield connection

    @asynccontextmanager
    async def session_guard(self, session_id):
        identity = hashlib.sha256(
            (self.table_prefix + "\0" + session_id).encode()
        ).hexdigest()
        # PostgreSQL session locks survive commits; xact locks cannot protect an
        # entire incremental archive. Close on any ambiguous acquire/release.
        # https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS
        async with super()._writer_connection() as connection:
            try:
                deadline = time.monotonic() + self.lock_wait_seconds
                while True:
                    async with connection.cursor() as cursor:
                        await cursor.execute(
                            f"SELECT pg_try_advisory_lock({_LOCK_ID})", (identity,)
                        )
                        row = await cursor.fetchone()
                    # A waiting lock attempt must not pin an old repeatable-read
                    # snapshot after the preceding owner publishes new revisions.
                    await connection.rollback()
                    if row is not None and row[0] is True:
                        break
                    if time.monotonic() >= deadline:
                        raise SageV2Error(
                            RuntimeErrorInfo(
                                code="session_store.archive_busy",
                                category=ErrorCategory.CONFLICT,
                                message="Session archive is busy; retry later",
                                retryable=True,
                                safe_to_resume=True,
                            )
                        )
                    await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
            except BaseException:
                await finish_cleanup(connection.close())
                raise
            token = self._archive_connection.set((asyncio.current_task(), connection))
            try:
                yield
            finally:
                self._archive_connection.reset(token)

                async def release():
                    try:
                        await connection.rollback()
                        async with connection.cursor() as cursor:
                            await cursor.execute(
                                f"SELECT pg_advisory_unlock({_LOCK_ID})", (identity,)
                            )
                            row = await cursor.fetchone()
                        if row is None or row[0] is not True:
                            await connection.close()
                    except BaseException:
                        await connection.close()
                        raise

                await finish_cleanup(release())
