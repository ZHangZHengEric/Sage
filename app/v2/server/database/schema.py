from __future__ import annotations

import hashlib

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from app.v2.server.im import orm as _im_orm  # noqa: F401
from app.v2.server.database import Database
from app.v2.server.database.base import Base
from app.v2.server.identity import orm as _identity_orm  # noqa: F401
from app.v2.server.identity.migrations import upgrade_identity_schema
from app.v2.server.skills.migrations import upgrade_skill_schema
from app.v2.server.observability.logging import get_logger
from app.v2.server.catalog import orm as _catalog_orm  # noqa: F401
from app.v2.server.conversations import orm as _conversations_orm  # noqa: F401
from app.v2.server.skills import orm as _skills_orm  # noqa: F401
from app.v2.server.observability import orm as _diagnostics_orm  # noqa: F401
from app.v2.server.packages import orm as _packages_orm  # noqa: F401
from app.v2.server.self_configuration import repository as _self_configuration  # noqa: F401

logger = get_logger(__name__)


async def create_host_schema(database: Database) -> None:
    engine = database._engine
    if engine is None:
        raise RuntimeError("database is not started")
    async with engine.connect() as connection:
        if connection.dialect.name == "mysql":
            # A connection lock survives MySQL DDL's implicit commits.
            database_name = engine.url.database or ""
            name = "sage-schema-" + hashlib.sha256(database_name.encode()).hexdigest()[:48]
            locked = await connection.scalar(text("SELECT GET_LOCK(:name, 60)"), {"name": name})
            await connection.commit()
            if locked != 1:
                raise RuntimeError("could not acquire the Server schema migration lock")
            try:
                async with connection.begin():
                    await connection.run_sync(_create_missing_host_tables)
            finally:
                await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
                await connection.commit()
        else:
            async with connection.begin():
                if connection.dialect.name == "postgresql":
                    await connection.execute(text(
                        "SELECT pg_advisory_xact_lock(hashtextextended(current_database() || ':' || current_schema() || ':' || :purpose, 0))"
                    ), {"purpose": "sage-host-schema"})
                if connection.dialect.name == "sqlite":
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")
                await connection.run_sync(_create_missing_host_tables)
    logger.info("server.schema.ready", "host schema and identity migration completed")


def _create_missing_host_tables(connection) -> None:
    # One metadata query replaces a per-table existence check on every boot.
    existing = set(inspect(connection).get_table_names())
    missing = [table for table in Base.metadata.sorted_tables if table.name not in existing]
    if missing:
        Base.metadata.create_all(connection, tables=missing, checkfirst=False)
    upgrade_identity_schema(connection)
    upgrade_skill_schema(connection)
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
