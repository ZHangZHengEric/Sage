import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.agent.simple_agent import SimpleAgent


class DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover - simplified dummy
        yield None


@pytest.mark.asyncio
async def test_must_continue_when_last_role_is_tool():
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role='tool',
            content='工具执行结果',
            message_type=MessageType.TOOL_CALL_RESULT.value,
            tool_call_id='call_1',
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_must_continue_when_last_assistant_processing_keyword():
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(role=MessageRole.ASSISTANT.value, content='正在处理，请稍等', message_type=MessageType.ASSISTANT_TEXT.value),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_must_continue_when_last_assistant_ends_with_colon():
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(role=MessageRole.ASSISTANT.value, content='HTML报告已生成，现在让我完成最后的检查并更新任务状态：', message_type=MessageType.ASSISTANT_TEXT.value),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_not_must_continue_for_normal_assistant_message():
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(role=MessageRole.ASSISTANT.value, content='任务已经完成，这是最终结果。', message_type=MessageType.ASSISTANT_TEXT.value),
    ]
    assert await agent._must_continue_by_rules(messages) is False
