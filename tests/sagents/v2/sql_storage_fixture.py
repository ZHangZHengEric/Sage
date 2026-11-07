"""Identical public business contracts for both SQL dialects and Redis modes."""

import asyncio
from contextlib import asynccontextmanager
import os
from uuid import uuid4
from unittest.mock import AsyncMock

import fakeredis
import fakeredis.aioredis
import pytest


@asynccontextmanager
async def sql_store_factory(mode):
    from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
    from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore
    from sagents.v2.runtime.session.plugins.mysql.archive import MysqlSessionArchive
    from sagents.v2.runtime.session.plugins.postgres import PostgresSessionStore
    from sagents.v2.runtime.session.plugins.postgres.redis import (
        RedisPostgresSessionStore,
    )
    from sagents.v2.runtime.session.plugins.postgres.archive import (
        PostgresSessionArchive,
    )

    backend = mode.removeprefix("redis-")
    dsn = os.environ.get("SAGE_V2_TEST_" + backend.upper() + "_DSN")
    if not dsn:
        pytest.skip("set SQL backend test DSN for live business parity contracts")
    prefix = "business_" + uuid4().hex[:12]
    factories = {
        "mysql": MysqlSessionStore,
        "postgres": PostgresSessionStore,
        "redis-mysql": RedisMysqlSessionStore,
        "redis-postgres": RedisPostgresSessionStore,
    }
    opened = []
    server = fakeredis.FakeServer()

    def reopen():
        options = {"table_prefix": prefix}
        if mode.startswith("redis-"):
            options.update(
                redis_url="redis://business-test/0", archive_interval_seconds=3600
            )
        store = factories[mode](dsn, **options)
        if mode.startswith("redis-"):
            client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
            client.info = AsyncMock(
                return_value={"maxmemory_policy": "noeviction", "aof_enabled": 1}
            )
            store._redis = client

            async def idle():
                await asyncio.Event().wait()

            store._archive_loop = idle
        opened.append(store)
        return store

    try:
        yield reopen
    finally:
        for store in reversed(opened):
            await store.close()
        cleanup_type = (
            PostgresSessionArchive if backend == "postgres" else MysqlSessionArchive
        )
        cleanup = cleanup_type(dsn, table_prefix=prefix)
        try:
            async with cleanup._writer_connection() as connection:
                async with connection.cursor() as cursor:
                    for name in (
                        "attachments",
                        "derived_state",
                        "start_idempotency",
                        "locations",
                        "run_events",
                        "session_mutations",
                        "sessions",
                    ):
                        await cursor.execute(
                            f"DROP TABLE IF EXISTS {cleanup._table(name)}"
                        )
                await connection.commit()
        finally:
            await cleanup.close()
