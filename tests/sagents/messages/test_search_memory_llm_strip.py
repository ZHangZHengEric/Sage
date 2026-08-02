"""Tests for keeping historical search_memory records out of LLM context."""

from copy import deepcopy

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import (
    MessageManager,
    SEARCH_MEMORY_TOOL_NAME,
)


def _tool_call(name: str, tool_call_id: str) -> dict:
    return {
        "id": tool_call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def _assistant_call(
    message_id: str,
    *tool_calls: dict,
    content: str | None = None,
) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        tool_calls=list(tool_calls),
        message_id=message_id,
        message_type=MessageType.TOOL_CALL.value,
    )


def _tool_result(
    message_id: str,
    tool_call_id: str,
    content: str = '{"status":"success"}',
) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.TOOL.value,
        content=content,
        tool_call_id=tool_call_id,
        message_id=message_id,
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )


def _user(message_id: str, content: str) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.USER.value,
        content=content,
        message_id=message_id,
    )


def test_inference_view_removes_completed_turn_search_memory_pair():
    messages = [
        _user("old-user", "first request"),
        _assistant_call(
            "old-search-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old"),
        ),
        _tool_result("old-search-result", "search-old"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="answer based on recalled context",
            message_id="old-answer",
        ),
        _user("current-user", "new request"),
    ]

    view = MessageManager.extract_messages_for_inference(messages)

    assert [msg.message_id for msg in view] == [
        "old-user",
        "old-answer",
        "current-user",
    ]


def test_inference_view_keeps_current_turn_search_memory_pair():
    messages = [
        _user("current-user", "new request"),
        _assistant_call(
            "current-search-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-current"),
        ),
        _tool_result("current-search-result", "search-current"),
    ]

    view = MessageManager.extract_messages_for_inference(messages)

    assert [msg.message_id for msg in view] == [
        "current-user",
        "current-search-call",
        "current-search-result",
    ]


def test_runtime_continuation_guidance_is_not_a_user_turn_boundary():
    messages = [
        _user("old-user", "first request"),
        _assistant_call(
            "old-search-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old"),
        ),
        _tool_result("old-search-result", "search-old"),
        _user("current-user", "new request"),
        _assistant_call(
            "current-search-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-current"),
        ),
        _tool_result("current-search-result", "search-current"),
        MessageChunk(
            role=MessageRole.USER.value,
            content=(
                "<runtime_continuation_guidance>"
                "internal note"
                "</runtime_continuation_guidance>"
            ),
            message_id="runtime-guidance",
            metadata={
                "inference_view_only": True,
                "runtime_continuation_guidance": True,
            },
        ),
    ]

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert [msg.message_id for msg in view] == [
        "old-user",
        "current-user",
        "current-search-call",
        "current-search-result",
        "runtime-guidance",
    ]


def test_strip_prunes_only_search_memory_from_mixed_tool_calls():
    messages = [
        _user("old-user", "first request"),
        _assistant_call(
            "mixed-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old"),
            _tool_call("file_read", "file-old"),
            content="I will inspect both sources.",
        ),
        _tool_result("search-result", "search-old"),
        _tool_result("file-result", "file-old", "file contents"),
        _user("current-user", "new request"),
    ]

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert [msg.message_id for msg in view] == [
        "old-user",
        "mixed-call",
        "file-result",
        "current-user",
    ]
    mixed_call = view[1]
    assert mixed_call.content == "I will inspect both sources."
    assert [tc["function"]["name"] for tc in mixed_call.tool_calls or []] == [
        "file_read"
    ]


def test_strip_keeps_assistant_text_when_search_memory_was_its_only_call():
    messages = [
        _assistant_call(
            "search-with-text",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old"),
            content="Searching prior context.",
        ),
        _tool_result("search-result", "search-old"),
        _user("current-user", "new request"),
    ]

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert [msg.message_id for msg in view] == [
        "search-with-text",
        "current-user",
    ]
    assert view[0].content == "Searching prior context."
    assert view[0].tool_calls is None


def test_strip_removes_multiple_historical_searches_including_error_result():
    messages = [
        _assistant_call(
            "search-call-1",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-1"),
        ),
        _tool_result("search-result-1", "search-1"),
        _assistant_call(
            "search-call-2",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-2"),
        ),
        _tool_result(
            "search-result-2",
            "search-2",
            content='{"status":"error"}',
        ),
        _user("current-user", "new request"),
    ]

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert [msg.message_id for msg in view] == ["current-user"]


def test_strip_without_user_boundary_leaves_messages_unchanged():
    messages = [
        _assistant_call(
            "search-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-1"),
        ),
        _tool_result("search-result", "search-1"),
    ]

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert view == messages


def test_strip_is_idempotent_and_does_not_mutate_ledger_messages():
    messages = [
        _user("old-user", "first request"),
        _assistant_call(
            "mixed-call",
            _tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old"),
            _tool_call("file_read", "file-old"),
        ),
        _tool_result("search-result", "search-old"),
        _tool_result("file-result", "file-old", "file contents"),
        _user("current-user", "new request"),
    ]
    original = deepcopy(messages)

    first = MessageManager.strip_historical_search_memory_from_llm_context(messages)
    second = MessageManager.strip_historical_search_memory_from_llm_context(first)

    assert second == first
    assert messages == original
    assert len(messages[1].tool_calls or []) == 2


def test_strip_supports_raw_dict_messages_without_mutating_them():
    messages = [
        {"role": "user", "content": "old request"},
        {
            "role": "assistant",
            "content": "Searching.",
            "tool_calls": [_tool_call(SEARCH_MEMORY_TOOL_NAME, "search-old")],
        },
        {
            "role": "tool",
            "content": '{"status":"success"}',
            "tool_call_id": "search-old",
        },
        {"role": "user", "content": "current request"},
    ]
    original = deepcopy(messages)

    view = MessageManager.strip_historical_search_memory_from_llm_context(messages)

    assert view == [
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "Searching."},
        {"role": "user", "content": "current request"},
    ]
    assert messages == original
