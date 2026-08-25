from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageType
from sagents.context.messages.message_manager import MessageManager


def test_reasoning_only_message_chunk_round_trips() -> None:
    message = MessageChunk(
        role="assistant",
        reasoning_content="先分析，再行动。",
        message_type=MessageType.REASONING_CONTENT.value,
    )

    restored = MessageChunk.from_dict(message.to_dict())

    assert restored.content is None
    assert restored.reasoning_content == "先分析，再行动。"


def test_minimax_reasoning_details_round_trip_and_keep_latest_snapshot() -> None:
    message_id = "minimax-response"
    manager = MessageManager()
    manager.add_messages(
        MessageChunk(
            role="assistant",
            reasoning_content="先分析",
            reasoning_details=[{"type": "reasoning.text", "text": "先分析"}],
            message_id=message_id,
            message_type=MessageType.REASONING_CONTENT.value,
        )
    )
    manager.add_messages(
        MessageChunk(
            role="assistant",
            reasoning_content="，再回答",
            reasoning_details=[
                {"type": "reasoning.text", "text": "先分析，再回答"}
            ],
            message_id=message_id,
            message_type=MessageType.REASONING_CONTENT.value,
        )
    )

    restored = MessageChunk.from_dict(manager.messages[0].to_dict())

    assert restored.reasoning_content == "先分析，再回答"
    assert restored.reasoning_details == [
        {"type": "reasoning.text", "text": "先分析，再回答"}
    ]


def test_token_estimate_counts_content_and_reasoning_content(monkeypatch) -> None:
    monkeypatch.setattr(
        MessageManager,
        "calculate_str_token_length",
        staticmethod(lambda value: len(value or "")),
    )
    message = MessageChunk(
        role="assistant",
        content="answer",
        reasoning_content="reasoning",
    )

    assert MessageManager.calculate_message_token_length(message) == 15
    assert MessageManager.calculate_messages_token_length([message]) == 15
    assert MessageManager.calculate_message_token_components([message])["text_chars"] == 15


def test_message_manager_persists_one_assistant_message_per_model_response() -> None:
    message_id = "response-1"
    manager = MessageManager()

    manager.add_messages(
        MessageChunk(
            role="assistant",
            reasoning_content="need tools",
            message_id=message_id,
            message_type=MessageType.REASONING_CONTENT.value,
        )
    )
    manager.add_messages(
        MessageChunk(
            role="assistant",
            content="checking",
            message_id=message_id,
            message_type=MessageType.DO_SUBTASK_RESULT.value,
        )
    )
    manager.add_messages(
        MessageChunk(
            role="assistant",
            tool_calls=[
                {
                    "index": 0,
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                },
                {
                    "index": 1,
                    "id": "call-2",
                    "type": "function",
                    "function": {"name": "calendar", "arguments": "{}"},
                },
            ],
            message_id=message_id,
            message_type=MessageType.TOOL_CALL.value,
        )
    )

    assert len(manager.messages) == 1
    response = manager.messages[0]
    assert response.message_id == message_id
    assert response.message_type == MessageType.TOOL_CALL.value
    assert response.reasoning_content == "need tools"
    assert response.content == "checking"
    assert [tool_call["id"] for tool_call in response.tool_calls or []] == [
        "call-1",
        "call-2",
    ]


def test_deepseek_tool_request_coalesces_reasoning_into_assistant_message() -> None:
    messages = [
        {"role": "user", "content": "weather"},
        {"role": "assistant", "reasoning_content": "need tool"},
        {"role": "assistant", "content": "checking"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "sunny"},
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=True
    )

    assert len(result) == 3
    assert result[1]["reasoning_content"] == "need tool"
    assert result[1]["content"] == "checking"
    assert result[1]["tool_calls"][0]["id"] == "call-1"


def test_inference_view_fuses_reasoning_with_matching_tool_call() -> None:
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            reasoning_content="need tool",
            message_type=MessageType.REASONING_CONTENT.value,
        ),
        MessageChunk(role="assistant", content="checking"),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        ),
        MessageChunk(
            role="tool", content="sunny", tool_call_id="call-1"
        ),
    ]

    result = MessageManager.build_inference_view(messages)

    assert len(result) == 3
    assert result[1].reasoning_content == "need tool"
    assert result[1].content == "checking"
    assert result[1].tool_calls[0]["id"] == "call-1"


