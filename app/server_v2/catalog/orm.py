from __future__ import annotations

from typing import Any
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.server_v2.database.base import Base


class CatalogRow(Base):
    __tablename__ = "catalogs"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agents: Mapped[list[Any]] = mapped_column(JSON)
    models: Mapped[list[Any]] = mapped_column(JSON)
    mcp_servers: Mapped[list[Any]] = mapped_column(JSON)
    a2a_agents: Mapped[list[Any]] = mapped_column(JSON)
