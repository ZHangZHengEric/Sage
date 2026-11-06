from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.v2.server.database.base import Base


class UserRow(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(191), unique=True)
    username_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Kept for additive upgrades and rollback; new credentials live separately.
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(16))
    execution_policy: Mapped[str] = mapped_column(Text, default="{}")


class PasswordCredentialRow(Base):
    __tablename__ = "password_credentials"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class ExternalIdentityRow(Base):
    __tablename__ = "external_identities"
    identity_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    issuer: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(String(64), index=True)


class LoginSessionRow(Base):
    __tablename__ = "login_sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


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
