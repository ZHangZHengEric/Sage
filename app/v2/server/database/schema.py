from __future__ import annotations

from sqlalchemy import inspect, text

from app.v2.server.database import Database
from app.v2.server.database.base import Base
from app.v2.server.identity import orm as _identity_orm  # noqa: F401
from app.v2.server.catalog import orm as _catalog_orm  # noqa: F401
from app.v2.server.conversations import orm as _conversations_orm  # noqa: F401
from app.v2.server.skills import orm as _skills_orm  # noqa: F401
from app.v2.server.packages import orm as _packages_orm  # noqa: F401


async def create_host_schema(database: Database) -> None:
    engine = database._engine
    if engine is None:
        raise RuntimeError("database is not started")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_upgrade_legacy_schema)


def _upgrade_legacy_schema(connection) -> None:
    """Apply idempotent upgrades; create_all does not alter existing tables."""
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("threads")}
    if "agent_id" not in columns:
        connection.execute(
            text("ALTER TABLE threads ADD COLUMN agent_id VARCHAR(191) DEFAULT ''")
        )
    if connection.dialect.name in {"mysql", "mariadb"}:
        description = next(
            column
            for column in inspector.get_columns("skills")
            if column["name"] == "description"
        )
        if str(description["type"]).upper() != "LONGTEXT":
            connection.execute(
                text("ALTER TABLE skills MODIFY COLUMN description LONGTEXT NOT NULL")
            )
