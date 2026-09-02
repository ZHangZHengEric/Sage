from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from loguru import logger
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

T = TypeVar("T")
AfterCommitCallback = Callable[[], object]
_AFTER_COMMIT = "aiot_core_after_commit"
_TRANSIENT_MYSQL_CODES = {1205, 1213}


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = field(repr=False)
    pool_size: int = 10
    max_overflow: int = 40
    pool_timeout_seconds: int = 10
    pool_recycle_seconds: int = 1800
    sql_timing_enabled: bool = False
    sql_timing_min_ms: int = 0


class Database:
    name = "database"

    def __init__(self, settings: DatabaseSettings) -> None:
        if not str(settings.url or "").strip():
            raise ValueError("database URL is required")
        if settings.pool_size <= 0:
            raise ValueError("database pool size must be positive")
        if settings.max_overflow < 0:
            raise ValueError("database maximum overflow cannot be negative")
        if settings.pool_timeout_seconds <= 0:
            raise ValueError("database pool timeout must be positive")
        if settings.pool_recycle_seconds <= 0:
            raise ValueError("database pool recycle must be positive")
        if settings.sql_timing_min_ms < 0:
            raise ValueError("database SQL timing threshold cannot be negative")
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._sessions: Callable[[], AsyncSession] | None = None

    async def start(self) -> None:
        self._engine = create_async_engine(
            self._settings.url,
            pool_size=self._settings.pool_size,
            max_overflow=self._settings.max_overflow,
            pool_timeout=self._settings.pool_timeout_seconds,
            pool_recycle=self._settings.pool_recycle_seconds,
            pool_pre_ping=True,
            json_serializer=lambda value: json.dumps(value, ensure_ascii=False),
            json_deserializer=json.loads,
        )
        self._configure_sql_timing(self._engine)
        self._sessions = async_sessionmaker(
            self._engine,
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except BaseException:
            await self.stop()
            raise

    async def ready(self) -> bool:
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def stop(self) -> None:
        engine = self._engine
        self._sessions = None
        if engine is not None:
            await engine.dispose()
            if self._engine is engine:
                self._engine = None

    def _new_session(self) -> AsyncSession:
        if self._sessions is None:
            raise RuntimeError("database is not initialized")
        return self._sessions()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._new_session()
        try:
            yield session
        finally:
            await asyncio.shield(session.close())

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        session = self._new_session()
        callbacks: list[AfterCommitCallback] = []
        try:
            async with session.begin():
                yield session
            callbacks = list(session.info.pop(_AFTER_COMMIT, ()))
        except BaseException:
            session.info.pop(_AFTER_COMMIT, None)
            raise
        finally:
            await asyncio.shield(session.close())
        for callback in callbacks:
            try:
                result = callback()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("after-commit callback failed")

    def after_commit(
        self,
        session: AsyncSession,
        callback: AfterCommitCallback,
    ) -> None:
        session.info.setdefault(_AFTER_COMMIT, []).append(callback)

    async def run_transaction(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 0.05,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> T:
        attempts = int(max_attempts)
        if attempts <= 0:
            raise ValueError("transaction retry attempts must be positive")
        delay_base = float(base_delay_seconds)
        if delay_base < 0:
            raise ValueError("transaction retry delay cannot be negative")
        for attempt in range(1, attempts + 1):
            try:
                async with self.transaction() as session:
                    return await operation(session)
            except OperationalError as error:
                if _mysql_error_code(error) not in _TRANSIENT_MYSQL_CODES or attempt >= attempts:
                    raise
                delay = delay_base * (2 ** (attempt - 1))
                logger.warning(
                    "transaction lock conflict; retrying attempt={} delay={}",
                    attempt + 1,
                    delay,
                )
                await sleep(delay)
        raise RuntimeError("unreachable transaction retry state")

    def _configure_sql_timing(self, engine: AsyncEngine) -> None:
        if not self._settings.sql_timing_enabled:
            return
        minimum_ms = self._settings.sql_timing_min_ms

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def before_cursor_execute(
            connection: Any,
            cursor: Any,
            statement: Any,
            parameters: Any,
            context: Any,
            executemany: Any,
        ) -> None:
            connection.info.setdefault("_query_started_at", []).append(time.perf_counter())

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def after_cursor_execute(
            connection: Any,
            cursor: Any,
            statement: Any,
            parameters: Any,
            context: Any,
            executemany: Any,
        ) -> None:
            started = connection.info.get("_query_started_at", [])
            if not started:
                return
            elapsed_ms = int((time.perf_counter() - started.pop()) * 1000)
            if elapsed_ms >= minimum_ms:
                logger.bind(flow="database").info(
                    "sql elapsed_ms={} executemany={} statement={}",
                    elapsed_ms,
                    bool(executemany),
                    " ".join(str(statement).split()),
                )


def _mysql_error_code(error: OperationalError) -> int | None:
    original = getattr(error, "orig", None)
    args = getattr(original, "args", ())
    if not args:
        return None
    try:
        return int(args[0])
    except (TypeError, ValueError):
        return None
