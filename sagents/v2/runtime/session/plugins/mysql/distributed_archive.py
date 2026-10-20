"""Connection-scoped archive serialization without extra business tables."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import hashlib

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from .archive import MysqlSessionArchive


class DistributedMysqlSessionArchive(MysqlSessionArchive):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._archive_connection = ContextVar("distributed_mysql_archive_connection", default=None)

    def _pinned_connection(self):
        value = self._archive_connection.get()
        return value[1] if value is not None and value[0] is asyncio.current_task() else None

    @asynccontextmanager
    async def _writer_connection(self):
        connection = self._pinned_connection()
        if connection is not None:
            yield connection
        else:
            async with super()._writer_connection() as connection:
                yield connection

    @asynccontextmanager
    async def _reader_connection(self):
        connection = self._pinned_connection()
        if connection is not None:
            yield connection
        else:
            async with super()._reader_connection() as connection:
                yield connection

    @asynccontextmanager
    async def session_guard(self, session_id):
        identity = f"{self._connect_kwargs['db']}\0{self.table_prefix}\0{session_id}"
        lock_name = "sage_archive_" + hashlib.sha256(identity.encode()).hexdigest()[:48]
        # Keep the SQL lock across all baseline/batch/delete transactions. A
        # Redis guard alone can expire while an old archive is paused in SQL.
        async with super()._writer_connection() as connection:
            try:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT GET_LOCK(%s, 5)", (lock_name,))
                    row = await cursor.fetchone()
                if row is None or row[0] != 1:
                    raise SageV2Error(RuntimeErrorInfo(code="session_store.archive_busy",
                        category=ErrorCategory.CONFLICT, message="Session archive is busy; retry later",
                        retryable=True, safe_to_resume=True))
            except BaseException:
                # Includes an ambiguous GET_LOCK response: never return a
                # possibly locked connection to the shared pool.
                connection.close()
                raise
            token = self._archive_connection.set((asyncio.current_task(), connection))
            try:
                yield
            finally:
                self._archive_connection.reset(token)
                try:
                    await connection.rollback()
                    async with connection.cursor() as cursor:
                        await cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                        row = await cursor.fetchone()
                    if row is None or row[0] != 1:
                        connection.close()
                except BaseException:
                    connection.close()
                    raise
