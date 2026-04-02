"""Kdb + KdbDoc ORM/DAO (shared)."""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Boolean, or_, select, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class Kdb(Base):
    __tablename__ = "kdb"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    intro: Mapped[str] = mapped_column(String(1024), default="")
    setting: Mapped[dict] = mapped_column(JSON, default=dict)
    data_type: Mapped[str] = mapped_column(String(52), default="file")
    user_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(default=get_local_now)
    updated_at: Mapped[datetime] = mapped_column(default=get_local_now)

    def __init__(
        self,
        id: str,
        name: str,
        intro: str,
        setting: dict,
        data_type: str,
        user_id: str,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.intro = intro
        self.setting = setting
        self.data_type = data_type
        self.user_id = user_id
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()

    def get_index_name(self) -> str:
        """获取KDB索引名称"""
        h = hashlib.sha1(self.id.encode()).hexdigest()
        return f"kdb_{h[:8]}"


class KdbDao(BaseDao):
    async def save(self, kdb: "Kdb") -> bool:
        kdb.updated_at = get_local_now()
        return await BaseDao.save(self, kdb)

    async def get_by_id(self, kdb_id: str) -> Optional["Kdb"]:
        return await BaseDao.get_by_id(self, Kdb, kdb_id)

    async def delete_by_id(self, kdb_id: str) -> None:
        await BaseDao.delete_by_id(self, Kdb, kdb_id)

    async def update_by_id(self, kdb_id: str, update_map: Dict[str, Any]) -> None:
        await BaseDao.update_where(
            self, Kdb, where=[Kdb.id == kdb_id], values=update_map
        )

    async def get_kdbs_paginated(
        self,
        kdb_ids: List[str] | None,
        data_type: str,
        query_name: str,
        page: int,
        page_size: int,
        user_id: Optional[str] = None,
    ) -> tuple[list[Kdb], int]:
        """分页查询KDB"""
        where = []
        if kdb_ids:
            where.append(Kdb.id.in_(kdb_ids))
        if query_name:
            where.append(Kdb.name.like(f"%{query_name}%"))
        if data_type:
            where.append(Kdb.data_type == data_type)
        if user_id:
            where.append(Kdb.user_id == user_id)

        items, total = await BaseDao.paginate_list(
            self,
            Kdb,
            where=where,
            order_by=Kdb.created_at.desc(),
            page=page,
            page_size=page_size,
        )
        return items, total


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

    created_at: Mapped[datetime] = mapped_column(default=get_local_now)
    updated_at: Mapped[datetime] = mapped_column(default=get_local_now)


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
        await BaseDao.update_where(
            self, KdbDoc, where=[KdbDoc.id.in_(ids)], values={"status": status}
        )

    async def update_status(self, doc_id: str, status: int) -> None:
        await BaseDao.update_where(
            self, KdbDoc, where=[KdbDoc.id == doc_id], values={"status": status}
        )

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
        self, status: int, data_sources: List[str], limit: int
    ) -> list[KdbDoc]:
        where = [KdbDoc.status == status, KdbDoc.data_source.in_(data_sources)]
        return await BaseDao.get_list(
            self,
            KdbDoc,
            where=where,
            order_by=KdbDoc.created_at.asc(),
            limit=limit,
        )

    async def get_failed_list(
        self, data_sources: List[str], limit: int
    ) -> list[KdbDoc]:
        where = [
            KdbDoc.status == KdbDocStatus.FAILED,
            KdbDoc.data_source.in_(data_sources),
            KdbDoc.retry_count < 3,
        ]
        return await BaseDao.get_list(
            self,
            KdbDoc,
            where=where,
            order_by=KdbDoc.created_at.asc(),
            limit=limit,
        )

    async def save(self, doc: "KdbDoc") -> bool:
        doc.updated_at = get_local_now()
        return await BaseDao.save(self, doc)

    async def get_by_id(self, doc_id: str) -> Optional["KdbDoc"]:
        return await BaseDao.get_by_id(self, KdbDoc, doc_id)

    async def delete_by_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        await BaseDao.delete_where(self, KdbDoc, where=[KdbDoc.id.in_(ids)])

    async def get_counts_by_kdb_ids(self, kdb_ids: List[str]) -> dict[str, int]:
        if not kdb_ids:
            return {}
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = (
                select(KdbDoc.kdb_id, func.count())
                .where(KdbDoc.kdb_id.in_(kdb_ids))
                .group_by(KdbDoc.kdb_id)
            )
            res = await session.execute(stmt)
            rows = res.all()
            return {str(kdb_id): int(cnt or 0) for kdb_id, cnt in rows}

