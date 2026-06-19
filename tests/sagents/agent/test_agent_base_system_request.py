import pytest

from sagents.agent.common_agent import CommonAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def _message(role: str, content: str) -> MessageChunk:
    return MessageChunk(
        role=role,
        content=content,
        message_type=MessageType.SYSTEM.value
        if role == MessageRole.SYSTEM.value
        else MessageType.ASSISTANT_TEXT.value,
    )


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_uses_fresh_system_and_filters_stale_system(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [
            _message(MessageRole.SYSTEM.value, "fresh-stable"),
            _message(MessageRole.SYSTEM.value, "fresh-volatile"),
        ]

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            _message(MessageRole.SYSTEM.value, "stale-history-system"),
            _message(MessageRole.USER.value, "user payload"),
        ],
        extra_messages=[
            _message(MessageRole.SYSTEM.value, "stale-extra-system"),
            _message(MessageRole.ASSISTANT.value, "assistant payload"),
        ],
        custom_prefix="custom",
        language="zh",
        include_sections=["role_definition"],
    )

    assert [message.role for message in request_messages] == [
        MessageRole.SYSTEM.value,
        MessageRole.SYSTEM.value,
        MessageRole.USER.value,
        MessageRole.ASSISTANT.value,
    ]
    assert [message.content for message in request_messages] == [
        "fresh-stable",
        "fresh-volatile",
        "user payload",
        "assistant payload",
    ]
    assert captured["session_id"] == "sess"
    assert captured["custom_prefix"] == "custom"
    assert captured["language"] == "zh"
    assert captured["include_sections"] == ["role_definition"]


@pytest.mark.asyncio
async def test_prepare_llm_system_prompt_text_uses_same_fresh_segment_builder(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [
            _message(MessageRole.SYSTEM.value, "stable"),
            _message(MessageRole.SYSTEM.value, "volatile"),
        ]

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)

    system_prompt = await agent.prepare_llm_system_prompt_text(
        session_id="sess",
        system_prefix_override="override",
        language="en",
        include_sections=["system_context"],
    )

    assert system_prompt == "stablevolatile"
    assert captured["session_id"] == "sess"
    assert captured["system_prefix_override"] == "override"
    assert captured["language"] == "en"
    assert captured["include_sections"] == ["system_context"]
