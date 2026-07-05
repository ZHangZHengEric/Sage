from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_execution_error_message_type,
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
