from __future__ import annotations

from typing import Any
from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import LONGTEXT

from app.v2.server.database.base import Base


class CatalogRow(Base):
    __tablename__ = "catalogs"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    default_agent_id: Mapped[str] = mapped_column(String(64))
    models: Mapped[list[Any]] = mapped_column(JSON)
    mcp_servers: Mapped[list[Any]] = mapped_column(JSON)
    a2a_agents: Mapped[list[Any]] = mapped_column(JSON)


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(191))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql", "mariadb"), default="")
    model_id: Mapped[str] = mapped_column(String(191), default="")
    tools: Mapped[list[Any]] = mapped_column(JSON)
    execution_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
