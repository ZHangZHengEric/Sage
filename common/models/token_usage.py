"""Token usage ORM + DAO (shared by server and desktop)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
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
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=get_local_now)
    #: 完整 token 统计 JSON，与拆列字段同步落库，满足本地库可能存在的 NOT NULL 约束
    usage_payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

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
        started_at: datetime,
        finished_at: datetime,
        created_at: Optional[datetime] = None,
        usage_payload: str = "{}",
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
        self.started_at = started_at
        self.finished_at = finished_at
        self.created_at = created_at or get_local_now()
        self.usage_payload = usage_payload


class TokenUsageDao(BaseDao):
    async def save_usage(self, token_usage: TokenUsage) -> bool:
        return await BaseDao.save(self, token_usage)

    async def get_stats(
        self,
        *,
        dimension: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_source: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        dimension_map = {
            "agent": ("agent_id", TokenUsage.agent_id),
            "user": ("user_id", TokenUsage.user_id),
            "session": ("session_id", TokenUsage.session_id),
        }
        if dimension not in dimension_map:
            raise ValueError(f"Unsupported dimension: {dimension}")

        dimension_key, dimension_column = dimension_map[dimension]
        where = []
        if user_id is not None:
            where.append(TokenUsage.user_id == user_id)
        if agent_id is not None:
            where.append(TokenUsage.agent_id == agent_id)
        if session_id is not None:
            where.append(TokenUsage.session_id == session_id)
        if request_source is not None:
            where.append(TokenUsage.request_source == request_source)
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
                func.count(func.distinct(TokenUsage.session_id)).label("session_count"),
                func.coalesce(func.sum(TokenUsage.step_count), 0).label("model_call_count"),
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
                    func.count(func.distinct(TokenUsage.session_id)).label("session_count"),
                    func.coalesce(func.sum(TokenUsage.step_count), 0).label("model_call_count"),
                    func.min(TokenUsage.started_at).label("started_at"),
                    func.max(TokenUsage.finished_at).label("finished_at"),
                    func.min(TokenUsage.user_id).label("resolved_user_id"),
                    func.count(func.distinct(TokenUsage.user_id)).label("user_count"),
                    func.min(TokenUsage.agent_id).label("resolved_agent_id"),
                    func.count(func.distinct(TokenUsage.agent_id)).label("agent_count"),
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
            item_user_id = ""
            item_agent_id = ""
            item_session_id = ""
            if dimension == "user":
                item_user_id = str(row[dimension_key] or "")
            elif dimension == "agent":
                item_agent_id = str(row[dimension_key] or "")
            else:
                item_session_id = str(row[dimension_key] or "")
                if int(row["user_count"] or 0) == 1:
                    item_user_id = str(row["resolved_user_id"] or "")
                if int(row["agent_count"] or 0) == 1:
                    item_agent_id = str(row["resolved_agent_id"] or "")

            item = {
                "agent_id": item_agent_id,
                "user_id": item_user_id,
                "session_id": item_session_id,
                "session_count": int(row["session_count"] or 0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "model_call_count": int(row["model_call_count"] or 0),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            items.append(item)

        summary_session_count = int(summary_row["session_count"] or 0)
        summary_total_tokens = int(summary_row["total_tokens"] or 0)
        return {
            "summary": {
                "input_tokens": int(summary_row["input_tokens"] or 0),
                "output_tokens": int(summary_row["output_tokens"] or 0),
                "total_tokens": summary_total_tokens,
                "session_count": summary_session_count,
                "average_tokens_per_session": (
                    summary_total_tokens / summary_session_count if summary_session_count else 0
                ),
                "model_call_count": int(summary_row["model_call_count"] or 0),
            },
            "items": items,
        }
