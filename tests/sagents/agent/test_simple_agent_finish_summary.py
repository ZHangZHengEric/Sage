"""SimpleAgent._has_recent_assistant_summary 单测。

验证 finish_turn 的「先总结再结束」契约：当 assistant 在前一步已经输出过总结，
后一步单独发 finish_turn 时不应被误拒。
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
    立刻只调 finish_turn —— 旧规则会把那段过渡话误判为总结。
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
    """合法形态 (b)：tool 之后模型先发一条纯文本总结，再下一次 LLM 调用 finish_turn。"""
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
