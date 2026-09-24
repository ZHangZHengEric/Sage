from __future__ import annotations

from typing import Any
from sqlalchemy import JSON, String
from sqlalchemy.dialects.mysql import VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.server_v2.database.base import Base


class ManagedRecordRow(Base):
    """Indexed immutable package and operation records; no credentials."""
    __tablename__ = 'managed_agent_records'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(512).with_variant(VARCHAR(512, charset='utf8mb4', collation='utf8mb4_bin'), 'mysql'), default='')
    ref: Mapped[str] = mapped_column(String(80), default='', index=True)
    agent: Mapped[str] = mapped_column(String(191).with_variant(VARCHAR(191, charset='utf8mb4', collation='utf8mb4_bin'), 'mysql'), default='')
    session_key: Mapped[str] = mapped_column(String(64), default='', index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
