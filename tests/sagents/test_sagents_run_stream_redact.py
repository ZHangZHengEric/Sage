"""SAgent.run_stream 出口处的协议性内部工具过滤白盒测试。

直接对模块级 helper `_redact_hidden_tools_from_chunk` 做单测，避免起整个 SAgent。
"""

from __future__ import annotations

from types import SimpleNamespace

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.sagents import _HiddenToolStreamState, _redact_hidden_tools_from_chunk


def _make_state() -> _HiddenToolStreamState:
    return _HiddenToolStreamState()


def _assistant_tool_call_chunk(tool_calls):
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        tool_calls=tool_calls,
        message_type=MessageType.TOOL_CALL.value,
    )


def test_full_turn_status_tool_call_dropped():
    state = _make_state()
    chunk = _assistant_tool_call_chunk([
        {
            "id": "call_ts_1",
            "index": 0,
            "type": "function",
            "function": {"name": "turn_status", "arguments": '{"status":"task_done"}'},
        }
    ])
    assert _redact_hidden_tools_from_chunk(chunk, state) is None
    assert "call_ts_1" in state.call_ids
    assert state.index_to_id.get(0) == "call_ts_1"
    assert state.last_was_hidden is True


def test_id_only_continuation_delta_dropped():
    state = _make_state()
    head = _assistant_tool_call_chunk([
        {
            "id": "call_ts_2",
            "index": 1,
            "type": "function",
            "function": {"name": "turn_status", "arguments": ""},
        }
    ])
    assert _redact_hidden_tools_from_chunk(head, state) is None

    tail = _assistant_tool_call_chunk([
        {
            "id": "call_ts_2",
            "type": "function",
            "function": {"name": None, "arguments": '{"status":"task_done"}'},
        }
    ])
    assert _redact_hidden_tools_from_chunk(tail, state) is None


def test_index_only_continuation_delta_dropped():
    state = _make_state()
    head = _assistant_tool_call_chunk([
        {
            "id": "call_ts_3",
            "index": 2,
            "type": "function",
            "function": {"name": "turn_status", "arguments": ""},
        }
    ])
    assert _redact_hidden_tools_from_chunk(head, state) is None

    tail = _assistant_tool_call_chunk([
        {
            "index": 2,
            "type": "function",
            "function": {"name": None, "arguments": '"done"}'},
        }
    ])
    assert _redact_hidden_tools_from_chunk(tail, state) is None


def test_greedy_continuation_when_id_and_index_missing():
    """部分后端在续片中既丢 id 也丢 index，仅 arguments delta，需要按 last_was_hidden 兜底。"""
    state = _make_state()
    head = _assistant_tool_call_chunk([
        {
            "id": "call_ts_greedy",
            "index": 0,
            "type": "function",
            "function": {"name": "turn_status", "arguments": ""},
        }
    ])
    assert _redact_hidden_tools_from_chunk(head, state) is None

    tail = _assistant_tool_call_chunk([
        {
            "type": "function",
            "function": {"name": None, "arguments": '"done"}'},
        }
    ])
    assert _redact_hidden_tools_from_chunk(tail, state) is None


def test_greedy_continuation_does_not_swallow_after_visible_tool():
    """上一 entry 是非隐藏工具时，三件套缺失的续片不应被误隐藏。"""
    state = _make_state()
    visible = _assistant_tool_call_chunk([
        {
            "id": "call_visible_1",
            "index": 0,
            "type": "function",
            "function": {"name": "shell", "arguments": ""},
        }
    ])
    assert _redact_hidden_tools_from_chunk(visible, state) is visible

    tail = _assistant_tool_call_chunk([
        {
            "type": "function",
            "function": {"name": None, "arguments": '"ls"}'},
        }
    ])
    out = _redact_hidden_tools_from_chunk(tail, state)
    assert out is tail


def test_mixed_tool_calls_only_turn_status_removed():
    state = _make_state()
    chunk = _assistant_tool_call_chunk([
        {
            "id": "call_ts_4",
            "index": 0,
            "type": "function",
            "function": {"name": "turn_status", "arguments": "{}"},
        },
        {
            "id": "call_other_1",
            "index": 1,
            "type": "function",
            "function": {"name": "shell", "arguments": '{"cmd":"ls"}'},
        },
    ])
    out = _redact_hidden_tools_from_chunk(chunk, state)
    assert out is not None
    assert out.tool_calls is not None
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0]["function"]["name"] == "shell"
    # 末尾 entry 是 visible，last_was_hidden 应被覆写为 False，避免后续误隐藏。
    assert state.last_was_hidden is False


