"""SimpleAgent turn_status 前置文本校验单测。

验证 turn_status 的「先说明再报告状态」契约。
"""
import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.agent.simple_agent import SimpleAgent


class _DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover
        yield None


def _agent():
    return SimpleAgent(model=_DummyModel(), model_config={})


def test_returns_true_when_recent_assistant_text_exists():
    msgs = [
        MessageChunk(role=MessageRole.USER.value, content="跑一下", message_type=MessageType.USER_INPUT.value),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="任务完成，文件已生成。", message_type=MessageType.ASSISTANT_TEXT.value),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is True


def test_returns_false_when_no_assistant_text_since_last_user():
    msgs = [
        MessageChunk(role=MessageRole.ASSISTANT.value, content="老的总结", message_type=MessageType.ASSISTANT_TEXT.value),
        MessageChunk(role=MessageRole.USER.value, content="再来一次", message_type=MessageType.USER_INPUT.value),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_user_message_acts_as_boundary():
    msgs = [
        MessageChunk(role=MessageRole.ASSISTANT.value, content="老总结", message_type=MessageType.ASSISTANT_TEXT.value),
        MessageChunk(role=MessageRole.USER.value, content="新需求", message_type=MessageType.USER_INPUT.value),
        MessageChunk(role='tool', content='ok', tool_call_id='x', message_type=MessageType.TOOL_CALL_RESULT.value),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_blank_assistant_content_not_counted():
    msgs = [
        MessageChunk(role=MessageRole.USER.value, content="hi", message_type=MessageType.USER_INPUT.value),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="   \n", message_type=MessageType.ASSISTANT_TEXT.value),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_empty_history_returns_false():
    assert _agent()._has_recent_assistant_summary([]) is False


def test_trailing_tool_result_blocks_summary():
    """末尾是 tool 消息：模型刚跑完工具，还没机会写总结，应判定无总结。

    复现实际故障：assistant 输出过渡话 + todo_write tool_calls，tool 返回后模型
    立刻只调 turn_status —— 旧规则会把那段过渡话误判为总结。
    """
    msgs = [
        MessageChunk(role=MessageRole.USER.value, content="跑测试", message_type=MessageType.USER_INPUT.value),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="完美！现在让我更新任务清单并生成最终报告：",
            tool_calls=[{"id": "t1", "type": "function", "function": {"name": "todo_write", "arguments": "{}"}}],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(role='tool', content='ok', tool_call_id='t1', message_type=MessageType.TOOL_CALL_RESULT.value),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_assistant_with_tool_calls_does_not_count_as_summary():
    """assistant 既有 content 又有 tool_calls：那段文字是过渡话不是总结。"""
    msgs = [
        MessageChunk(role=MessageRole.USER.value, content="干活", message_type=MessageType.USER_INPUT.value),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="好的，我先列一下 todo：",
            tool_calls=[{"id": "t2", "type": "function", "function": {"name": "todo_write", "arguments": "{}"}}],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is False


def test_clean_trailing_assistant_text_counts_as_summary():
    """合法形态：tool 之后模型先发一条纯文本总结，再下一次 LLM 调用 turn_status。"""
    msgs = [
        MessageChunk(role=MessageRole.USER.value, content="干活", message_type=MessageType.USER_INPUT.value),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="开工：",
            tool_calls=[{"id": "t3", "type": "function", "function": {"name": "todo_write", "arguments": "{}"}}],
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
        MessageChunk(role='tool', content='ok', tool_call_id='t3', message_type=MessageType.TOOL_CALL_RESULT.value),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务全部完成：todo 已更新，关键产物 X、Y。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert _agent()._has_recent_assistant_summary(msgs) is True


def test_plain_text_without_tool_call_requests_turn_status_retry():
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="任务已经完成，结果如下。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]
    tools_json = [{"function": {"name": "turn_status"}}]

    assert _agent()._should_request_turn_status_after_text_response(chunks, tools_json) is True


def test_tool_call_response_does_not_request_turn_status_retry():
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=None,
            tool_calls=[{"id": "t1", "type": "function", "function": {"name": "todo_write", "arguments": "{}"}}],
            message_type=MessageType.TOOL_CALL.value,
        )
    ]
    tools_json = [{"function": {"name": "turn_status"}}]

    assert _agent()._should_request_turn_status_after_text_response(chunks, tools_json) is False


def test_missing_turn_status_tool_does_not_request_retry():
    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="仅文字输出。",
            message_type=MessageType.ASSISTANT_TEXT.value,
        )
    ]

    assert _agent()._should_request_turn_status_after_text_response(chunks, []) is False


def test_turn_status_tools_only_filters_action_tools():
    tools_json = [
        {"function": {"name": "todo_write"}},
        {"function": {"name": "turn_status"}},
    ]

    assert _agent()._turn_status_tools_only(tools_json) == [{"function": {"name": "turn_status"}}]


def test_coerce_invalid_status_only_returns_continue_work_with_metadata():
    """status-only 补轮里改写违规工具：保留原 id、记录原始工具名、note 走 i18n。"""
    import json

    invalid_calls = {
        "call_X": {
            "id": "call_X",
            "type": "function",
            "function": {"name": "todo_write", "arguments": "{}"},
        },
        "call_Y": {
            "id": "call_Y",
            "type": "function",
            "function": {"name": "load_skill", "arguments": "{}"},
        },
    }
    new_calls, coerced_id, original_names = _agent()._coerce_invalid_status_only_tool_calls(
        invalid_calls, language="zh"
    )

    assert coerced_id == "call_X"
    assert set(original_names) == {"todo_write", "load_skill"}
    assert list(new_calls.keys()) == ["call_X"]
    fn = new_calls["call_X"]["function"]
    assert fn["name"] == "turn_status"
    args = json.loads(fn["arguments"])
    assert args["status"] == "continue_work"
    # 中文文案 + 原始工具名注入到 note
    assert "todo_write" in args["note"] and "load_skill" in args["note"]
    assert "turn_status" in args["note"]


def test_turn_status_from_tool_call_reads_continue_work():
    tool_call = {
        "function": {
            "name": "turn_status",
            "arguments": '{"status": "continue_work", "note": "more"}',
        }
    }

    assert _agent()._turn_status_from_tool_call(tool_call) == "continue_work"
