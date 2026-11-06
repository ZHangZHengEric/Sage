"""Additive identity upgrade. Preserve legacy hashes for rollback, copy only once."""

from sqlalchemy import Column, Connection, Text, inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.schema import CreateColumn

from app.v2.server.identity.orm import PasswordCredentialRow, UserRow
from app.v2.server.identity.users import username_key


def upgrade_identity_schema(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("users")}
    # Early Server databases predate per-user execution policy as well.
    additions = [
        UserRow.__table__.c.username_key,
        Column("execution_policy", Text, nullable=True),
    ]
    for column in additions:
        if column.name in columns:
            continue
        try:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN "
                + str(CreateColumn(column).compile(dialect=connection.dialect))
            )
        except DBAPIError:
            if column.name not in {
                item["name"] for item in inspect(connection).get_columns("users")
            }:
                raise
    users = UserRow.__table__
    # Only legacy rows need work. New accounts write both records atomically.
    rows = (
        connection.execute(select(users).where(users.c.username_key.is_(None)))
        .mappings()
        .all()
    )
    keys: set[str] = set()
    for row in rows:
        key = username_key(row["username"])
        if key in keys:
            raise ValueError(
                "Conflicting normalized usernames; resolve duplicate accounts before upgrading"
            )
        keys.add(key)
        connection.execute(
            update(users)
            .where(users.c.user_id == row["user_id"])
            .values(username_key=key)
        )
        if row["password_hash"]:
            credentials = PasswordCredentialRow.__table__
            existing = connection.scalar(
                select(credentials.c.user_id).where(
                    credentials.c.user_id == row["user_id"]
                )
            )
            if existing is None:
                connection.execute(
                    credentials.insert().values(
                        user_id=row["user_id"], password_hash=row["password_hash"]
                    )
                )
    # unique=True is a table constraint on fresh installs; old tables need an index.
    inspector = inspect(connection)
    unique_keys = inspector.get_unique_constraints("users") + inspector.get_indexes(
        "users"
    )
    if not any(
        item.get("unique", True) and item["column_names"] == ["username_key"]
        for item in unique_keys
    ):
        from sqlalchemy import Index

        index = Index("uq_users_username_key", users.c.username_key, unique=True)
        try:
            index.create(connection)
        except (DBAPIError, IntegrityError):
            if not any(
                item["name"] == index.name
                for item in inspect(connection).get_indexes("users")
            ):
                raise
        finally:
            users.indexes.discard(index)
