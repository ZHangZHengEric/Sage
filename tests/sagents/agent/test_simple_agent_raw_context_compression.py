from types import SimpleNamespace

import pytest

from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager


def _msg(
    role: str,
    content: str,
    message_type: str,
    tool_call_id: str | None = None,
) -> MessageChunk:
    return MessageChunk(
        role=role,
        content=content,
        message_type=message_type,
        tool_call_id=tool_call_id,
    )


@pytest.mark.asyncio
async def test_persistent_raw_context_compression_yields_tool_messages(monkeypatch):
    agent = SimpleAgent(model=None, model_config={})
    raw_messages = [
        _msg(MessageRole.SYSTEM.value, "system", MessageType.SYSTEM.value),
        _msg(MessageRole.USER.value, "please continue", MessageType.USER_INPUT.value),
        _msg(
            MessageRole.ASSISTANT.value,
            "old output",
            MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    tool_call = _msg(MessageRole.ASSISTANT.value, "", MessageType.TOOL_CALL.value)
    tool_call.tool_calls = [
        {
            "id": "auto_compress_test",
            "type": "function",
            "function": {
                "name": "compress_conversation_history",
                "arguments": '{"session_id": "sess-test"}',
            },
        }
    ]
    tool_result = _msg(
        MessageRole.TOOL.value,
        "历史已压缩",
        MessageType.TOOL_CALL_RESULT.value,
        tool_call_id="auto_compress_test",
    )
    tool_result.metadata = {
        "tool_name": "compress_conversation_history",
        "auto_generated": True,
        "status": "success",
    }
    compacted_messages = [raw_messages[1], tool_call, tool_result]

    async def fake_compress(messages, session_id):
        assert messages == raw_messages
        assert session_id == "sess-test"
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.MessageManager.extract_messages_for_inference",
        lambda messages: compacted_messages,
    )
    token_lengths = iter([1_000_001, 500])
    monkeypatch.setattr(
        "sagents.agent.simple_agent.MessageManager.calculate_messages_token_length",
        lambda messages: next(token_lengths),
    )

    (
        result_messages,
        emitted_chunks,
        still_over_limit,
    ) = await agent._persistently_compress_raw_messages_if_needed(
        raw_messages,
        session_id="sess-test",
        limit=1_000_000,
        force=True,
    )

    assert result_messages == compacted_messages
    assert emitted_chunks == [tool_call, tool_result]
    assert still_over_limit is False


@pytest.mark.asyncio
async def test_persistent_raw_context_compression_writes_anchor_to_message_manager(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={})
    message_manager = MessageManager()
    raw_messages = [
        _msg(MessageRole.USER.value, "please continue", MessageType.USER_INPUT.value),
        _msg(
            MessageRole.ASSISTANT.value,
            "old output",
            MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    message_manager.add_messages(raw_messages)

    tool_call = _msg(MessageRole.ASSISTANT.value, "", MessageType.TOOL_CALL.value)
    tool_call.tool_calls = [
        {
            "id": "auto_compress_test",
            "type": "function",
            "function": {
                "name": "compress_conversation_history",
                "arguments": '{"session_id": "sess-test"}',
            },
        }
    ]
    tool_result = _msg(
        MessageRole.TOOL.value,
        "历史已压缩",
        MessageType.TOOL_CALL_RESULT.value,
        tool_call_id="auto_compress_test",
    )
    tool_result.metadata = {
        "tool_name": "compress_conversation_history",
        "auto_generated": True,
        "status": "success",
    }

    async def fake_compress(messages, session_id):
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)
    monkeypatch.setattr(
        "sagents.agent.simple_agent.MessageManager.extract_messages_for_inference",
        lambda messages: [raw_messages[0], tool_call, tool_result],
    )
    token_lengths = iter([1_000_001, 500])
    monkeypatch.setattr(
        "sagents.agent.simple_agent.MessageManager.calculate_messages_token_length",
        lambda messages: next(token_lengths),
    )

    await agent._persistently_compress_raw_messages_if_needed(
        raw_messages,
        session_id="sess-test",
        limit=1_000_000,
        force=True,
        message_manager=message_manager,
    )

    assert message_manager.messages[-2:] == [tool_call, tool_result]
    assert message_manager.active_start_index == len(message_manager.messages) - 2


@pytest.mark.asyncio
async def test_persistent_raw_context_compression_handles_real_100k_plus_context(
    monkeypatch,
):
    configured_limit = 100_000
    agent = SimpleAgent(model=None, model_config={})
    message_manager = MessageManager()
    raw_messages = [
        _msg(MessageRole.USER.value, "continue the task", MessageType.USER_INPUT.value),
        _msg(
            MessageRole.ASSISTANT.value,
            "A" * 600_000,
            MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    message_manager.add_messages(raw_messages)
    raw_tokens = MessageManager.calculate_messages_token_length(raw_messages)
    assert raw_tokens > configured_limit

    tool_call = _msg(MessageRole.ASSISTANT.value, "", MessageType.TOOL_CALL.value)
    tool_call.tool_calls = [
        {
            "id": "auto_compress_100k",
            "type": "function",
            "function": {
                "name": "compress_conversation_history",
                "arguments": '{"session_id": "sess-100k"}',
            },
        }
    ]
    tool_result = _msg(
        MessageRole.TOOL.value,
        "压缩摘要：旧的大段 assistant 历史已经被总结。",
        MessageType.TOOL_CALL_RESULT.value,
        tool_call_id="auto_compress_100k",
    )
    tool_result.metadata = {
        "tool_name": "compress_conversation_history",
        "auto_generated": True,
        "status": "success",
    }

    async def fake_compress(messages, session_id):
        assert session_id == "sess-100k"
        assert (
            MessageManager.calculate_messages_token_length(messages) > configured_limit
        )
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    (
        result_messages,
        emitted_chunks,
        still_over_limit,
    ) = await agent._persistently_compress_raw_messages_if_needed(
        raw_messages,
        session_id="sess-100k",
        limit=configured_limit,
        force=True,
        message_manager=message_manager,
    )

    assert emitted_chunks == [tool_call, tool_result]
    assert still_over_limit is False
    assert (
        MessageManager.calculate_messages_token_length(result_messages)
        < configured_limit
    )
    assert raw_messages[1] not in result_messages
    assert message_manager.messages[-2:] == [tool_call, tool_result]
    assert message_manager.active_start_index == len(message_manager.messages) - 2


@pytest.mark.asyncio
async def test_execute_loop_compresses_real_oversized_raw_context_before_llm(
    monkeypatch,
):
    agent = SimpleAgent(
        model=None,
        model_config={
            "max_model_len": 128_000,
            "persistent_compression_threshold": 100_000,
        },
    )
    message_manager = MessageManager()
    raw_messages = [
        _msg(MessageRole.USER.value, "continue the task", MessageType.USER_INPUT.value),
        _msg(
            MessageRole.ASSISTANT.value,
            "A" * 600_000,
            MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    message_manager.add_messages(raw_messages)
    raw_tokens = MessageManager.calculate_messages_token_length(raw_messages)
    assert raw_tokens > 128_000

    session_context = SimpleNamespace(
        session_id=None,
        agent_config={"max_loop_count": 3},
        audit_status={},
        message_manager=message_manager,
        get_language=lambda: "zh",
    )
    tool_call = _msg(MessageRole.ASSISTANT.value, "", MessageType.TOOL_CALL.value)
    tool_call.tool_calls = [
        {
            "id": "auto_compress_loop",
            "type": "function",
            "function": {
                "name": "compress_conversation_history",
                "arguments": '{"session_id": "sess-loop"}',
            },
        }
    ]
    tool_result = _msg(
        MessageRole.TOOL.value,
        "压缩摘要：主循环中的旧历史已经被总结。",
        MessageType.TOOL_CALL_RESULT.value,
        tool_call_id="auto_compress_loop",
    )
    tool_result.metadata = {
        "tool_name": "compress_conversation_history",
        "auto_generated": True,
        "status": "success",
    }
    llm_inputs = []

    async def fake_compress(messages, session_id):
        assert session_id == "sess-loop"
        assert raw_messages[1] in messages
        yield [tool_call]
        yield [tool_result]

    async def fake_call_llm_and_process_response(
        messages_input,
        tools_json,
        tool_manager,
        session_id,
        force_tool_choice_required=False,
        force_tool_choice_auto=False,
    ):
        llm_inputs.append(messages_input)
        yield (
            [
                _msg(
                    MessageRole.ASSISTANT.value,
                    "done",
                    MessageType.ASSISTANT_TEXT.value,
                )
            ],
            True,
        )

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)
    monkeypatch.setattr(
        agent,
        "_call_llm_and_process_response",
        fake_call_llm_and_process_response,
    )

    yielded_chunks = []
    async for chunks in agent._execute_loop(
        messages_input=raw_messages,
        tools_json=[],
        tool_manager=None,
        session_id="sess-loop",
        session_context=session_context,
    ):
        yielded_chunks.extend(chunks)

    assert yielded_chunks[:2] == [tool_call, tool_result]
    assert len(llm_inputs) == 1
    assert raw_messages[1] not in llm_inputs[0]
    assert MessageManager.calculate_messages_token_length(llm_inputs[0]) < 128_000
    assert message_manager.messages[-2:] == [tool_call, tool_result]
    assert message_manager.active_start_index == len(message_manager.messages) - 2


def test_persistent_compression_threshold_can_be_configured_from_agent_config():
    agent = SimpleAgent(model=None, model_config={"max_model_len": 200_000})
    session_context = SimpleNamespace(
        agent_config={"persistent_compression_threshold": 123_456}
    )

    assert (
        agent._resolve_persistent_compression_threshold(session_context, 1_000_000)
        == 123_456
    )


def test_persistent_compression_threshold_can_be_configured_from_model_config():
    agent = SimpleAgent(
        model=None,
        model_config={
            "max_model_len": 300_000,
            "persistent_compression_threshold": 234_567,
        },
    )
    session_context = SimpleNamespace(agent_config={})

    assert (
        agent._resolve_persistent_compression_threshold(session_context, 1_000_000)
        == 234_567
    )


def test_persistent_compression_threshold_can_be_configured_from_env(monkeypatch):
    monkeypatch.setenv("SAGE_PERSISTENT_COMPRESSION_THRESHOLD", "34567")
    agent = SimpleAgent(model=None, model_config={"max_model_len": 64_000})
    session_context = SimpleNamespace(agent_config={})

    assert (
        agent._resolve_persistent_compression_threshold(session_context, 1_000_000)
        == 34_567
    )


def test_persistent_compression_threshold_is_capped_by_max_model_len():
    agent = SimpleAgent(
        model=None,
        model_config={
            "max_model_len": 64_000,
            "persistent_compression_threshold": 100_000,
        },
    )
    session_context = SimpleNamespace(agent_config={})

    assert (
        agent._resolve_persistent_compression_threshold(session_context, 1_000_000)
        == 64_000
    )


def test_max_model_input_len_defaults_to_max_model_len():
    agent = SimpleAgent(model=None, model_config={"max_model_len": 128_000})

    assert agent.max_model_input_len == 128_000


def test_max_model_input_len_is_capped_by_max_model_len():
    agent = SimpleAgent(
        model=None,
        model_config={"max_model_len": 128_000, "max_model_input_len": 2_000_000},
    )

    assert agent.max_model_input_len == 128_000
