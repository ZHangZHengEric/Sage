"""
MCP服务器数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


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


class MCPServerDao(BaseDao):
    """
    MCP 服务器数据访问对象（DAO）
    """

    async def get_by_name(self, name: str) -> Optional["MCPServer"]:
        return await BaseDao.get_by_id(self, MCPServer, name)

    async def get_list(self) -> List["MCPServer"]:
        return await BaseDao.get_list(self, MCPServer, order_by=MCPServer.created_at)

    async def delete_by_name(self, name: str) -> bool:
        return await BaseDao.delete_by_id(self, MCPServer, name)

    async def save_mcp_server(
        self, name: str, config: Dict[str, Any]
    ) -> MCPServer:
        db = await self._get_db()
        async with db.get_session() as session:
            existing = await session.get(MCPServer, name)
            now = datetime.now()
            if existing:
                existing.config = config
                existing.updated_at = now
                await session.merge(existing)
                return existing
            else:
                obj = MCPServer(name=name, config=config, created_at=now, updated_at=now)
                session.add(obj)
                return obj
