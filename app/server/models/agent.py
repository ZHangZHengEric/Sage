"""
Agent 配置数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String
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


class AgentConfigDao(BaseDao):
    """
    Agent 配置数据访问对象（DAO）
    """

    async def get_by_name_and_user(self, name: str, user_id: str) -> Optional["Agent"]:
        where = [Agent.name == name, Agent.user_id == user_id]
        return await BaseDao.get_first(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def save(self, config: "Agent") -> bool:
        config.updated_at = datetime.now()
        return await BaseDao.save(self, config)

    async def get_by_id(self, agent_id: str) -> Optional["Agent"]:
        return await BaseDao.get_by_id(self, Agent, agent_id)

    async def get_all(self) -> List["Agent"]:
        return await BaseDao.get_all(self, Agent, Agent.created_at)

    async def get_list(self, user_id: Optional[str] = None) -> List["Agent"]:
        where = [Agent.user_id == user_id] if user_id else None
        return await BaseDao.get_list(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def delete_by_id(self, agent_id: str) -> bool:
        return await BaseDao.delete_by_id(self, Agent, agent_id)
