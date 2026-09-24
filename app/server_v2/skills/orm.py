from __future__ import annotations

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.server_v2.database.base import Base


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
