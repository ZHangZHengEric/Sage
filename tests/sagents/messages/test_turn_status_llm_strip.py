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


def test_strip_keeps_only_last_turn_status_pair():
    """多条历史 turn_status：仅最后一条 pair 保留，其余历史剔除；assistant 文本独立保留。"""
    a1 = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="阶段一总结",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "old_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    t1 = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true}',
        tool_call_id="old_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    a2 = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="阶段二总结",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "last_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    t2 = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true,"should_end":true}',
        tool_call_id="last_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context([a1, t1, a2, t2])
    # a1 的 turn_status 被剔除（保留 content），a2 的 turn_status 是最后一条 → 整对保留
    assert len(out) == 3
    assert out[0].role == MessageRole.ASSISTANT.value
    assert out[0].content == "阶段一总结"
    assert out[0].tool_calls is None
    assert out[1].role == MessageRole.ASSISTANT.value
    assert out[1].tool_calls and out[1].tool_calls[0]["id"] == "last_1"
    assert out[2].role == MessageRole.TOOL.value
    assert out[2].tool_call_id == "last_1"


def test_strip_keeps_single_turn_status_as_last():
    """仅 1 条 turn_status 时，它就是最后一条，按新策略整对保留。"""
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="阶段总结",
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
    assert len(out) == 2
    assert out[0].tool_calls and out[0].tool_calls[0]["id"] == "only_ts"
    assert out[1].tool_call_id == "only_ts"


def test_strip_keeps_other_tools_and_last_turn_status():
    """turn_status 与其他工具同条 assistant；当它是最后一条 turn_status，整条 assistant 与对应 tool 结果都保留。"""
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
    assert len(out) == 3
    assert out[0].tool_calls is not None
    names = [tc["function"]["name"] for tc in out[0].tool_calls]
    assert names == ["grep", TURN_STATUS_TOOL_NAME]
    assert out[1].tool_call_id == "c1"
    assert out[2].tool_call_id == "c2"


def test_strip_historical_turn_status_inside_mixed_tool_calls():
    """同条 assistant 里既有 turn_status 又有其他工具，且后续还有更新的 turn_status：
    本条的 turn_status 视为历史，应从 tool_calls 里裁掉，其他工具与文本保留。"""
    assistant_old = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="进行中",
        tool_calls=[
            _tc("grep", "g1"),
            _tc(TURN_STATUS_TOOL_NAME, "old_ts"),
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_g = MessageChunk(
        role=MessageRole.TOOL.value,
        content="hits",
        tool_call_id="g1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    tool_old = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true}',
        tool_call_id="old_ts",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    assistant_new = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="阶段二",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "last_ts")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_new = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true,"should_end":true}',
        tool_call_id="last_ts",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context(
        [assistant_old, tool_g, tool_old, assistant_new, tool_new]
    )
    # assistant_old 的 turn_status 历史 → 被裁；grep 与文本保留；old_ts 的 tool 结果被剔除
    # assistant_new 是最后一条 turn_status → 整对保留
    assert len(out) == 4
    names = [tc["function"]["name"] for tc in (out[0].tool_calls or [])]
    assert names == ["grep"]
    assert out[1].tool_call_id == "g1"
    assert out[2].tool_calls and out[2].tool_calls[0]["id"] == "last_ts"
    assert out[3].tool_call_id == "last_ts"


def test_extract_messages_for_inference_keeps_last_turn_status():
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
    # 仅 1 条 turn_status → 最后一条 → 保留
    assert len(out) == 2
    assert out[0].tool_calls and out[0].tool_calls[0]["id"] == "x"


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


def test_strip_keeps_rejected_when_not_last():
    """rejected 在中间，最后又有一条普通 turn_status：rejected 与最后一条都保留。"""
    a_rej = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "rej_x")],
        message_type=MessageType.TOOL_CALL.value,
    )
    t_rej = MessageChunk(
        role=MessageRole.TOOL.value,
        content="turn_status 调用被拒绝：先写说明。",
        tool_call_id="rej_x",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"turn_status_rejected": True},
    )
    a_mid = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="中间普通一轮",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "mid")],
        message_type=MessageType.TOOL_CALL.value,
    )
    t_mid = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true}',
        tool_call_id="mid",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    a_last = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="最后一轮",
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "last")],
        message_type=MessageType.TOOL_CALL.value,
    )
    t_last = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true,"should_end":true}',
        tool_call_id="last",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    out = MessageManager.strip_turn_status_from_llm_context(
        [a_rej, t_rej, a_mid, t_mid, a_last, t_last]
    )
    kept_ids = [
        m.tool_call_id
        for m in out
        if m.role == MessageRole.TOOL.value
    ]
    assert kept_ids == ["rej_x", "last"]
    # 中间 mid 的 assistant 仅保留 content，tool_calls 被剔除
    mids = [m for m in out if m.role == MessageRole.ASSISTANT.value and m.content == "中间普通一轮"]
    assert mids and mids[0].tool_calls is None


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


def test_strip_keeps_coerced_turn_status_pair():
    """status-only 补轮里被改写的 turn_status (metadata.coerced_from) 必须保留，让 LLM 看到改写事实。"""
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[_tc(TURN_STATUS_TOOL_NAME, "coerce_1")],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_msg = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"success":true,"status":"success","should_end":false}',
        tool_call_id="coerce_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"coerced_from": "todo_write"},
    )
    out = MessageManager.strip_turn_status_from_llm_context([assistant, tool_msg])
    assert len(out) == 2
    assert out[0].role == MessageRole.ASSISTANT.value
    assert out[0].tool_calls and out[0].tool_calls[0]["id"] == "coerce_1"
    assert out[1].role == MessageRole.TOOL.value
    assert out[1].tool_call_id == "coerce_1"


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
