"""
File ORM 模型（异步SQLAlchemy）
"""

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class File(Base):
    __tablename__ = "file"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    path: Mapped[str] = mapped_column(String(4096), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)


class FileDao(BaseDao):
    async def get_by_id(self, id: str) -> Optional[File]:
        return await BaseDao.get_by_id(self, File, id)

    async def get_by_ids(self, ids: List[str]) -> Dict[str, File]:
        if not ids:
            return {}
        items = await BaseDao.get_list(self, File, where=[File.id.in_(ids)])
        return {f.id: f for f in items}

    async def delete_by_file_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        await BaseDao.delete_where(self, File, where=[File.id.in_(ids)])

    async def insert(self, obj: File) -> None:
        await BaseDao.insert(self, obj)

    async def batch_insert(self, objs: List[File]) -> None:
        if not objs:
            return
        await BaseDao.batch_insert(self, objs)

    async def get_by_file_path(self, path: str) -> Optional[File]:
        return await BaseDao.get_first(self, File, where=[File.path == path])
