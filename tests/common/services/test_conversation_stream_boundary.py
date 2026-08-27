import asyncio
from types import SimpleNamespace

from common.services import conversation_service


def test_get_stream_manager_uses_common_stream_manager(monkeypatch):
    manager = object()

    class FakeStreamManager:
        @classmethod
        def get_instance(cls):
            return manager

    monkeypatch.setattr(conversation_service, "StreamManager", FakeStreamManager)

    assert conversation_service._get_stream_manager() is manager


def test_interrupt_session_stops_shared_stream_once(monkeypatch):
    stop_calls = []

    class FakeStreamManager:
        @classmethod
        def get_instance(cls):
            return cls()

        async def stop_session(self, session_id):
            stop_calls.append(session_id)

    async def persist_session(_session_id):
        return None

    live_session = SimpleNamespace(request_interrupt=lambda _message: True)
    session_manager = SimpleNamespace(get_live_session=lambda _session_id: live_session)
    monkeypatch.setattr(
        conversation_service,
        "get_global_session_manager",
        lambda: session_manager,
    )
    monkeypatch.setattr(
        conversation_service,
        "persist_session_state_with_cancel_protection",
        persist_session,
    )
    monkeypatch.setattr(conversation_service, "StreamManager", FakeStreamManager)
    monkeypatch.setattr(conversation_service, "_is_desktop_mode", lambda: False)

    result = asyncio.run(conversation_service.interrupt_session("session-1"))

    assert result == {"session_id": "session-1"}
    assert stop_calls == ["session-1"]
