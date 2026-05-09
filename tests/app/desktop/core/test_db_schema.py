from sqlalchemy import create_engine, inspect, text

from app.desktop.core.db_schema import (
    ensure_desktop_models_registered,
    sync_database_schema,
)
from common.models.base import Base


def test_ensure_desktop_models_registered_loads_desktop_tables():
    ensure_desktop_models_registered()

    assert "agent_configs" in Base.metadata.tables
    assert "llm_providers" in Base.metadata.tables
    assert "token_usage" in Base.metadata.tables


def test_sync_database_schema_adds_missing_and_drops_unused_sqlite_columns():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE agent_configs (
                    agent_id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    config JSON NOT NULL,
                    user_id VARCHAR(128),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    legacy_prompt TEXT
                )
                """
            )
        )

        sync_database_schema(conn)

        columns = {col["name"] for col in inspect(conn).get_columns("agent_configs")}
        assert "is_default" in columns
        assert "legacy_prompt" not in columns
