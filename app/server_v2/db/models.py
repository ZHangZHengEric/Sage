from __future__ import annotations

from typing import Any

from app.server_v2.core.database import Database
from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(191), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))


class CatalogRow(Base):
    __tablename__ = "catalogs"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ThreadRow(Base):
    __tablename__ = "threads"
    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    agent_id: Mapped[str] = mapped_column(String(191), default="")
    updated_at: Mapped[str] = mapped_column(String(64))


class SkillRow(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint(
            "dimension",
            "owner_user_id",
            "name",
            name="uq_skills_scope_name",
        ),
    )

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(16), index=True)
    owner_user_id: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(191))
    description: Mapped[str] = mapped_column(String(512), default="")
    current_version_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64))


class SkillVersionRow(Base):
    __tablename__ = "skill_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    artifact_path: Mapped[str] = mapped_column(String(512))
    skill_md_sha256: Mapped[str] = mapped_column(String(64))
    package_sha256: Mapped[str] = mapped_column(String(80))
    file_count: Mapped[int] = mapped_column(Integer)
    total_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(64))


class AgentSkillSelectionRow(Base):
    __tablename__ = "agent_skill_selections"

    owner_user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(191), primary_key=True)
    source_skill_id: Mapped[str] = mapped_column(String(64), default="")
    position: Mapped[int] = mapped_column(Integer)


async def create_host_schema(database: Database) -> None:
    engine = database._engine
    if engine is None:
        raise RuntimeError("database is not started")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_thread_agent_id)


def _ensure_thread_agent_id(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "threads" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("threads")}
    if "agent_id" in columns:
        return
    connection.execute(
        text("ALTER TABLE threads ADD COLUMN agent_id VARCHAR(191) DEFAULT ''")
    )
