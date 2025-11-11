"""
MCP服务器数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
import asyncio
from typing import Dict, Any, Optional, List

from sqlalchemy import String, JSON, select
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from core.globals import get_global_db


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.name = name
        self.config = config
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "config": self.config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServer":
        return cls(
            name=data["name"],
            config=data["config"],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class MCPServerDao:
    """
    MCP 服务器数据访问对象（DAO）
    """

    def __init__(self):
        # 在初始化阶段获取全局数据库实例（若事件循环可用则预取）
        self.db = None
        try:
            loop = asyncio.get_running_loop()
            self._db_task = loop.create_task(get_global_db())
        except RuntimeError:
            # 若无运行中的事件循环，延迟到方法调用时获取
            self._db_task = None

    @classmethod
    async def create(cls) -> "MCPServerDao":
        """工厂方法：创建并绑定已初始化的 DB 的 DAO 实例"""
        inst = cls()
        inst.db = await get_global_db()
        return inst

    async def _get_db(self):
        if self.db is not None:
            return self.db
        if self._db_task is not None:
            self.db = await self._db_task
            return self.db
        self.db = await get_global_db()
        return self.db

    async def get_by_name(self, name: str) -> Optional["MCPServer"]:
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(MCPServer, name)
            return obj

    async def get_all(self) -> List["MCPServer"]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(MCPServer).order_by(MCPServer.created_at)
            res = await session.execute(stmt)
            return [o for o in res.scalars().all()]

    async def delete_by_name(self, name: str) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(MCPServer, name)
            if obj:
                await session.delete(obj)
                return True
            return False

    async def save_mcp_server(self, name: str, config: Dict[str, Any]) -> MCPServer:
        db = await self._get_db()
        async with db.get_session() as session:
            existing = await session.get(MCPServer, name)
            now = datetime.now()
            if existing:
                # 合并更新配置，保留未提供的现有字段
                existing.config = config
                existing.updated_at = now
                # 使用 merge 确保改动被持久化
                await session.merge(existing)
                return existing
            else:
                obj = MCPServer(
                    name=name, config=config, created_at=now, updated_at=now
                )
                await session.add(obj)
                return obj
