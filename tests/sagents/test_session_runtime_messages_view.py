from sagents.context.messages.message import MessageChunk, MessageRole
from sagents import session_runtime


class FakeSessionManager:
    def __init__(self, messages):
        self._messages = messages

    def get_session_messages(self, session_id):
        return self._messages


def test_conversation_messages_view_filters_hidden_context_messages(monkeypatch):
    hidden_context = MessageChunk(
        role=MessageRole.USER.value,
        content=[
            {"type": "text", "text": "工具注入的图片上下文"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ],
        message_id="hidden-ctx",
        metadata={"hidden_from_chat": True, "tool_source": "analyze_image"},
    )
    visible_user = MessageChunk(
        role=MessageRole.USER.value,
        content="看这张图片",
        message_id="visible-user",
    )
    visible_assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="图片里是一张图表。",
        message_id="visible-assistant",
    )

    monkeypatch.setattr(
        session_runtime,
        "_global_session_manager",
        FakeSessionManager([visible_user, hidden_context, visible_assistant]),
    )

    view = session_runtime.build_conversation_messages_view("sess-1")

    assert [message["message_id"] for message in view["messages"]] == [
        "visible-user",
        "visible-assistant",
    ]


def test_conversation_messages_view_filters_self_check_diagnostic_without_metadata(
    monkeypatch,
):
    self_check_context = MessageChunk(
        role=MessageRole.USER.value,
        content=(
            '<runtime_diagnostic source="sage_self_check" generated_by="system">\n'
            "Self-check found issues\n"
            "</runtime_diagnostic>"
        ),
        message_id="self-check",
    )
    visible_assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="继续执行后的正常回复。",
        message_id="visible-assistant",
    )

    monkeypatch.setattr(
        session_runtime,
        "_global_session_manager",
        FakeSessionManager([self_check_context, visible_assistant]),
    )

    view = session_runtime.build_conversation_messages_view("sess-1")

    assert [message["message_id"] for message in view["messages"]] == [
        "visible-assistant",
    ]
