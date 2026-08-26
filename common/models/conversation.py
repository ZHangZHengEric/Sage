"""Conversation ORM + DAO (shared by server and desktop)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import json
from sqlalchemy import Index, Integer, JSON, String, Text, func, or_, select, update
from sqlalchemy.orm import Mapped, load_only, mapped_column

from common.models.base import Base, BaseDao, get_local_now


def _stored_message_count(messages: Any) -> int:
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except Exception:  # noqa: BLE001
            return 0
    if not isinstance(messages, list):
        return 0
    return len(messages)


class Conversation(Base):
    __tablename__ = "conversations"
    # 长 pytest 进程中模型可能被多次 import，避免重复注册同一张表。
    # 覆盖索引必须包含 session_id，避免 SQLite 回表读取巨大 messages JSON。
    __table_args__ = (
        Index(
            "idx_conversations_user_updated_session",
            "user_id",
            "updated_at",
            "session_id",
        ),
        Index("idx_conversations_updated_session", "updated_at", "session_id"),
        Index(
            "idx_conversations_user_agent_updated_session",
            "user_id",
            "agent_id",
            "updated_at",
            "session_id",
        ),
        Index(
            "idx_conversations_agent_updated_session",
            "agent_id",
            "updated_at",
            "session_id",
        ),
        Index(
            "idx_conversations_user_title_session",
            "user_id",
            "title",
            "session_id",
        ),
        Index("idx_conversations_title_session", "title", "session_id"),
        Index(
            "idx_conversations_user_msgcount_session",
            "user_id",
            "message_count",
            "session_id",
        ),
        Index("idx_conversations_msgcount_session", "message_count", "session_id"),
        {"extend_existing": True},
    )

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    messages: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=get_local_now)
    updated_at: Mapped[datetime] = mapped_column(
        default=get_local_now, onupdate=get_local_now
    )

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
        message_count: Optional[int] = None,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.title = title
        self.messages = messages or []
        self.message_count = (
            message_count
            if message_count is not None
            else _stored_message_count(self.messages)
        )
        self.created_at = created_at or get_local_now()
        self.updated_at = updated_at or get_local_now()

    def get_message_count(self) -> Dict[str, int]:
        """统计消息数量，区分用户与代理（assistant/agent）。"""
        user_count = 0
        agent_count = 0
        msgs: List[Dict[str, Any]] = []
        try:
            if isinstance(self.messages, str):
                msgs = json.loads(self.messages)
            else:
                msgs = self.messages or []
        except Exception:  # noqa: BLE001
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
    """会话数据访问对象（共享 DAO）。"""

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
        conversation.updated_at = get_local_now()
        return await BaseDao.save(self, conversation)

    async def get_by_session_id(self, session_id: str) -> Optional[Conversation]:
        return await BaseDao.get_by_id(self, Conversation, session_id)

    async def get_recent_conversations(
        self,
        *,
        user_id: Optional[str] = None,
        updated_after: Optional[datetime] = None,
        agent_id: Optional[str] = None,
    ) -> List[Conversation]:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = select(Conversation)
            if user_id:
                stmt = stmt.where(Conversation.user_id == user_id)
            if updated_after:
                stmt = stmt.where(Conversation.updated_at >= updated_after)
            if agent_id:
                stmt = stmt.where(Conversation.agent_id == agent_id)
            stmt = stmt.order_by(Conversation.updated_at.desc())
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_conversations_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        agent_id: Optional[str] = None,
        sort_by: str = "date",
        include_messages: bool = True,
    ) -> tuple[List[Conversation], int]:
        where = []
        if user_id:
            where.append(Conversation.user_id == user_id)
        if agent_id:
            where.append(Conversation.agent_id == agent_id)
        if search:
            like = f"%{search}%"
            where.append(
                or_(Conversation.title.like(like), Conversation.session_id.like(like))
            )

        if sort_by == "title":
            order = (Conversation.title.asc(), Conversation.session_id.asc())
        elif sort_by == "messages":
            order = (
                Conversation.message_count.desc(),
                Conversation.session_id.desc(),
            )
        else:
            order = (
                Conversation.updated_at.desc(),
                Conversation.session_id.desc(),
            )

        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            count_stmt = select(func.count()).select_from(Conversation)
            id_stmt = select(Conversation.session_id)
            if where:
                for cond in where:
                    count_stmt = count_stmt.where(cond)
                    id_stmt = id_stmt.where(cond)

            total = int((await session.execute(count_stmt)).scalar() or 0)
            id_stmt = id_stmt.order_by(*order).offset((page - 1) * page_size).limit(
                page_size
            )
            ids = list((await session.execute(id_stmt)).scalars().all())

            if not ids:
                return [], total

            data_stmt = select(Conversation).where(Conversation.session_id.in_(ids))
            if not include_messages:
                data_stmt = data_stmt.options(
                    load_only(
                        Conversation.session_id,
                        Conversation.user_id,
                        Conversation.agent_id,
                        Conversation.agent_name,
                        Conversation.title,
                        Conversation.message_count,
                        Conversation.created_at,
                        Conversation.updated_at,
                    )
                )
            res = await session.execute(data_stmt)
            items = list(res.scalars().all())
            order_index = {sid: idx for idx, sid in enumerate(ids)}
            items.sort(key=lambda x: order_index.get(x.session_id, len(order_index)))
            return items, total

    async def delete_conversation(self, session_id: str) -> bool:
        return await BaseDao.delete_by_id(self, Conversation, session_id)

    async def update_conversation_messages(
        self, session_id: str, messages: List[Dict[str, Any]]
    ) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            payload = messages or []
            stmt = (
                update(Conversation)
                .where(Conversation.session_id == session_id)
                .values(
                    messages=payload,
                    message_count=_stored_message_count(payload),
                    updated_at=get_local_now(),
                )
            )
            result = await session.execute(stmt)
            return bool(result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]

    async def update_title(self, session_id: str, title: str) -> bool:
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = (
                update(Conversation)
                .where(Conversation.session_id == session_id)
                .values(title=title, updated_at=get_local_now())
            )
            result = await session.execute(stmt)
            return bool(result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]

    async def update_timestamp(self, session_id: str) -> bool:
        """仅更新会话的 updated_at 时间戳。"""
        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            stmt = (
                update(Conversation)
                .where(Conversation.session_id == session_id)
                .values(updated_at=get_local_now())
            )
            result = await session.execute(stmt)
            return bool(result.rowcount)  # pyright: ignore[reportAttributeAccessIssue]

    # Desktop 端兼容方法：不带 user_id 的分页查询（保持原签名）
    async def get_conversations_paginated_desktop(
        self,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        agent_id: Optional[str] = None,
        sort_by: str = "date",
    ) -> tuple[List[Conversation], int]:
        return await self.get_conversations_paginated(
            page=page,
            page_size=page_size,
            user_id=None,
            search=search,
            agent_id=agent_id,
            sort_by=sort_by,
        )
