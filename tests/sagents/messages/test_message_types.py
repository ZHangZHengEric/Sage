from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_execution_error_message_type,
    is_message_client_visible,
)
from sagents.context.messages.message_manager import MessageManager


def test_agent_execution_error_preserves_assistant_content_contract():
    message = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="Tool was not provided.",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
    )

    payload = message.to_dict()

    assert payload["role"] == "assistant"
    assert payload["content"] == "Tool was not provided."
    assert payload["type"] == MessageType.AGENT_EXECUTION_ERROR.value
    assert payload["message_type"] == MessageType.AGENT_EXECUTION_ERROR.value


def test_execution_error_helper_covers_legacy_and_agent_execution_errors():
    assert is_execution_error_message_type(MessageType.ERROR.value)
    assert is_execution_error_message_type(MessageType.AGENT_EXECUTION_ERROR.value)
    assert not is_execution_error_message_type(MessageType.ASSISTANT_TEXT.value)


def test_agent_execution_error_is_tagged_as_runtime_diagnostic_for_llm_request():
    message = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="自检发现以下问题，需要先修复后再继续。",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
    )

    payload = MessageManager.convert_messages_to_dict_for_request([message])

    assert payload[0]["role"] == "assistant"
    assert (
        '<runtime_diagnostic source="sage_runtime" generated_by="system">'
        in payload[0]["content"]
    )
    assert "Sage runtime diagnostic / Sage 运行时诊断" in payload[0]["content"]
    assert "not text authored by the assistant/agent" in payload[0]["content"]
    assert "自检发现以下问题" in payload[0]["content"]


def test_agent_execution_error_runtime_diagnostic_tag_is_not_duplicated():
    content = (
        '<runtime_diagnostic source="sage_self_check" generated_by="system">\n'
        "already tagged\n"
        "</runtime_diagnostic>"
    )
    message = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
    )

    payload = MessageManager.convert_messages_to_dict_for_request([message])

    assert payload[0]["content"] == content


def test_next_request_message_is_included_only_while_pending():
    message = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="retry with the expansion tool",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    pending = MessageManager.convert_messages_to_dict_for_request([message])
    assert len(pending) == 1

    message.metadata["llm_state"] = "consumed"
    consumed = MessageManager.convert_messages_to_dict_for_request([message])
    assert consumed == []


def test_client_visibility_contract_accepts_chunks_and_serialized_messages():
    visible = MessageChunk(role=MessageRole.ASSISTANT.value, content="visible")
    hidden = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="internal",
        metadata={"sse_visible": False},
    )

    assert is_message_client_visible(visible) is True
    assert is_message_client_visible(visible.to_dict()) is True
    assert is_message_client_visible(hidden) is False
    assert is_message_client_visible(hidden.to_dict()) is False


def test_hidden_durable_image_context_remains_in_llm_request():
    message = MessageChunk(
        role=MessageRole.USER.value,
        content=[
            {"type": "text", "text": "inspect this image"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ],
        metadata={
            "hidden_from_chat": True,
            "sse_visible": False,
            "llm_scope": "durable",
        },
    )

    payload = MessageManager.convert_messages_to_dict_for_request([message])
    assert len(payload) == 1
    assert payload[0]["content"] == message.content


def test_legacy_hidden_tool_diagnostic_is_not_reused():
    message = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="Tool was not provided.",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"runtime_notice": "unavailable_tool_rejected"},
    )

    assert MessageManager.convert_messages_to_dict_for_request([message]) == []


def test_rejected_streamed_tool_pair_stays_out_of_llm_request():
    user = MessageChunk(role=MessageRole.USER.value, content="run")
    call = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        tool_calls=[
            {
                "id": "call_bad",
                "type": "function",
                "function": {"name": "forbidden_tool", "arguments": "{}"},
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    rejected = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"status":"rejected"}',
        tool_call_id="call_bad",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"streamed_tool_rejected": True},
    )
    diagnostic = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="use tool expansion",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    payload = MessageManager.convert_messages_to_dict_for_request(
        [user, call, rejected, diagnostic]
    )

    assert [message["role"] for message in payload] == ["user", "assistant"]
    assert "tool_calls" not in payload[1]
    assert "runtime_diagnostic" in payload[1]["content"]
