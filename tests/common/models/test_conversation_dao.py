from types import SimpleNamespace

import pytest

from common.core.client.db import SessionManager, register_db_getter
from common.models.base import Base
from common.models.conversation import ConversationDao


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