def test_inference_view_does_not_move_reasoning_between_model_responses() -> None:
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            reasoning_content="agent a reasoning",
            message_type=MessageType.REASONING_CONTENT.value,
            agent_name="agent-a",
            metadata={"llm_response_id": "response-a"},
        ),
        MessageChunk(
            role="assistant",
            content="agent a text",
            agent_name="agent-a",
            metadata={"llm_response_id": "response-a"},
        ),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
            agent_name="agent-b",
            metadata={"llm_response_id": "response-b"},
        ),
    ]

    result = MessageManager.build_inference_view(messages)

    assert [message.get_content() for message in result] == [
        "weather",
        "agent a text",
        "",
    ]
    assert result[2].tool_calls[0]["id"] == "call-b"
    assert result[2].reasoning_content is None


def test_legacy_inference_view_does_not_move_reasoning_between_agents() -> None:
    messages = [
        MessageChunk(
            role="assistant",
            reasoning_content="agent a reasoning",
            message_type=MessageType.REASONING_CONTENT.value,
            agent_name="agent-a",
        ),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
            agent_name="agent-b",
        ),
    ]

    result = MessageManager.build_inference_view(messages)

    assert len(result) == 1
    assert result[0].tool_calls[0]["id"] == "call-b"
    assert result[0].reasoning_content is None


def test_provider_coalescing_respects_model_response_identity() -> None:
    messages = [
        {
            "role": "assistant",
            "reasoning_content": "response a reasoning",
            "_sage_llm_response_id": "response-a",
        },
        {
            "role": "assistant",
            "content": "response a text",
            "_sage_llm_response_id": "response-a",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
            "_sage_llm_response_id": "response-b",
        },
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=True
    )

    assert result[0] == {"role": "assistant", "content": "response a text"}
    assert result[1]["tool_calls"][0]["id"] == "call-b"
    assert "reasoning_content" not in result[1]
    assert all("_sage_llm_response_id" not in message for message in result)


def test_deepseek_drops_reasoning_from_final_assistant_message() -> None:
    messages = [
        {"role": "assistant", "reasoning_content": "final thought"},
        {"role": "assistant", "content": "answer"},
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=True
    )

    assert result == [{"role": "assistant", "content": "answer"}]


def test_non_deepseek_keeps_visible_text_when_reasoning_precedes_tool_call() -> None:
    messages = [
        {"role": "assistant", "reasoning_content": "need tool"},
        {"role": "assistant", "content": "checking"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        },
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=False
    )

    assert result[0] == {"role": "assistant", "content": "checking"}
    assert result[1]["tool_calls"][0]["id"] == "call-1"
    assert all("reasoning_content" not in item for item in result)


def test_non_deepseek_keeps_canonical_tool_call_text_without_reasoning() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "I will check that now.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        }
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=False
    )
    result = AgentBase._remove_content_if_tool_calls(None, result)

    assert result[0] == {"role": "assistant", "content": "I will check that now."}
    assert result[1]["tool_calls"][0]["id"] == "call-1"
    assert "content" not in result[1]


def test_non_deepseek_or_no_tools_drops_reasoning_from_provider_history() -> None:
    messages = [
        {"role": "assistant", "reasoning_content": "private reasoning"},
        {"role": "assistant", "content": "answer"},
    ]

    result = AgentBase._coalesce_reasoning_content_messages(
        messages, preserve_reasoning=False
    )

    assert result == [{"role": "assistant", "content": "answer"}]


def test_legacy_reasoning_message_serializes_as_reasoning_field() -> None:
    legacy = MessageChunk(
        role="assistant",
        content="legacy reasoning",
        message_type=MessageType.REASONING_CONTENT.value,
    )

    assert MessageManager.convert_message_to_dict_for_request(legacy) == {
        "role": "assistant",
        "reasoning_content": "legacy reasoning",
    }
