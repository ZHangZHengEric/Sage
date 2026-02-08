"""
Trace 数据模型 (SQLAlchemy ORM)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BaseDao


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    span_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    duration_ms: Mapped[float] = mapped_column(nullable=False)
    status_code: Mapped[str] = mapped_column(String(64), nullable=True)
    status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)
    events: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    resource: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)
    
    # Add index for session_id and start_time for efficient querying
    __table_args__ = (
        Index('idx_session_start_time', 'session_id', 'start_time'),
    )

    def __init__(
        self,
        span_id: str,
        trace_id: str,
        session_id: str,
        name: str,
        kind: str,
        start_time: datetime,
        end_time: datetime,
        duration_ms: float,
        parent_span_id: Optional[str] = None,
        status_code: Optional[str] = None,
        status_message: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        resource: Optional[Dict[str, Any]] = None,
    ):
        self.span_id = span_id
        self.trace_id = trace_id
        self.session_id = session_id
        self.name = name
        self.kind = kind
        self.start_time = start_time
        self.end_time = end_time
        self.duration_ms = duration_ms
        self.parent_span_id = parent_span_id
        self.status_code = status_code
        self.status_message = status_message
        self.attributes = attributes or {}
        self.events = events or []
        self.resource = resource or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "session_id": self.session_id,
            "name": self.name,
            "kind": self.kind,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_ms": self.duration_ms,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "attributes": self.attributes,
            "events": self.events,
            "resource": self.resource
        }

class TraceDao(BaseDao):
    """
    Trace 数据访问对象
    """
    async def save_spans(self, spans: List[TraceSpan]) -> None:
        """批量保存 Spans"""
        if not spans:
            return
        
        try:
            db = await self._get_db()
            async with db.get_session() as session:
                session.add_all(spans)
        except Exception as e:
            logger.error(f"Failed to save traces: {e}")
            raise

    async def get_traces_by_session_id(self, session_id: str) -> List[TraceSpan]:
        """获取指定 Session 的所有 Trace Spans"""
        from sqlalchemy import select
        
        db = await self._get_db()
        async with db.get_session() as session:
            stmt = select(TraceSpan).where(TraceSpan.session_id == session_id).order_by(TraceSpan.start_time)
            result = await session.execute(stmt)
            return result.scalars().all()
