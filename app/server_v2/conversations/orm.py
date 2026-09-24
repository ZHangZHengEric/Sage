from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.server_v2.database.base import Base


class ThreadRow(Base):
    __tablename__ = "threads"
    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    agent_id: Mapped[str] = mapped_column(String(191), default="")
    updated_at: Mapped[str] = mapped_column(String(64))
