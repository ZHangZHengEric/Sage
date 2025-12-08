"""
KdbDoc ORM 模型（异步SQLAlchemy）
"""

from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON
from sqlalchemy import select, func, update, delete

from datetime import datetime

from .base import Base, BaseDao
from typing import Optional, List


class KdbDoc(Base):
    __tablename__ = "kdb_doc"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kdb_id: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128), default="")
    doc_name: Mapped[str] = mapped_column(String(128), default="")
    data_source: Mapped[str] = mapped_column(String(52), default="common")
    source_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    meta_data: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)


class KdbDocStatus:
    PENDING = 0
    PROCESSING = 1
    SUCCESS = 2
    FAILED = 3


class KdbDocDao(BaseDao):
    async def insert(self, obj: KdbDoc) -> None:
        await BaseDao.insert(self, obj)

    async def batch_insert(self, objs: List[KdbDoc]) -> None:
        if not objs:
            return
        await BaseDao.batch_insert(self, objs)

    async def update(self, obj: KdbDoc) -> None:
        await BaseDao.save(self, obj)

    async def get_by_kdb_id(self, kdb_id: str) -> list[KdbDoc]:
        where = [KdbDoc.kdb_id == kdb_id]
        return await BaseDao.get_list(self, KdbDoc, where=where)

    async def batch_update_status(self, ids: List[str], status: int) -> None:
        if not ids:
            return
        await BaseDao.update_where(self, KdbDoc, where=[KdbDoc.id.in_(ids)], values={"status": status})

    async def update_status(self, doc_id: str, status: int) -> None:
        await BaseDao.update_where(self, KdbDoc, where=[KdbDoc.id == doc_id], values={"status": status})

    async def update_status_and_retry(self, doc_id: str, status: int) -> None:
        await BaseDao.update_where(
            self,
            KdbDoc,
            where=[KdbDoc.id == doc_id],
            values={"status": status, "retry_count": KdbDoc.retry_count + 1},
        )

    async def get_kdb_docs_paginated(
        self,
        kdb_id: str,
        query_name: str,
        status: List[int],
        query_task_id: str,
        page_no: int,
        page_size: int,
    ) -> tuple[list[KdbDoc], int]:
        """分页查询KDB文档"""
        where = [KdbDoc.kdb_id == kdb_id]
        if query_task_id:
            where.append(KdbDoc.task_id == query_task_id)
        if query_name:
            where.append(KdbDoc.doc_name.like(f"%{query_name}%"))
        if status:
            where.append(KdbDoc.status.in_(status))
        items, total = await BaseDao.paginate_list(
            self,
            KdbDoc,
            where=where,
            order_by=KdbDoc.created_at.desc(),
            page=page_no,
            page_size=page_size,
        )
        return items, total

    async def get_list_by_status_and_data_source(
        self, status: int, data_source: str, limit: int
    ) -> list[KdbDoc]:
        where = [KdbDoc.status == status, KdbDoc.data_source == data_source]
        return await BaseDao.get_list(
            self, KdbDoc, where=where, order_by=KdbDoc.created_at.asc(), limit=limit
        )

    async def get_failed_list(self, data_source: str, limit: int) -> list[KdbDoc]:
        where = [
            KdbDoc.status == KdbDocStatus.FAILED,
            KdbDoc.data_source == data_source,
            KdbDoc.retry_count < 3,
        ]
        return await BaseDao.get_list(
            self, KdbDoc, where=where, order_by=KdbDoc.created_at.asc(), limit=limit
        )

    async def get_by_id(self, data_id: int | str) -> Optional[KdbDoc]:
        return await BaseDao.get_by_id(self, KdbDoc, str(data_id))

    async def delete_by_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        await BaseDao.delete_where(self, KdbDoc, where=[KdbDoc.id.in_(ids)])

    async def get_counts_by_kdb_ids(self, kdb_ids: List[str]) -> dict[str, int]:
        if not kdb_ids:
            return {}
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = (
                select(KdbDoc.kdb_id, func.count())
                .where(KdbDoc.kdb_id.in_(kdb_ids))
                .group_by(KdbDoc.kdb_id)
            )
            res = await session.execute(stmt)
            rows = res.all()
            return {str(kdb_id): int(cnt or 0) for kdb_id, cnt in rows}
