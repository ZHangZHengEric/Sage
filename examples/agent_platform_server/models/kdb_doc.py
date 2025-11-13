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
        db = await self._get_db()
        async with db.get_session() as session:
            await session.add(obj)

    async def batch_insert(self, objs: List[KdbDoc]) -> None:
        if not objs:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            session.add_all(objs)

    async def get_by_kdb_id(self, kdb_id: str) -> list[KdbDoc]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(KdbDoc).where(KdbDoc.kdb_id == kdb_id)
            return list((await session.execute(stmt)).scalars().all())

    async def batch_update_status(self, ids: List[str], status: int) -> None:
        if not ids:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(
                update(KdbDoc).where(KdbDoc.id.in_(ids)).values(status=status)
            )

    async def update_status(self, doc_id: str, status: int) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(
                update(KdbDoc).where(KdbDoc.id == doc_id).values(status=status)
            )

    async def update_status_and_retry(self, doc_id: str, status: int) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(
                update(KdbDoc)
                .where(KdbDoc.id == doc_id)
                .values(status=status, retry_count=KdbDoc.retry_count + 1)
            )

    async def get_list(
        self,
        kdb_id: str,
        query_name: str,
        status: List[int],
        query_task_id: str,
        page_no: int,
        page_size: int,
    ) -> tuple[list[KdbDoc], int]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(KdbDoc).where(KdbDoc.kdb_id == kdb_id)
            if query_task_id:
                stmt = stmt.where(KdbDoc.task_id == query_task_id)
            if query_name:
                stmt = stmt.where(KdbDoc.doc_name.like(f"%{query_name}%"))
            if status:
                stmt = stmt.where(KdbDoc.status.in_(status))
            count_stmt = select(func.count()).select_from(stmt.subquery())
            cnt = (await session.execute(count_stmt)).scalar() or 0
            stmt = (
                stmt.offset((page_no - 1) * page_size)
                .limit(page_size)
                .order_by(KdbDoc.created_at.desc())
            )
            res = (await session.execute(stmt)).scalars().all()
            return list(res), int(cnt)

    async def get_list_by_status_and_data_source(
        self, status: int, data_source: str, limit: int
    ) -> list[KdbDoc]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = (
                select(KdbDoc)
                .where(KdbDoc.status == status)
                .where(KdbDoc.data_source == data_source)
                .limit(limit)
                .order_by(KdbDoc.created_at.asc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def get_failed_list(self, data_source: str, limit: int) -> list[KdbDoc]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = (
                select(KdbDoc)
                .where(KdbDoc.status == KdbDocStatus.FAILED)
                .where(KdbDoc.data_source == data_source)
                .where(KdbDoc.retry_count < 3)
                .limit(limit)
                .order_by(KdbDoc.created_at.asc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def get_by_id(self, data_id: int | str) -> Optional[KdbDoc]:
        db = await self._get_db()
        async with db.get_session() as session:
            return await session.get(KdbDoc, str(data_id))

    async def delete_by_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(delete(KdbDoc).where(KdbDoc.id.in_(ids)))
