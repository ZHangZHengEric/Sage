"""Operational IM state only. Sage Session remains the conversation authority."""

from sqlalchemy import JSON, Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.v2.server.database.base import Base


class ConnectionRow(Base):
    __tablename__ = "im_connections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(191))
    name: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSON)
    account_key: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    sender_id: Mapped[str] = mapped_column(String(192), default="")
    auth_epoch: Mapped[int] = mapped_column(Integer, default=1)
    pairing_hash: Mapped[str] = mapped_column(String(64), default="")
    pairing_until: Mapped[float] = mapped_column(Float, default=0)
    pairing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)


class BindingRow(Base):
    __tablename__ = "im_conversation_bindings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64), index=True)
    chat_id: Mapped[str] = mapped_column(String(192))
    sender_id: Mapped[str] = mapped_column(String(192))
    session_id: Mapped[str] = mapped_column(String(192))
    generation: Mapped[int] = mapped_column(Integer, default=1)


class InboxRow(Base):
    __tablename__ = "im_inbox"
    __table_args__ = (
        Index("ix_im_inbox_connection_state_id", "connection_id", "state", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(String(64))
    message_key: Mapped[str] = mapped_column(String(64), unique=True)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)
    digest: Mapped[str] = mapped_column(String(64))
    binding_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(192))
    generation: Mapped[int] = mapped_column(Integer)
    auth_epoch: Mapped[int] = mapped_column(Integer)
    sender_id: Mapped[str] = mapped_column(String(192))
    chat_id: Mapped[str] = mapped_column(String(192))
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(24), default="pending")
    command: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_id: Mapped[str] = mapped_column(String(192), default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[float] = mapped_column(Float)


class DeliveryRow(Base):
    __tablename__ = "im_deliveries"
    __table_args__ = (
        Index("ix_im_delivery_connection_state_id", "connection_id", "state", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(String(64))
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    binding_id: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    auth_epoch: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[str] = mapped_column(String(192))
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0)
    receipt: Mapped[str] = mapped_column(String(192), default="")
    error: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[float] = mapped_column(Float)
    # A prepared Run notification is an outbox intent, not an inbound IM event.
    run_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
