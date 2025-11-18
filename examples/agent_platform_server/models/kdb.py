"""
Kdb ORM 模型（异步SQLAlchemy）
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON
from datetime import datetime
from typing import Optional, Dict, List, Any

from .base import Base, BaseDao
import hashlib


class Kdb(Base):
    __tablename__ = "kdb"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    intro: Mapped[str] = mapped_column(String(1024), default="")
    setting: Mapped[dict] = mapped_column(JSON, default=dict)
    data_type: Mapped[str] = mapped_column(String(52), default="file")
    user_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)

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
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def get_index_name(self) -> str:
        """获取KDB索引名称"""
        h = hashlib.sha1(self.id.encode()).hexdigest()
        return f"kdb_{h[:8]}"


class KdbDao(BaseDao):

    async def insert(self, obj: Kdb) -> None:
        await BaseDao.insert(self, obj)

    async def get_by_id(self, kdb_id: str) -> Optional[Kdb]:
        return await BaseDao.get_by_id(self, Kdb, kdb_id)

    async def delete_by_id(self, kdb_id: str) -> None:
        await BaseDao.delete_by_id(self, Kdb, kdb_id)

    async def update_by_id(self, kdb_id: str, update_map: Dict[str, Any]) -> None:
        await BaseDao.update_where(
            self, Kdb, where=[Kdb.id == kdb_id], values=update_map
        )

    async def get_kdbs_paginated(self, kdb_ids: List[str] | None, data_type: str, query_name: str, page: int, page_size: int, user_id: Optional[str] = None,) -> tuple[list[Kdb], int]:
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
