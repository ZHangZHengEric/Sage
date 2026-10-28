
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from sqlalchemy import event, inspect

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.base import Base
from app.v2.server.database.schema import create_host_schema


async def test_schema_creates_current_tables_and_only_checks_metadata_on_restart(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        await create_host_schema(database)
        async with cast('AsyncEngine', database._engine).connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert set(Base.metadata.tables) <= tables
        engine = cast('AsyncEngine', database._engine).sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            await create_host_schema(database)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 2
        assert statements[0].lstrip().upper().startswith("SELECT")
        assert statements[1].lstrip().upper().startswith("PRAGMA")
    finally:
        await database.stop()


async def test_existing_im_outbox_is_upgraded_without_losing_deliveries(tmp_path):
    from sqlalchemy import text
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/upgrade.db"))
    await database.start()
    try:
        async with database._engine.begin() as connection:
            await connection.execute(text("CREATE TABLE im_deliveries (id INTEGER PRIMARY KEY, text TEXT)"))
            await connection.execute(text("INSERT INTO im_deliveries (id, text) VALUES (1, 'pending result')"))
        await create_host_schema(database)
        await create_host_schema(database)
        async with database._engine.connect() as connection:
            row = (await connection.execute(text("SELECT text, run_context FROM im_deliveries WHERE id = 1"))).one()
            assert tuple(row) == ("pending result", None)
    finally:
        await database.stop()
