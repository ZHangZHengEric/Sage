"""
SQLAlchemy 基础设施

"""

import asyncio
from typing import Any, Optional, Sequence, Type

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class BaseDao:
    """基础DAO类"""

    def __init__(self):
        try:
            loop = asyncio.get_running_loop()
            from core.client.db import get_global_db

            self._db_task = loop.create_task(get_global_db())
        except RuntimeError:
            self._db_task = None
        self.db = None

    async def _get_db(self):
        if self.db is not None:
            return self.db
        if self._db_task is not None:
            self.db = await self._db_task
            return self.db
        from core.client.db import get_global_db

        self.db = await get_global_db()
        return self.db

    async def insert(self, obj: Any) -> None:
        """插入对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            session.add(obj)

    async def batch_insert(self, objs: Sequence[Any]) -> None:
        """批量插入对象"""
        if not objs:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            session.add_all(list(objs))

    async def save(self, obj: Any) -> bool:
        """保存对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            await session.merge(obj)
            return True

    async def get_by_id(self, model: Type[Any], pk: Any) -> Optional[Any]:
        """根据主键查询对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            return await session.get(model, pk)

    async def delete_by_id(self, model: Type[Any], pk: Any) -> bool:
        """根据主键删除对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(model, pk)
            if obj:
                await session.delete(obj)
                return True
            return False

    async def get_all(self, model: Type[Any], order_by: Any | None = None) -> list[Any]:
        """查询所有对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(model)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_list(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        """查询对象列表"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(model)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            if limit is not None:
                stmt = stmt.limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_first(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
    ) -> Optional[Any]:
        """查询第一个对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(model)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            if order_by is not None:
                stmt = stmt.order_by(order_by)
            stmt = stmt.limit(1)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def count(self, model: Type[Any], where: Sequence[Any] | None = None) -> int:
        """查询对象数量"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(func.count()).select_from(model)
            if where:
                for cond in where:
                    stmt = stmt.where(cond)
            res = await session.execute(stmt)
            return int(res.scalar() or 0)

    async def paginate_list(
        self,
        model: Type[Any],
        where: Sequence[Any] | None = None,
        order_by: Any | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Any], int]:
        """分页查询对象列表"""
        db = await self._get_db()
        async with db.get_session() as session:
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
        """根据条件更新对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = update(model)
            for cond in where or []:
                stmt = stmt.where(cond)
            await session.execute(stmt.values(**values))

    async def delete_where(self, model: Type[Any], where: Sequence[Any]) -> None:
        """根据条件删除对象"""
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = delete(model)
            for cond in where or []:
                stmt = stmt.where(cond)
            await session.execute(stmt)
