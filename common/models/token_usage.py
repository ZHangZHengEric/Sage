"""Token usage ORM + DAO (shared by server and desktop)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from common.models.base import Base, BaseDao, get_local_now


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (
        Index("idx_token_usage_user_finished_at", "user_id", "finished_at"),
        Index("idx_token_usage_agent_finished_at", "agent_id", "finished_at"),
        Index("idx_token_usage_session_finished_at", "session_id", "finished_at"),
        Index("idx_token_usage_finished_at", "finished_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    request_source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_audio_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_audio_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=get_local_now)

    def __init__(
        self,
        *,
        id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
        request_source: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cached_tokens: int,
        reasoning_tokens: int,
        prompt_audio_tokens: int,
        completion_audio_tokens: int,
        step_count: int,
        usage_payload: Dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        created_at: Optional[datetime] = None,
    ) -> None:
        self.id = id
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.request_source = request_source
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.cached_tokens = cached_tokens
        self.reasoning_tokens = reasoning_tokens
        self.prompt_audio_tokens = prompt_audio_tokens
        self.completion_audio_tokens = completion_audio_tokens
        self.step_count = step_count
        self.usage_payload = usage_payload
        self.started_at = started_at
        self.finished_at = finished_at
        self.created_at = created_at or get_local_now()


class TokenUsageDao(BaseDao):
    async def save_usage(self, token_usage: TokenUsage) -> bool:
        return await BaseDao.save(self, token_usage)

    async def get_stats(
        self,
        *,
        group_by: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        dimension_map = {
            "user": ("user_id", TokenUsage.user_id),
            "agent": ("agent_id", TokenUsage.agent_id),
            "session": ("session_id", TokenUsage.session_id),
        }
        if group_by not in dimension_map:
            raise ValueError(f"Unsupported group_by: {group_by}")

        dimension_key, dimension_column = dimension_map[group_by]
        where = []
        if user_id is not None:
            where.append(TokenUsage.user_id == user_id)
        if agent_id is not None:
            where.append(TokenUsage.agent_id == agent_id)
        if session_id is not None:
            where.append(TokenUsage.session_id == session_id)
        if start_time is not None:
            where.append(TokenUsage.finished_at >= start_time)
        if end_time is not None:
            where.append(TokenUsage.finished_at <= end_time)

        db = await self._get_db()
        async with db.get_session() as session:  # type: ignore[attr-defined]
            summary_stmt = select(
                func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
                func.count(TokenUsage.id).label("execution_count"),
                func.coalesce(func.sum(TokenUsage.cached_tokens), 0).label("cached_tokens"),
                func.coalesce(func.sum(TokenUsage.reasoning_tokens), 0).label("reasoning_tokens"),
            )
            for cond in where:
                summary_stmt = summary_stmt.where(cond)
            summary_row = (await session.execute(summary_stmt)).mappings().one()

            items_stmt = (
                select(
                    dimension_column.label(dimension_key),
                    func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input_tokens"),
                    func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output_tokens"),
                    func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
                    func.count(TokenUsage.id).label("execution_count"),
                    func.coalesce(func.sum(TokenUsage.cached_tokens), 0).label("cached_tokens"),
                    func.coalesce(func.sum(TokenUsage.reasoning_tokens), 0).label("reasoning_tokens"),
                    func.min(TokenUsage.finished_at).label("first_seen_at"),
                    func.max(TokenUsage.finished_at).label("last_seen_at"),
                )
                .group_by(dimension_column)
                .order_by(
                    func.coalesce(func.sum(TokenUsage.total_tokens), 0).desc(),
                    func.max(TokenUsage.finished_at).desc(),
                )
            )
            for cond in where:
                items_stmt = items_stmt.where(cond)
            item_rows = (await session.execute(items_stmt)).mappings().all()

        items: List[Dict[str, Any]] = []
        for row in item_rows:
            item = {
                "user_id": None,
                "agent_id": None,
                "session_id": None,
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "execution_count": int(row["execution_count"] or 0),
                "cached_tokens": int(row["cached_tokens"] or 0),
                "reasoning_tokens": int(row["reasoning_tokens"] or 0),
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
            }
            item[dimension_key] = row[dimension_key]
            items.append(item)

        return {
            "summary": {
                "input_tokens": int(summary_row["input_tokens"] or 0),
                "output_tokens": int(summary_row["output_tokens"] or 0),
                "total_tokens": int(summary_row["total_tokens"] or 0),
                "execution_count": int(summary_row["execution_count"] or 0),
                "cached_tokens": int(summary_row["cached_tokens"] or 0),
                "reasoning_tokens": int(summary_row["reasoning_tokens"] or 0),
            },
            "items": items,
        }
