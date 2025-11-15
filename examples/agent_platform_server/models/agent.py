"""
Agent 配置数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
import asyncio
from typing import Dict, Any, Optional, List

from sqlalchemy import String, select, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class Agent(Base):
    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), default="")
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
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

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


class AgentConfigDao(BaseDao):
    """
    Agent 配置数据访问对象（DAO）
    """

    async def get_by_name(self, name: str) -> Optional["Agent"]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Agent).where(Agent.name == name)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def save(self, config: "Agent") -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            config.updated_at = datetime.now()
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
                await session.delete(obj)
                return True
            return False
