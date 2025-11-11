"""
Agent 配置数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
import asyncio
from typing import Dict, Any, Optional, List

from sqlalchemy import String, select, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from core.globals import get_global_db


class Agent(Base):
    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        agent_id: str,
        name: str,
        config: Dict[str, Any],
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.config = config
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "config": self.config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Agent":
        return cls(
            agent_id=data["agent_id"],
            name=data["name"],
            config=data["config"],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class AgentConfigDao:
    """
    Agent 配置数据访问对象（DAO）
    """

    def __init__(self):
        self.db = None
        try:
            loop = asyncio.get_running_loop()
            self._db_task = loop.create_task(get_global_db())
        except RuntimeError:
            self._db_task = None

    @classmethod
    async def create(cls) -> "AgentConfigDao":
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

    async def get_by_name(self, name: str) -> Optional["Agent"]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Agent).where(Agent.name == name)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def save(self, config: "Agent") -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            config.updated_at = datetime.now().isoformat()
            await session.merge(config)
            return True

    async def get_by_id(self, agent_id: str) -> Optional["Agent"]:
        db = await self._get_db()
        async with db.get_session() as session:
            return await session.get(Agent, agent_id)

    async def get_all(self) -> List["Agent"]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Agent).order_by(Agent.created_at)
            res = await session.execute(stmt)
            return [o for o in res.scalars().all()]

    async def delete_by_id(self, agent_id: str) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(Agent, agent_id)
            if obj:
                session.delete(obj)
                return True
            return False
