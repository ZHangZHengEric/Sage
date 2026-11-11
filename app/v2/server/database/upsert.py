"""Dialect-specific primary key upserts for the Server database."""

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


async def upsert(db, table, values, *, key, merge=None):
    columns = (key,) if isinstance(key, str) else key
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(table).values(values)
        changes = merge(statement.inserted) if merge else {columns[0]: table.c[columns[0]]}
        statement = statement.on_duplicate_key_update(list(changes.items()))
    else:
        insert = postgres_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(table).values(values)
        if merge:
            statement = statement.on_conflict_do_update(
                index_elements=columns, set_=merge(statement.excluded),
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=columns)
    await db.execute(statement)
