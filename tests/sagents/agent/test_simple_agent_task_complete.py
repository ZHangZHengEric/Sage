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


# ---- 规则 3：由 SAGE_CONTINUE_ON_PROCESSING_KEYWORDS 控制 ----

@pytest.mark.asyncio
async def test_keywords_rule_hits_by_default(monkeypatch):
    """默认（env 未设）启用关键词规则，'正在处理' 命中必须继续。"""
    monkeypatch.delenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", raising=False)
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='正在处理，请稍等',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_keywords_rule_skipped_when_disabled(disable_keywords):
    """env=false 时跳过关键词规则，'正在处理' 自述也不强制继续。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='我正在处理这个请求',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False


@pytest.mark.asyncio
async def test_keywords_rule_skipped_but_rule4_still_fires(disable_keywords):
    """关键词规则被跳过时，规则 4（冒号结尾）仍然生效。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='好的，先列出镜头：',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is True


@pytest.mark.asyncio
async def test_keywords_rule_explicit_true_enables(monkeypatch):
    """显式 env=true 同样启用关键词规则。"""
    monkeypatch.setenv("SAGE_CONTINUE_ON_PROCESSING_KEYWORDS", "true")
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='正在处理中呢？',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is True
