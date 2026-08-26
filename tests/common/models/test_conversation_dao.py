from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

from common.core.client.db import SessionManager, register_db_getter, sync_database_schema
from common.models.base import Base
from common.models.conversation import Conversation, ConversationDao
from common.services import conversation_service


@pytest.fixture
async def conversation_db():
    manager = SessionManager(SimpleNamespace(db_type="memory"))
    await manager.init_conn()

    async def get_test_db():
        return manager

    register_db_getter(get_test_db)
    async with manager._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield manager
    finally:
        register_db_getter(None)
        await manager.close()


def _conversation_columns(sync_conn):
    return {col["name"] for col in inspect(sync_conn).get_columns("conversations")}


@pytest.mark.asyncio
async def test_conversation_search_matches_partial_session_id(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_abc123_xyz",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Budget planning",
    )
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_other",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Roadmap",
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        search="abc123",
    )

    assert total == 1
    assert [conversation.session_id for conversation in conversations] == [
        "session_abc123_xyz"
    ]


@pytest.mark.asyncio
async def test_conversation_search_still_matches_title(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_budget",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Budget planning",
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        search="Budget",
    )

    assert total == 1
    assert conversations[0].session_id == "session_budget"


@pytest.mark.asyncio
async def test_conversation_table_does_not_store_messages(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_with_counts",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Long chat",
    )
    await dao.update_conversation_counts(
        "session_with_counts",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "content": "{}"},
        ],
    )

    async with conversation_db._engine.begin() as conn:
        columns = await conn.run_sync(_conversation_columns)
        row = (
            await conn.execute(
                text(
                    "SELECT message_count, user_count, agent_count FROM conversations "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": "session_with_counts"},
            )
        ).one()

    conversation = await dao.get_by_session_id("session_with_counts")

    assert "messages" not in columns
    assert "messages" not in Conversation.__table__.columns
    assert row == (3, 1, 1)
    assert conversation is not None
    assert conversation.message_count == 3
    assert conversation.get_message_count() == {"user_count": 1, "agent_count": 1}


@pytest.mark.asyncio
async def test_conversation_list_can_skip_message_counts(conversation_db, monkeypatch):
    monkeypatch.setattr(conversation_service, "_build_session_trace_id", lambda _: None)
    monkeypatch.setattr(
        conversation_service, "_build_session_trace_url", lambda _: None
    )

    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_with_messages",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Long chat",
    )
    await dao.update_conversation_counts(
        "session_with_messages",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )

    conversations, total = await dao.get_conversations_paginated(user_id="user-1")
    result = conversation_service.build_conversation_list_result(
        conversations=conversations,
        total_count=total,
        page=1,
        page_size=10,
        include_message_counts=False,
    )

    assert total == 1
    assert conversations[0].message_count == 2
    assert result["list"][0]["message_count"] == 0
    assert result["list"][0]["user_count"] == 0
    assert result["list"][0]["agent_count"] == 0


@pytest.mark.asyncio
async def test_conversation_pagination_orders_by_updated_at(conversation_db):
    dao = ConversationDao()
    for index in range(3):
        await dao.save_conversation(
            user_id="user-1",
            session_id=f"session-{index}",
            agent_id="agent-1",
            agent_name="Agent One",
            title=f"Chat {index}",
        )

    first_page, total = await dao.get_conversations_paginated(
        user_id="user-1",
        page=1,
        page_size=2,
    )
    second_page, _ = await dao.get_conversations_paginated(
        user_id="user-1",
        page=2,
        page_size=2,
    )

    assert total == 3
    assert [item.session_id for item in first_page] == ["session-2", "session-1"]
    assert [item.session_id for item in second_page] == ["session-0"]


@pytest.mark.asyncio
async def test_conversation_sort_by_messages_uses_stored_count(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="short",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Short",
    )
    await dao.update_conversation_counts(
        "short",
        [{"role": "user", "content": "a"}],
    )
    await dao.save_conversation(
        user_id="user-1",
        session_id="long",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Long",
    )
    await dao.update_conversation_counts(
        "long",
        [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ],
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        sort_by="messages",
    )

    assert total == 2
    assert [item.session_id for item in conversations] == ["long", "short"]
    assert [item.message_count for item in conversations] == [3, 1]


@pytest.mark.asyncio
async def test_list_result_uses_stored_total_and_role_counts(
    conversation_db, monkeypatch
):
    monkeypatch.setattr(conversation_service, "_build_session_trace_id", lambda _: None)
    monkeypatch.setattr(
        conversation_service, "_build_session_trace_url", lambda _: None
    )

    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Chat",
    )
    await dao.update_conversation_counts(
        "session-1",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "content": "{}"},
        ],
    )
    conversations, total = await dao.get_conversations_paginated(user_id="user-1")
    result = conversation_service.build_conversation_list_result(
        conversations=conversations,
        total_count=total,
        page=1,
        page_size=10,
    )

    assert result["list"][0]["message_count"] == 3
    assert result["list"][0]["user_count"] == 1
    assert result["list"][0]["agent_count"] == 1


@pytest.mark.asyncio
async def test_persist_session_state_writes_counts_not_messages(
    conversation_db, monkeypatch
):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Chat",
    )
    monkeypatch.setattr(
        conversation_service,
        "_load_session_raw_messages",
        lambda session_id: [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: None
    )

    await conversation_service.persist_session_state("session-1")
    conversation = await dao.get_by_session_id("session-1")

    async with conversation_db._engine.begin() as conn:
        columns = await conn.run_sync(_conversation_columns)

    assert "messages" not in columns
    assert conversation is not None
    assert conversation.message_count == 2
    assert conversation.get_message_count() == {"user_count": 1, "agent_count": 1}


def test_sync_database_schema_keeps_legacy_messages_column_without_rewrite():
    from sqlalchemy import create_engine

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
        conn.execute(
            text(
                """
                INSERT INTO conversations (
                    session_id, user_id, agent_id, agent_name, title, messages
                ) VALUES (
                    'legacy-1', 'user-1', 'agent-1', 'Agent', 'Old chat',
                    '[{"role":"user"},{"role":"assistant"},{"role":"tool"}]'
                )
                """
            )
        )
        sync_database_schema(conn, Base)
        columns = {col["name"] for col in inspect(conn).get_columns("conversations")}
        row = conn.execute(
            text(
                "SELECT message_count, user_count, agent_count FROM conversations "
                "WHERE session_id = 'legacy-1'"
            )
        ).one()

    assert "messages" in columns
    assert "message_count" in columns
    assert "user_count" in columns
    assert "agent_count" in columns
    assert row.message_count == 0
    assert row.user_count == 0
    assert row.agent_count == 0
