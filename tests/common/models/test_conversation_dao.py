from types import SimpleNamespace

import pytest

from common.core.client.db import SessionManager, register_db_getter
from common.models.base import Base
from common.models.conversation import ConversationDao
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


@pytest.mark.asyncio
async def test_conversation_search_matches_partial_session_id(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_abc123_xyz",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Budget planning",
        messages=[],
    )
    await dao.save_conversation(
        user_id="user-1",
        session_id="session_other",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Roadmap",
        messages=[],
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
        messages=[],
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        search="Budget",
    )

    assert total == 1
    assert conversations[0].session_id == "session_budget"


@pytest.mark.asyncio
async def test_conversation_list_can_skip_message_counts_without_loading_messages(
    conversation_db,
    monkeypatch,
):
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
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        include_messages=False,
    )
    result = conversation_service.build_conversation_list_result(
        conversations=conversations,
        total_count=total,
        page=1,
        page_size=10,
        include_message_counts=False,
    )

    assert total == 1
    assert "messages" not in conversations[0].__dict__
    assert conversations[0].message_count == 2
    assert result["list"][0]["message_count"] == 0
    assert result["list"][0]["user_count"] == 0
    assert result["list"][0]["agent_count"] == 0


@pytest.mark.asyncio
async def test_conversation_pagination_orders_by_updated_at_without_loading_messages(
    conversation_db,
):
    dao = ConversationDao()
    for index in range(3):
        await dao.save_conversation(
            user_id="user-1",
            session_id=f"session-{index}",
            agent_id="agent-1",
            agent_name="Agent One",
            title=f"Chat {index}",
            messages=[{"role": "user", "content": "x" * 2000}],
        )

    first_page, total = await dao.get_conversations_paginated(
        user_id="user-1",
        page=1,
        page_size=2,
        include_messages=False,
    )
    second_page, _ = await dao.get_conversations_paginated(
        user_id="user-1",
        page=2,
        page_size=2,
        include_messages=False,
    )

    assert total == 3
    assert [item.session_id for item in first_page] == ["session-2", "session-1"]
    assert [item.session_id for item in second_page] == ["session-0"]
    assert all("messages" not in item.__dict__ for item in first_page + second_page)


@pytest.mark.asyncio
async def test_conversation_sort_by_messages_uses_stored_count(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="short",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Short",
        messages=[{"role": "user", "content": "a"}],
    )
    await dao.save_conversation(
        user_id="user-1",
        session_id="long",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Long",
        messages=[
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ],
    )

    conversations, total = await dao.get_conversations_paginated(
        user_id="user-1",
        sort_by="messages",
        include_messages=False,
    )

    assert total == 2
    assert [item.session_id for item in conversations] == ["long", "short"]
    assert [item.message_count for item in conversations] == [3, 1]


@pytest.mark.asyncio
async def test_update_conversation_messages_refreshes_message_count(conversation_db):
    dao = ConversationDao()
    await dao.save_conversation(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        title="Chat",
        messages=[],
    )

    updated = await dao.update_conversation_messages(
        "session-1",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    conversation = await dao.get_by_session_id("session-1")

    assert updated is True
    assert conversation is not None
    assert conversation.message_count == 2
