from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_execution_error_message_type,
)


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
