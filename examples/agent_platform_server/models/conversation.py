"""
会话数据模型（SQLAlchemy ORM）
"""

import json
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
        conversation = Conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
            agent_name=agent_name,
            title=title,
            messages=messages or [],
        )
        conversation.updated_at = datetime.now()
        return await BaseDao.save(self, conversation)

    async def get_by_session_id(self, session_id: str) -> Optional[Conversation]:
        return await BaseDao.get_by_id(self, Conversation, session_id)

    async def get_conversations_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        agent_id: Optional[str] = None,
        sort_by: str = "date",
    ) -> tuple[List[Conversation], int]:
        where = []
        if user_id:
            where.append(Conversation.user_id == user_id)
        if agent_id:
            where.append(Conversation.agent_id == agent_id)
        if search:
            like = f"%{search}%"
            where.append((Conversation.title.like(like)) | (Conversation.messages.like(like)))

        if sort_by == "title":
            order = Conversation.title.asc()
        elif sort_by == "messages":
            order = func.length(Conversation.messages).desc()
        else:
            order = Conversation.updated_at.desc()

        # Step 1: 仅查询 session_id，并进行计数 + 分页 + 排序
        db = await self._get_db()
        async with db.get_session() as session:
            base_stmt = select(Conversation.session_id)
            if where:
                for cond in where:
                    base_stmt = base_stmt.where(cond)

            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            total = int((await session.execute(count_stmt)).scalar() or 0)

            if order is not None:
                base_stmt = base_stmt.order_by(order)
            base_stmt = base_stmt.offset((page - 1) * page_size).limit(page_size)

            id_res = await session.execute(base_stmt)
            ids = list(id_res.scalars().all())

            if not ids:
                return [], total

            # Step 2: 使用批量 session_id 查询完整字段，并使用相同排序保证顺序一致
            data_stmt = select(Conversation).where(Conversation.session_id.in_(ids))
            if order is not None:
                data_stmt = data_stmt.order_by(order)

            res = await session.execute(data_stmt)
            items = list(res.scalars().all())
            return items, total

    async def delete_conversation(self, session_id: str) -> bool:
        return await BaseDao.delete_by_id(self, Conversation, session_id)

    async def update_conversation_messages(
        self, session_id: str, messages: List[Dict[str, Any]]
    ) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:
            conversation = await session.get(Conversation, session_id)
            if not conversation:
                return False
            conversation.messages = messages or []
            conversation.updated_at = datetime.now()
            await session.merge(conversation)
            return True
