"""MCPServer ORM + DAO (shared by server and desktop)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, or_
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        user_id: str = "",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.name = name
        self.config = config
        self.user_id = user_id
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class MCPServerDao(BaseDao):
    """MCP 服务器数据访问对象（共享 DAO）。"""

    async def get_by_name(self, name: str) -> Optional["MCPServer"]:
        return await BaseDao.get_by_id(self, MCPServer, name)

    async def get_list(self, user_id: Optional[str] = None) -> List["MCPServer"]:
        if user_id is None:
            where = None
        else:
            where = [or_(MCPServer.user_id == user_id, MCPServer.user_id == "")]
        return await BaseDao.get_list(
            self, MCPServer, where=where, order_by=MCPServer.created_at
        )

    async def delete_by_name(self, name: str) -> bool:
        return await BaseDao.delete_by_id(self, MCPServer, name)

    async def save_mcp_server(
        self, name: str, config: Dict[str, Any], user_id: Optional[str] = None
    ) -> MCPServer:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            existing = await session.get(MCPServer, name)
            now = get_local_now()
            if existing:
                existing.config = config
                existing.updated_at = now
                if user_id is not None:
                    existing.user_id = user_id
                await session.merge(existing)
                return existing
            else:
                obj = MCPServer(name=name, config=config, created_at=now, updated_at=now)
                if user_id is not None:
                    obj.user_id = user_id
                session.add(obj)
                return obj
