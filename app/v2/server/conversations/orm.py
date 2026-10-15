from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.v2.server.database.base import Base


class ThreadRow(Base):
    __tablename__ = "threads"
    thread_id: Mapped[str] = mapped_column(String(192), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    agent_id: Mapped[str] = mapped_column(String(191), default="")
    updated_at: Mapped[str] = mapped_column(String(64))


class SessionBindingRow(Base):
    """Immutable ownership claim; IDs are global in the current SessionStore."""

    __tablename__ = "session_bindings"
    session_id: Mapped[str] = mapped_column(String(192), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(191))
    tenant_id: Mapped[str] = mapped_column(String(191))
    agent_id: Mapped[str] = mapped_column(String(191))
