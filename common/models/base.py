"""SQLAlchemy 基础设施（共享给 server 和 desktop）"""

from __future__ import annotations

import asyncio
from datetime import datetime
from functools import wraps
from typing import Any, Optional, Sequence, Type

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import DeclarativeBase

from common.core.client.db import get_global_db


def get_local_now() -> datetime:
    """返回当前本地时间（naive datetime）。"""
    return datetime.now().astimezone().replace(tzinfo=None)


def db_retry(max_retries: int = 3, delay: float = 1.0):
    """数据库操作重试装饰器（通用版）。

    - 捕获 OperationalError / InterfaceError，按次数重试；
    - 重试耗尽后记录错误并抛出 RuntimeError（由上层转换为 HTTP 异常）。
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_err: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (OperationalError, InterfaceError) as e:  # type: ignore[misc]
                    last_err = e
                    logger.warning(
                        f"数据库操作异常 (尝试 {attempt + 1}/{max_retries}): {e}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)

            logger.error(f"数据库操作最终失败: {last_err}")
            raise RuntimeError(f"数据库操作失败: {last_err}")

        return wrapper

    return decorator


class Base(DeclarativeBase):
    """共享 Declarative 基类。"""

    pass


class BaseDao:
    """基础 DAO 类：所有 ORM DAO 共用。"""

    def __init__(self) -> None:
        self.db = None

    async def _get_db(self):
        """获取当前应用注入的全局 DB 客户端。"""
        if self.db is not None:
            return self.db
        self.db = await get_global_db()
        return self.db

    async def insert(self, obj: Any) -> None:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            session.add(obj)

    async def batch_insert(self, objs: Sequence[Any]) -> None:
        if not objs:
            return
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            session.add_all(list(objs))

    async def save(self, obj: Any) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            await session.merge(obj)
            return True

    @db_retry()
    async def get_by_id(self, model: Type[Any], pk: Any) -> Optional[Any]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            return await session.get(model, pk)

    async def delete_by_id(self, model: Type[Any], pk: Any) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            obj = await session.get(model, pk)
            if obj:
                await session.delete(obj)
                return True
            return False

    @db_retry()
    async def get_all(
        self,
        model: Type[Any],
        order_by: Any | None = None,
        options: Sequence[Any] | None = None,
    ) -> list[Any]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(model)
            if options:
                for opt in options:
                    stmt = stmt.options(opt)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    @db_retry()
    async def get_list(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
        limit: int | None = None,
        options: Sequence[Any] | None = None,
    ) -> list[Any]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(model)
            if options:
                for opt in options:
                    stmt = stmt.options(opt)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            if limit is not None:
                stmt = stmt.limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    @db_retry()
    async def get_first(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
        options: Sequence[Any] | None = None,
    ) -> Optional[Any]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(model)
            if options:
                for opt in options:
                    stmt = stmt.options(opt)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            stmt = stmt.limit(1)
            res = await session.execute(stmt)
            return res.scalars().first()

    @db_retry()
    async def count(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
    ) -> int:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(func.count()).select_from(model)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            res = await session.execute(stmt)
            return int(res.scalar() or 0)

    @db_retry()
    async def paginate_list(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Any], int]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            base_stmt = select(model)
            if where:
                for cond in where:
                    base_stmt = base_stmt.where(cond)
            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            total = int((await session.execute(count_stmt)).scalar() or 0)
            if order_by is not None:
                base_stmt = base_stmt.order_by(order_by)
            base_stmt = base_stmt.offset((page - 1) * page_size).limit(page_size)
            res = await session.execute(base_stmt)
            return list(res.scalars().all()), total

    async def update_where(
        self,
        model: Type[Any],
        where: Sequence[Any],
        values: dict,
    ) -> None:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = update(model)
            for cond in where or []:
                stmt = stmt.where(cond)
            await session.execute(stmt.values(**values))

    async def delete_where(self, model: Type[Any], where: Sequence[Any]) -> None:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = delete(model)
            for cond in where or []:
                stmt = stmt.where(cond)
            await session.execute(stmt)
