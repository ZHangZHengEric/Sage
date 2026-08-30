import asyncio
from types import SimpleNamespace

import pytest

from common.services import conversation_service


@pytest.mark.asyncio
async def test_delete_conversation_removes_runtime_before_database(monkeypatch):
    events = []
    conversation = SimpleNamespace(user_id="user-1")

    class FakeDao:
        async def get_by_session_id(self, session_id):
            assert session_id == "session-1"
            return conversation

        async def delete_conversation(self, session_id):
            events.append(("database", session_id))
            return True

    class FakeManager:
        def interrupt_session(self, session_id, message):
            events.append(("interrupt", message))
            return True

        async def delete_session(self, session_id):
            events.append(("runtime", session_id))

    class FakeStreamManager:
        async def stop_session(self, session_id):
            events.append(("stream", session_id))

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service, "_get_stream_manager", lambda: FakeStreamManager()
    )

    result = await conversation_service.delete_conversation(
        "session-1", user_id="user-1"
    )

    assert result == "session-1"
    assert [event[0] for event in events] == [
        "interrupt",
        "stream",
        "runtime",
        "database",
    ]


@pytest.mark.asyncio
async def test_delete_conversation_waits_for_pending_persistence(monkeypatch):
    events = []
    allow_persistence = asyncio.Event()

    class FakeDao:
        async def get_by_session_id(self, session_id):
            return SimpleNamespace(user_id="user-1")

        async def delete_conversation(self, session_id):
            events.append("database")
            return True

    class FakeManager:
        def interrupt_session(self, session_id, message):
            return False

        async def delete_session(self, session_id):
            events.append("runtime")

    class FakeStreamManager:
        async def stop_session(self, session_id):
            return None

    async def persist():
        await allow_persistence.wait()
        events.append("persistence")

    persistence_task = asyncio.create_task(persist())
    conversation_service._SESSION_PERSISTENCE_TASKS["session-1"] = persistence_task
    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service, "_get_stream_manager", lambda: FakeStreamManager()
    )

    delete_task = asyncio.create_task(
        conversation_service.delete_conversation("session-1", user_id="user-1")
    )
    await asyncio.sleep(0)
    assert events == []

    allow_persistence.set()
    await delete_task

    assert events == ["persistence", "runtime", "database"]
    conversation_service._SESSION_PERSISTENCE_TASKS.clear()


@pytest.mark.asyncio
async def test_delete_conversation_keeps_database_row_when_runtime_delete_fails(
    monkeypatch,
):
    database_deleted = False

    class FakeDao:
        async def get_by_session_id(self, session_id):
            return SimpleNamespace(user_id="user-1")

        async def delete_conversation(self, session_id):
            nonlocal database_deleted
            database_deleted = True
            return True

    class FakeManager:
        def interrupt_session(self, session_id, message):
            return False

        async def delete_session(self, session_id):
            raise OSError("disk busy")

    class FakeStreamManager:
        async def stop_session(self, session_id):
            return None

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service, "_get_stream_manager", lambda: FakeStreamManager()
    )
    monkeypatch.setattr(conversation_service, "_is_desktop_mode", lambda: False)

    with pytest.raises(conversation_service.SageHTTPException):
        await conversation_service.delete_conversation(
            "session-1", user_id="user-1"
        )

    assert database_deleted is False
