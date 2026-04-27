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


def test_strip_keeps_rejected_turn_status_pair():
    """metadata.turn_status_rejected=True 时，strip 必须保留这对 assistant tool_call + tool 结果，
    避免模型在下一轮看不到拒绝原因。"""
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "rej_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    rejected_tool = MessageChunk(
        role=MessageRole.TOOL.value,
        content="turn_status 调用被拒绝：本轮 assistant 还没有输出任何自然语言说明。",
        tool_call_id="rej_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"turn_status_rejected": True},
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, rejected_tool])
    assert len(out) == 2
    assert out[0].role == MessageRole.ASSISTANT.value
    assert out[0].tool_calls is not None
    assert out[0].tool_calls[0]["function"]["name"] == TURN_STATUS_TOOL_NAME
    assert out[1].role == MessageRole.TOOL.value
    assert out[1].tool_call_id == "rej_1"


def test_strip_only_keeps_rejected_pair_when_mixed_with_success():
    """rejected 与正常 turn_status 共存：仅保留 rejected pair，正常 pair 仍剔除。"""
    assistant_ok = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="先讲清楚再调。",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "ok_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_ok = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true,"should_end":true}',
        tool_call_id="ok_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    assistant_rej = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "rej_2")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_rej = MessageChunk(
        role=MessageRole.TOOL.value,
        content="turn_status 调用被拒绝：本轮 assistant 还没有输出任何自然语言说明。",
        tool_call_id="rej_2",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"turn_status_rejected": True},
    )
    out = MessageManager.strip_turn_status_from_llm_context(
        [assistant_ok, tool_ok, assistant_rej, tool_rej]
    )
    # assistant_ok 仅含一个 turn_status，被剔除整段；其文本由 strip 规则保留
    assert len(out) == 3
    assert out[0].role == MessageRole.ASSISTANT.value
    assert out[0].content == "先讲清楚再调。"
    assert out[0].tool_calls is None
    # rejected pair 整体保留
    assert out[1].role == MessageRole.ASSISTANT.value
    assert out[1].tool_calls and out[1].tool_calls[0]["id"] == "rej_2"
    assert out[2].role == MessageRole.TOOL.value
    assert out[2].tool_call_id == "rej_2"


def test_strip_keeps_rejected_pair_inside_mixed_tool_calls():
    """assistant 同条消息里 turn_status(rejected) 与其他工具并存时，rejected 的 tool_call 不应被裁掉。"""
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="进行中",
        tool_calls=[
            _tc("grep", "g1"),
            _tc(TURN_STATUS_TOOL_NAME, "rej_3"),
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_g = MessageChunk(
        role=MessageRole.TOOL.value,
        content="hits",
        tool_call_id="g1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    tool_rej = MessageChunk(
        role=MessageRole.TOOL.value,
        content="turn_status 调用被拒绝：本轮 assistant 还没有输出任何自然语言说明。",
        tool_call_id="rej_3",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"turn_status_rejected": True},
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, tool_g, tool_rej])
    assert len(out) == 3
    names = [tc["function"]["name"] for tc in (out[0].tool_calls or [])]
    assert names == ["grep", TURN_STATUS_TOOL_NAME]
    assert out[1].tool_call_id == "g1"
    assert out[2].tool_call_id == "rej_3"


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
