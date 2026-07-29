from types import SimpleNamespace

import pytest

from common.services import conversation_service


@pytest.mark.asyncio
async def test_delete_conversation_clears_only_its_runtime_environment(monkeypatch):
    calls = []

    class FakeDao:
        async def get_by_session_id(self, session_id):
            return SimpleNamespace(user_id="owner")

        async def delete_conversation(self, session_id):
            return True

    class FakeStore:
        async def clear_session(self, owner_id, session_id):
            calls.append((owner_id, session_id))
            return True

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_runtime_env_store", lambda: FakeStore()
    )

    assert await conversation_service.delete_conversation(
        "session-a", user_id="owner"
    ) == "session-a"
    assert calls == [("owner", "session-a")]


@pytest.mark.asyncio
async def test_delete_conversation_uses_authenticated_owner_when_record_is_unowned(
    monkeypatch,
):
    calls = []

    class FakeDao:
        async def get_by_session_id(self, session_id):
            return SimpleNamespace(user_id=None)

        async def delete_conversation(self, session_id):
            return True

    class FakeStore:
        async def clear_session(self, owner_id, session_id):
            calls.append((owner_id, session_id))
            return True

        async def clear_session_for_any_owner(self, session_id):
            raise AssertionError("authenticated deletion must use an exact owner")

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_runtime_env_store", lambda: FakeStore()
    )

    assert await conversation_service.delete_conversation(
        "session-a", user_id="authenticated-owner"
    ) == "session-a"
    assert calls == [("authenticated-owner", "session-a")]
