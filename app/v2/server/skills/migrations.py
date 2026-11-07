"""Additive upgrade; legacy bindings continue to follow the latest version."""
from sqlalchemy import Connection, inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateColumn

from app.v2.server.skills.orm import AgentSkillSelectionRow, SkillVersionRow


def upgrade_skill_schema(connection: Connection) -> None:
    for column in (SkillVersionRow.__table__.c.description,
                   AgentSkillSelectionRow.__table__.c.source_version_id):
        table = column.table.name
        if column.name in {item["name"] for item in inspect(connection).get_columns(table)}:
            continue
        try:
            connection.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN "
                + str(CreateColumn(column).compile(dialect=connection.dialect))
            )
        except DBAPIError:
            if column.name not in {item["name"] for item in inspect(connection).get_columns(table)}:
                raise