def test_tool_result_for_turn_status_dropped():
    state = _make_state()
    head = _assistant_tool_call_chunk([
        {
            "id": "call_ts_5",
            "index": 0,
            "type": "function",
            "function": {"name": "turn_status", "arguments": "{}"},
        }
    ])
    assert _redact_hidden_tools_from_chunk(head, state) is None

    tool_result = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success": true, "should_end": true}',
        tool_call_id="call_ts_5",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    assert _redact_hidden_tools_from_chunk(tool_result, state) is None


def test_other_tool_result_passes_through():
    state = _make_state()
    tool_result = MessageChunk(
        role=MessageRole.TOOL.value,
        content="ok",
        tool_call_id="call_other_999",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = _redact_hidden_tools_from_chunk(tool_result, state)
    assert out is tool_result


def test_plain_assistant_text_passes_through():
    state = _make_state()
    chunk = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="hello",
        message_type=MessageType.ASSISTANT_TEXT.value,
    )
    out = _redact_hidden_tools_from_chunk(chunk, state)
    assert out is chunk


def test_pydantic_like_delta_objects_supported():
    """OpenAI 流式 delta 是 Pydantic 对象，非 dict。"""
    state = _make_state()
    fn = SimpleNamespace(name="turn_status", arguments="")
    delta_entry = SimpleNamespace(id="call_ts_6", index=0, type="function", function=fn)
    head = _assistant_tool_call_chunk([delta_entry])
    assert _redact_hidden_tools_from_chunk(head, state) is None
    assert "call_ts_6" in state.call_ids

    tail_fn = SimpleNamespace(name=None, arguments='{"status":"task_done"}')
    tail_entry = SimpleNamespace(id="call_ts_6", index=None, type="function", function=tail_fn)
    tail = _assistant_tool_call_chunk([tail_entry])
    assert _redact_hidden_tools_from_chunk(tail, state) is None


def test_turn_status_only_chunk_with_empty_content_dropped():
    state = _make_state()
    chunk = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="",
        tool_calls=[
            {
                "id": "call_ts_7",
                "index": 0,
                "type": "function",
                "function": {"name": "turn_status", "arguments": "{}"},
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    assert _redact_hidden_tools_from_chunk(chunk, state) is None


def test_rejected_turn_status_tool_result_still_hidden_from_sse():
    """C2 + C4 改动：reject 的 tool 结果会保留在 LLM 上下文（含 metadata 标记），
    但 SSE 端仍按 tool_call_id 隐藏，前端不会看到拒绝文本。"""
    state = _make_state()
    head = _assistant_tool_call_chunk([
        {
            "id": "call_rej_sse",
            "index": 0,
            "type": "function",
            "function": {"name": "turn_status", "arguments": "{}"},
        }
    ])
    assert _redact_hidden_tools_from_chunk(head, state) is None

    rejected = MessageChunk(
        role=MessageRole.TOOL.value,
        content=(
            "turn_status 调用被拒绝：本轮 assistant 还没有输出任何自然语言说明。"
            "请在本轮同一条 assistant 回复里同时输出面向用户的中文/英文说明（总结当前进展与结果，含已完成事项、关键产物或下一步建议），"
            "并同时调用 turn_status(status=...) 报告本轮状态；不要先发纯工具调用再单独补文字。"
        ),
        tool_call_id="call_rej_sse",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"turn_status_rejected": True},
    )
    assert _redact_hidden_tools_from_chunk(rejected, state) is None


def test_turn_status_only_chunk_with_text_keeps_text():
    state = _make_state()
    chunk = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="任务完成。",
        tool_calls=[
            {
                "id": "call_ts_8",
                "index": 0,
                "type": "function",
                "function": {"name": "turn_status", "arguments": "{}"},
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    out = _redact_hidden_tools_from_chunk(chunk, state)
    assert out is not None
    assert out.tool_calls is None
    assert out.content == "任务完成。"
