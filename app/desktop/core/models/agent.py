"""
Agent 配置数据模型（SQLAlchemy ORM）
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Integer, select, or_, delete, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao, get_local_now


class Agent(Base):
    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        agent_id: str,
        name: str,
        config: Dict[str, Any],
        is_default: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.config = config
        self.is_default = is_default
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class AgentConfigDao(BaseDao):
    """
    Agent 配置数据访问对象（DAO）
    """

    async def get_by_name(self, name: str) -> Optional["Agent"]:
        where = [Agent.name == name]
        return await BaseDao.get_first(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def save(self, config: "Agent") -> bool:
        config.updated_at = get_local_now()
        return await BaseDao.save(self, config)

    async def get_by_id(self, agent_id: str) -> Optional["Agent"]:
        return await BaseDao.get_by_id(self, Agent, agent_id)

    async def get_all(self) -> List["Agent"]:
        return await BaseDao.get_all(self, Agent, Agent.created_at)

    async def get_by_ids(self, agent_ids: List[str]) -> List["Agent"]:
        return await BaseDao.get_list(
            self, Agent, where=[Agent.agent_id.in_(agent_ids)], order_by=Agent.created_at
        )

    async def get_list(self) -> List["Agent"]:
        return await BaseDao.get_list(
            self, Agent, order_by=Agent.created_at
        )

    async def get_default(self) -> Optional["Agent"]:
        """获取默认 Agent"""
        where = [Agent.is_default.is_(True)]
        return await BaseDao.get_first(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def set_default(self, agent_id: str) -> bool:
        """
        设置指定 Agent 为默认，同时将其他 Agent 设为非默认
        确保只有一个 Agent 是默认
        """
        from sqlalchemy import update
        from ..core.client.db import get_global_db

        db_client = await get_global_db()

        async with db_client.get_session(autocommit=False) as session:
            try:
                # 先将所有 Agent 设为非默认
                await session.execute(
                    update(Agent).values(is_default=False)
                )
                # 再将指定 Agent 设为默认
                result = await session.execute(
                    update(Agent).where(Agent.agent_id == agent_id).values(is_default=True)
                )
                await session.commit()
                return result.rowcount > 0
            except Exception as e:
                await session.rollback()
                raise e

    async def delete_by_id(self, agent_id: str) -> bool:
        return await BaseDao.delete_by_id(self, Agent, agent_id)

    async def update_config(self, agent_id: str, name: str = None, config: Dict[str, Any] = None, **kwargs) -> Optional["Agent"]:
        config_obj = await self.get_by_id(agent_id)
        if config_obj:
            if name:
                config_obj.name = name
            if config:
                config_obj.config = config

            config_obj.updated_at = get_local_now()
            await BaseDao.save(self, config_obj)
            return config_obj
        return None
