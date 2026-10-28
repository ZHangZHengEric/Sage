from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.schema import CreateColumn

from app.v2.server.im import orm as _im_orm  # noqa: F401
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
        await connection.run_sync(_create_missing_host_tables)


def _create_missing_host_tables(connection) -> None:
    # One metadata query replaces a per-table existence check on every boot.
    existing = set(inspect(connection).get_table_names())
    missing = [table for table in Base.metadata.sorted_tables if table.name not in existing]
    if missing:
        Base.metadata.create_all(connection, tables=missing, checkfirst=False)
    if "im_deliveries" in existing:
        columns = {column["name"] for column in inspect(connection).get_columns("im_deliveries")}
        if "run_context" not in columns:
            column = Base.metadata.tables["im_deliveries"].c.run_context
            from sqlalchemy.exc import DBAPIError
            try:
                connection.exec_driver_sql(
                    "ALTER TABLE im_deliveries ADD COLUMN " + str(CreateColumn(column).compile(dialect=connection.dialect))
                )
            except DBAPIError:
                # Concurrent starters may have completed the same additive upgrade.
                if "run_context" not in {item["name"] for item in inspect(connection).get_columns("im_deliveries")}:
                    raise
