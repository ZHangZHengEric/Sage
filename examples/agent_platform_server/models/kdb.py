"""
Kdb ORM 模型（异步SQLAlchemy）
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON
from datetime import datetime
from typing import Optional, Dict, List, Any

from sqlalchemy import select, update, func

from .base import Base, BaseDao


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


class KdbDao(BaseDao):

    async def insert(self, obj: Kdb) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            await session.add(obj)

    async def get_by_id(self, kdb_id: str) -> Optional[Kdb]:
        db = await self._get_db()
        async with db.get_session() as session:
            return await session.get(Kdb, kdb_id)

    async def delete_by_id(self, kdb_id: str) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(Kdb, kdb_id)
            if obj:
                await session.delete(obj)

    async def update_by_id(self, kdb_id: str, update_map: Dict[str, Any]) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(
                update(Kdb).where(Kdb.id == kdb_id).values(**update_map)
            )

    async def get_list(
        self,
        kdb_ids: List[str] | None,
        data_type: str,
        query_name: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Kdb], int]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Kdb)
            if kdb_ids:
                stmt = stmt.where(Kdb.id.in_(kdb_ids))
            if query_name:
                stmt = stmt.where(Kdb.name.like(f"%{query_name}%"))
            if data_type:
                stmt = stmt.where(Kdb.data_type == data_type)
            count_stmt = select(func.count()).select_from(stmt.subquery())
            cnt = (await session.execute(count_stmt)).scalar() or 0
            stmt = (
                stmt.offset((page - 1) * page_size)
                .limit(page_size)
                .order_by(Kdb.created_at.desc())
            )
            res = (await session.execute(stmt)).scalars().all()
            return list(res), int(cnt)
