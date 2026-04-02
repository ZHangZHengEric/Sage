"""Agent ORM + DAO (shared by server and desktop)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, String, Integer, select, or_, delete, Boolean, update
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class AgentAuthorization(Base):
    __tablename__ = "agent_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=get_local_now)


class Agent(Base):
    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        agent_id: str,
        name: str,
        config: Dict[str, Any],
        user_id: str = "",
        is_default: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.config = config
        self.user_id = user_id
        self.is_default = is_default
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()


class AgentConfigDao(BaseDao):
    """Agent 配置数据访问对象（共享 DAO）。"""

    async def get_by_name_and_user(self, name: str, user_id: str) -> Optional["Agent"]:
        where = [Agent.name == name, Agent.user_id == user_id]
        return await BaseDao.get_first(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def get_by_name(self, name: str) -> Optional["Agent"]:
        """Desktop 端使用的按名称查询（无 user_id 限制）。"""
        where = [Agent.name == name]
        return await BaseDao.get_first(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def get_default(self) -> Optional["Agent"]:
        return await BaseDao.get_first(
            self,
            Agent,
            where=[Agent.is_default == True],  # noqa: E712
            order_by=Agent.created_at,
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
            self,
            Agent,
            where=[Agent.agent_id.in_(agent_ids)],
            order_by=Agent.created_at,
        )

    async def get_list(self, user_id: Optional[str] = None) -> List["Agent"]:
        where = [Agent.user_id == user_id] if user_id else None
        return await BaseDao.get_list(
            self, Agent, where=where, order_by=Agent.created_at
        )

    async def get_list_with_auth(self, user_id: Optional[str] = None) -> List["Agent"]:
        """Get agents owned by user OR authorized to user (server use)."""
        if not user_id:
            return await self.get_list(None)  # Admin sees all

        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(Agent)
            # Subquery for authorized agent IDs
            auth_subq = select(AgentAuthorization.agent_id).where(
                AgentAuthorization.user_id == user_id
            )

            stmt = stmt.where(
                or_(Agent.user_id == user_id, Agent.agent_id.in_(auth_subq))
            ).order_by(Agent.created_at)

            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_authorized_users(self, agent_id: str) -> List[str]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(AgentAuthorization.user_id).where(
                AgentAuthorization.agent_id == agent_id
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def update_authorizations(self, agent_id: str, user_ids: List[str]) -> None:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            # Delete existing
            await session.execute(
                delete(AgentAuthorization).where(AgentAuthorization.agent_id == agent_id)
            )
            # Insert new
            if user_ids:
                objs = [
                    AgentAuthorization(agent_id=agent_id, user_id=uid)
                    for uid in user_ids
                ]
                session.add_all(objs)

    async def delete_by_id(self, agent_id: str) -> bool:
        return await BaseDao.delete_by_id(self, Agent, agent_id)

    async def set_default(self, agent_id: str) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            target = await session.get(Agent, agent_id)
            if not target:
                return False

            await session.execute(update(Agent).values(is_default=False))
            target.is_default = True
            target.updated_at = get_local_now()
            session.add(target)
            return True
