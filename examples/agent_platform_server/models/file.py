"""
File ORM 模型（异步SQLAlchemy）
"""

from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from .base import Base, BaseDao
from typing import List, Optional, Dict, Any
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession


class File(Base):
    __tablename__ = "file"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    path: Mapped[str] = mapped_column(String(4096), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)


class FileDao(BaseDao):
    async def get_by_id(self, id: str) -> Optional[File]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(File).where(File.id == id)
            return (await session.execute(stmt)).scalars().first()

    async def get_by_ids(self, ids: List[str]) -> Dict[str, File]:
        if not ids:
            return {}
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(File).where(File.id.in_(ids))
            res = (await session.execute(stmt)).scalars().all()
            return {f.id: f for f in res}

    async def delete_by_file_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            await session.execute(delete(File).where(File.id.in_(ids)))

    async def insert(self, obj: File) -> None:
        db = await self._get_db()
        async with db.get_session() as session:
            await session.add(obj)

    async def batch_insert(self, objs: List[File]) -> None:
        if not objs:
            return
        db = await self._get_db()
        async with db.get_session() as session:
            await session.add_all(objs)

    async def get_by_file_path(self, path: str) -> Optional[File]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(File).where(File.path == path)
            return (await session.execute(stmt)).scalars().first()
