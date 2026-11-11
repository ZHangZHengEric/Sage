"""Dialect-specific primary key upserts for the Server database."""

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


async def upsert(db, table, values, *, key, replace=False):
    columns = (key,) if isinstance(key, str) else key
    changes = {name: value for name, value in values.items() if name not in columns} if replace else {}
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(table).values(values)
        statement = statement.on_duplicate_key_update(**(changes or {columns[0]: table.c[columns[0]]}))
    else:
        insert = postgres_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(table).values(values)
        if changes:
            statement = statement.on_conflict_do_update(index_elements=columns, set_=changes)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=columns)
    await db.execute(statement)
