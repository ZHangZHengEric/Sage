from sqlalchemy import event, inspect

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.base import Base
from app.v2.server.database.schema import create_host_schema


async def test_schema_creates_current_tables_and_only_checks_existence_on_restart(tmp_path):
    database = Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db"))
    await database.start()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        await create_host_schema(database)
        async with database._engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert set(Base.metadata.tables) <= tables
        engine = database._engine.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            await create_host_schema(database)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 1
        assert statements[0].lstrip().upper().startswith("SELECT")
    finally:
        await database.stop()
