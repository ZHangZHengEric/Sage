"""
会话数据模型（SQLAlchemy ORM）
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from sqlalchemy import String, Text, func, select, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class Conversation(Base):
    __tablename__ = "conversations"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    messages: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        agent_name: str,
        title: str,
        messages: List[Dict[str, Any]],
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.title = title
        self.messages = messages or []
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        msgs = self.messages or []
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "title": self.title,
            "messages": msgs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def get_message_count(self) -> Dict[str, int]:
        """统计消息数量，区分用户与代理（assistant/agent）"""
        user_count = 0
        agent_count = 0
        msgs: List[Dict[str, Any]] = []
        try:
            if isinstance(self.messages, str):
                msgs = json.loads(self.messages)
            else:
                msgs = self.messages or []
        except Exception:
            msgs = self.messages if isinstance(self.messages, list) else []

        for m in msgs:
            role = (m or {}).get("role")
            if role == "user":
                user_count += 1
            elif role in ("assistant", "agent"):
                agent_count += 1
        return {
            "user_count": user_count,
            "agent_count": agent_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            agent_id=data["agent_id"],
            agent_name=data["agent_name"],
            title=data["title"],
            messages=data.get("messages", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class ConversationDao(BaseDao):
    """
    会话数据访问对象（DAO）
    """

    async def save_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        agent_name: str,
        title: str,
        messages: List[Dict[str, Any]],
    ) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            conversation = Conversation(
                user_id=user_id,
                session_id=session_id,
                agent_id=agent_id,
                agent_name=agent_name,
                title=title,
                messages=messages or [],
            )
            conversation.updated_at = datetime.now()
            await session.merge(conversation)
            return True

    async def get_by_session_id(self, session_id: str) -> Optional[Conversation]:
        db = await self._get_db()
        async with db.get_session() as session:
            conversation = await session.get(Conversation, session_id)
            return conversation

    async def get_all_conversations(self) -> List[Conversation]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Conversation).order_by(Conversation.updated_at.desc())
            res = await session.execute(stmt)
            return [o for o in res.scalars().all()]

    async def get_conversations_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        agent_id: Optional[str] = None,
        sort_by: str = "date",
    ) -> tuple[List[Conversation], int]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(Conversation)
            if user_id:
                stmt = stmt.where(Conversation.user_id == user_id)
            if agent_id:
                stmt = stmt.where(Conversation.agent_id == agent_id)
            if search:
                like = f"%{search}%"
                stmt = stmt.where(
                    (Conversation.title.like(like)) | (Conversation.messages.like(like))
                )

            count_stmt = select(func.count()).select_from(Conversation)
            if user_id:
                count_stmt = count_stmt.where(Conversation.user_id == user_id)
            if agent_id:
                count_stmt = count_stmt.where(Conversation.agent_id == agent_id)
            if search:
                like = f"%{search}%"
                count_stmt = count_stmt.where(
                    (Conversation.title.like(like)) | (Conversation.messages.like(like))
                )
            count_res = await session.execute(count_stmt)
            total = count_res.scalar() or 0

            if sort_by == "title":
                stmt = stmt.order_by(Conversation.title.asc())
            elif sort_by == "messages":
                stmt = stmt.order_by(func.length(Conversation.messages).desc())
            else:
                stmt = stmt.order_by(Conversation.updated_at.desc())

            offset = (page - 1) * page_size
            stmt = stmt.offset(offset).limit(page_size)
            res = await session.execute(stmt)
            items = res.scalars().all()
            return [o for o in items], int(total)

    async def get_conversations_by_agent(self, agent_id: str) -> List[Conversation]:
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = (
                select(Conversation)
                .where(Conversation.agent_id == agent_id)
                .order_by(Conversation.updated_at.desc())
            )
            res = await session.execute(stmt)
            return [o for o in res.scalars().all()]

    async def delete_conversation(self, session_id: str) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            obj = await session.get(Conversation, session_id)
            if obj:
                session.delete(obj)
                return True
            return False

    async def update_conversation_messages(
        self, session_id: str, messages: List[Dict[str, Any]]
    ) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            conversation = await session.get(Conversation, session_id)
            if conversation:
                conversation.messages = messages or []
                conversation.updated_at = datetime.now()
                await session.merge(conversation)
                return True
            return False
