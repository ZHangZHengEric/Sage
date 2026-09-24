from __future__ import annotations

from app.server_v2.database import Database
from app.server_v2.database.base import Base
from app.server_v2.identity import orm as _identity_orm  # noqa: F401
from app.server_v2.catalog import orm as _catalog_orm  # noqa: F401
from app.server_v2.conversations import orm as _conversations_orm  # noqa: F401
from app.server_v2.skills import orm as _skills_orm  # noqa: F401
from app.server_v2.packages import orm as _packages_orm  # noqa: F401


async def create_host_schema(database: Database) -> None:
    engine = database._engine
    if engine is None:
        raise RuntimeError("database is not started")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
