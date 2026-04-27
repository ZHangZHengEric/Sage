"""turn_status 不进 LLM 请求的单元测试。"""

import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager, TURN_STATUS_TOOL_NAME


def _tc(name: str, tc_id: str) -> dict:
    return {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def test_strip_removes_turn_status_pair_keeps_assistant_text():
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="阶段总结说明",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "call_ts_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_msg = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"turn_status":"task_done"}',
        tool_call_id="call_ts_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, tool_msg])
    assert len(out) == 1
    assert out[0].role == MessageRole.ASSISTANT.value
    assert out[0].content == "阶段总结说明"
    assert out[0].tool_calls is None


def test_strip_drops_assistant_that_only_had_turn_status():
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "only_ts")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_msg = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true}',
        tool_call_id="only_ts",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, tool_msg])
    assert out == []


def test_strip_keeps_other_tools():
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="执行中",
        tool_calls=[
            _tc("grep", "c1"),
            _tc(TURN_STATUS_TOOL_NAME, "c2"),
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    t1 = MessageChunk(
        role=MessageRole.TOOL.value,
        content="hits",
        tool_call_id="c1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    t2 = MessageChunk(
        role=MessageRole.TOOL.value,
        content="ack",
        tool_call_id="c2",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, t1, t2])
    assert len(out) == 2
    assert out[0].tool_calls is not None
    assert len(out[0].tool_calls) == 1
    assert out[0].tool_calls[0]["function"]["name"] == "grep"
    assert out[1].tool_call_id == "c1"


def test_extract_messages_for_inference_strips_turn_status():
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="hi",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "x")],
    )
    tool_msg = MessageChunk(
        role=MessageRole.TOOL.value,
        content="ok",
        tool_call_id="x",
    )
    out = MessageManager.extract_messages_for_inference([assistant, tool_msg])
    assert len(out) == 1
    assert out[0].tool_calls is None


def test_idempotent():
    m = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="t",
            tool_calls=[_tc("grep", "g1")],
        )
    ]
    a = MessageManager.strip_turn_status_from_llm_context(m)
    b = MessageManager.strip_turn_status_from_llm_context(a)
    assert [x.content for x in a] == [x.content for x in b]
