from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.server_v2.database.base import Base


class UserRow(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(191), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))


class ApiKeyRow(Base):
    """Machine credentials for the A2A surface. Stores a hash, never a token."""

    __tablename__ = "api_keys"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(191), default="")
    name: Mapped[str] = mapped_column(String(191), default="")
    key_hash: Mapped[str] = mapped_column(String(255))
    scopes: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[str] = mapped_column(String(64))
    revoked_at: Mapped[str] = mapped_column(String(64), default="")
