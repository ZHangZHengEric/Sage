import json
from types import SimpleNamespace

import pytest

from common.services import conversation_service
from common.services.conversation_service import _find_last_user_message_index
from sagents import session_runtime
from sagents.context.messages.message import MessageChunk, MessageRole


def test_find_last_user_message_skips_hidden_context_messages():
    messages = [
        {"role": "user", "content": "真正的用户输入", "message_id": "u1"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "工具注入的图片上下文"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/a.png"},
                },
            ],
            "message_id": "hidden-ctx",
            "metadata": {"hidden_from_chat": True, "tool_source": "analyze_image"},
        },
    ]

    assert _find_last_user_message_index(messages) == 0


@pytest.mark.asyncio
async def test_get_conversation_messages_uses_client_visible_view(monkeypatch):
    conversation = SimpleNamespace(
        session_id="main-session",
        agent_id="agent-1",
        agent_name="Agent",
        title="Title",
        created_at="created",
        updated_at="updated",
    )

    class FakeDao:
        async def get_by_session_id(self, session_id):
            assert session_id == "main-session"
            return conversation

    class FakeManager:
        def get(self, session_id):
            return SimpleNamespace()

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service,
        "build_conversation_messages_view",
        lambda session_id: {
            "conversation_id": session_id,
            "messages": [
                {"role": "user", "content": "visible", "message_id": "visible"}
            ],
        },
    )
    monkeypatch.setattr(
        conversation_service,
        "_get_stream_manager",
        lambda: SimpleNamespace(get_history_length=lambda session_id: 3),
    )

    result = await conversation_service.get_conversation_messages("main-session")

    assert [message["message_id"] for message in result["messages"]] == ["visible"]
    assert result["message_count"] == 1
    assert result["next_stream_index"] == 3
    assert result["conversation_info"]["title"] == "Title"


@pytest.mark.asyncio
@pytest.mark.parametrize("session_kind", ["disk-session", "child-session"])
async def test_get_conversation_messages_without_conversation_record(
    monkeypatch, session_kind
):
    context = SimpleNamespace(
        agent_id="agent-context",
        agent_config={"agent_id": "agent-config", "name": "Restored Agent"},
    )
    restored_session = SimpleNamespace(
        get_context=lambda: context,
        get_start_time=lambda: 123.0,
        end_time=456.0,
    )

    class FakeDao:
        async def get_by_session_id(self, session_id):
            return None

    class FakeManager:
        def get(self, session_id):
            assert session_id == session_kind
            return restored_session

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service,
        "build_conversation_messages_view",
        lambda session_id: {
            "conversation_id": session_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": "restored",
                    "message_id": "restored-message",
                }
            ],
        },
    )
    monkeypatch.setattr(
        conversation_service,
        "_get_stream_manager",
        lambda: SimpleNamespace(get_history_length=lambda session_id: 0),
    )

    result = await conversation_service.get_conversation_messages(session_kind)

    assert result["conversation_id"] == session_kind
    assert result["conversation_info"] == {
        "session_id": session_kind,
        "agent_id": "agent-config",
        "agent_name": "Restored Agent",
        "title": "",
        "created_at": 123.0,
        "updated_at": 456.0,
    }
    assert result["messages"][0]["message_id"] == "restored-message"


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_404_only_when_session_is_absent(
    monkeypatch,
):
    class FakeDao:
        async def get_by_session_id(self, session_id):
            return SimpleNamespace(session_id=session_id)

    class FakeManager:
        def get(self, session_id):
            return None

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        conversation_service, "_is_desktop_mode", lambda: False
    )

    with pytest.raises(conversation_service.SageHTTPException) as exc_info:
        await conversation_service.get_conversation_messages("missing-session")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_conversation_messages_restores_disk_child_and_preserves_ledger(
    monkeypatch, tmp_path
):
    session_id = "disk-child"
    session_root = tmp_path / "sessions"
    session_workspace = (
        session_root / "parent-session" / "sub_sessions" / session_id
    )
    session_workspace.mkdir(parents=True)
    raw_messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content="visible",
            message_id="visible",
        ).to_dict(),
        MessageChunk(
            role=MessageRole.USER.value,
            content="internal self-check",
            message_id="hidden-self-check",
            metadata={"hidden_from_chat": True},
        ).to_dict(),
        MessageChunk(
            role=MessageRole.USER.value,
            content="internal tool parse",
            message_id="hidden-tool-parse",
            metadata={"hide_from_chat": True},
        ).to_dict(),
        MessageChunk(
            role=MessageRole.USER.value,
            content="internal repeat loop",
            message_id="hidden-repeat-loop",
            metadata={"sse_visible": False},
        ).to_dict(),
    ]
    messages_path = session_workspace / "messages.json"
    messages_path.write_text(json.dumps(raw_messages), encoding="utf-8")
    manager = session_runtime.SessionManager(str(session_root), enable_obs=False)

    class FakeDao:
        async def get_by_session_id(self, requested_session_id):
            assert requested_session_id == session_id
            return None

    monkeypatch.setattr(conversation_service, "ConversationDao", FakeDao)
    monkeypatch.setattr(
        conversation_service, "get_global_session_manager", lambda: manager
    )
    monkeypatch.setattr(session_runtime, "_global_session_manager", manager)
    monkeypatch.setattr(
        conversation_service,
        "_get_stream_manager",
        lambda: SimpleNamespace(get_history_length=lambda requested_session_id: 0),
    )

    result = await conversation_service.get_conversation_messages(session_id)

    assert [message["message_id"] for message in result["messages"]] == ["visible"]
    assert result["conversation_info"] == {
        "session_id": session_id,
        "agent_id": "",
        "agent_name": "",
        "title": "",
        "created_at": "",
        "updated_at": "",
    }
    assert json.loads(messages_path.read_text(encoding="utf-8")) == raw_messages
