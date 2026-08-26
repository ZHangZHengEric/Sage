from types import SimpleNamespace

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, create_engine, inspect, text

from common.core.client import db
from common.core.client.db import (
    drop_obsolete_conversation_indexes,
    migrate_legacy_conversation_messages_column,
    sync_database_schema,
    sync_missing_indexes,
)
from common.models.base import Base
from common.models.conversation import Conversation  # noqa: F401


def test_create_aiomysql_engine_forces_ping_reconnect_arg(monkeypatch):
    fake_dialect = SimpleNamespace()
    fake_engine = SimpleNamespace(sync_engine=SimpleNamespace(dialect=fake_dialect))
    calls = []

    def fake_create_async_engine(*args, **kwargs):
        calls.append((args, kwargs))
        return fake_engine

    monkeypatch.setattr(db, "create_async_engine", fake_create_async_engine)

    engine = db._create_aiomysql_engine(
        "mysql+aiomysql://user:pass@host/db", future=True, pool_pre_ping=True
    )

    assert engine is fake_engine
    assert fake_dialect.__dict__["_send_false_to_ping"] is True
    assert calls == [
        (
            ("mysql+aiomysql://user:pass@host/db",),
            {"future": True, "pool_pre_ping": True},
        )
    ]


def test_sync_missing_indexes_creates_declared_index():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "demo_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(64)),
        Index("idx_demo_items_name", "name"),
    )

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE demo_items (id INTEGER PRIMARY KEY, name VARCHAR(64))"))
        sync_missing_indexes(conn, metadata)
        index_names = {idx["name"] for idx in inspect(conn).get_indexes("demo_items")}

    assert "idx_demo_items_name" in index_names


def test_sync_database_schema_adds_conversation_list_indexes():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE conversations (
                    session_id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    agent_id VARCHAR(255) NOT NULL,
                    agent_name TEXT NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    messages JSON NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        sync_database_schema(conn, Base)
        columns = {col["name"] for col in inspect(conn).get_columns("conversations")}
        index_names = {idx["name"] for idx in inspect(conn).get_indexes("conversations")}

    assert "message_count" in columns
    assert "user_count" in columns
    assert "agent_count" in columns
    assert "messages" in columns
    assert "idx_conversations_updated_session" in index_names
    assert "idx_conversations_user_updated_session" in index_names
    assert "idx_conversations_user_msgcount_session" not in index_names
    assert "idx_conversations_title_session" not in index_names


def test_legacy_messages_column_is_left_in_place_at_startup():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE conversations (
                    session_id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    messages JSON NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO conversations (session_id, user_id, messages, message_count) "
                "VALUES ('s1', 'u1', json('[]'), 0)"
            )
        )
        migrate_legacy_conversation_messages_column(conn)
        columns = {col["name"] for col in inspect(conn).get_columns("conversations")}
        count = conn.execute(text("SELECT message_count FROM conversations WHERE session_id = 's1'")).scalar()

    assert "messages" in columns
    assert count == 0


def test_drop_obsolete_conversation_indexes():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE conversations (
                    session_id VARCHAR(255) PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_conversations_title_session ON conversations (user_id)"
            )
        )
        drop_obsolete_conversation_indexes(conn)
        index_names = {idx["name"] for idx in inspect(conn).get_indexes("conversations")}

    assert "idx_conversations_title_session" not in index_names
