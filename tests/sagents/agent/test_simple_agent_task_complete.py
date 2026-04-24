import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.agent.simple_agent import SimpleAgent


class DummyModel:
    async def astream(self, *args, **kwargs):  # pragma: no cover - simplified dummy
        yield None


@pytest.fixture
def disable_keywords(monkeypatch):
    """显式跳过"处理中关键词"规则（默认是启用）。"""
    monkeypatch.setenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", "false")
    yield


# ---- 规则 1 / 2 / 4：不受 env 影响，始终运行 ----

@pytest.mark.asyncio
async def test_must_continue_when_last_role_is_tool(monkeypatch):
    """规则 1：tool 结果后必须继续。不受关键词开关影响。"""
    monkeypatch.delenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", raising=False)
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
async def test_must_continue_when_last_assistant_ends_with_colon(monkeypatch):
    """规则 4：':' 结尾必须继续。不受关键词开关影响。"""
    monkeypatch.delenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", raising=False)
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='HTML报告已生成，现在让我完成最后的检查并更新任务状态：',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_not_must_continue_for_normal_assistant_message(monkeypatch):
    monkeypatch.delenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", raising=False)
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='任务已经完成，这是最终结果。',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False


# ---- 关键词规则已移除：以下测试验证"中文关键词不再触发强制继续" ----

@pytest.mark.asyncio
async def test_processing_keyword_no_longer_forces_continue():
    """'正在处理' 不再触发强制继续（关键词规则已下线）。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='正在处理，请稍等',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False


@pytest.mark.asyncio
async def test_user_question_with_punctuation_does_not_force_continue():
    """规则 4 不再对 USER 反问生效，避免被误判为继续。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.USER.value,
            content='你在处理什么？',
            message_type=MessageType.USER_INPUT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False
