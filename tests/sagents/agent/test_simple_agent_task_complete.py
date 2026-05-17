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


# ---- 规则 2 行为变更：工具失败不再强制继续，由主循环按 error_category 熔断 ----

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "工具调用失败：未提供的工具",
        "参数解析失败：JSON 解码错误",
        "调用 customer_send_message 时工具调用失败，原因：xxx",
    ],
)
async def test_tool_failure_no_longer_forces_continue(content):
    """回归 commit b0b70322：规则 2 历史实现"工具失败必须继续"，
    与主循环按 error_category 的连续错误熔断方向相反，会让单次会话撑到
    max_loop_count 跑出大量 chunk。现已改为 return False，把决策权交回
    主循环熔断（TOOL_REJECTED 1 次熔断、其他 2 次熔断）。

    此处断言失败标记本身不再强制继续，而不是熔断的最终行为（熔断在主循环里）。
    """
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=content,
            message_type=MessageType.DO_SUBTASK_RESULT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False


@pytest.mark.asyncio
async def test_tool_failure_marker_in_unrelated_message_type_does_not_continue():
    """规则 2 仅检查 DO_SUBTASK_RESULT 类型；其它类型即使包含失败关键词也不应触发。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    messages = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content='工具调用失败，但其实是正常文本',
            message_type=MessageType.ASSISTANT_TEXT.value,
        ),
    ]
    assert await agent._must_continue_by_rules(messages) is False


# ---- _classify_error_category：保护本次熔断 key 改造的 5 类映射 ----

@pytest.mark.parametrize(
    "content, expected",
    [
        ("模型调用了未提供的工具，已拒绝", "TOOL_REJECTED"),
        ("tool not provided in this turn", "TOOL_REJECTED"),
        ("违规工具：foo_tool", "TOOL_REJECTED"),
        ("turn_status 工具未调用", "TURN_STATUS"),
        ("execution timeout exceeded", "TIMEOUT"),
        ("工具执行超时", "TIMEOUT"),
        ("invalid arguments for tool", "INVALID_ARGS"),
        ("参数解析失败", "INVALID_ARGS"),
        ("some unknown error occurred", "OTHER"),
    ],
)
def test_classify_error_category_covers_known_kinds(content, expected):
    """主循环熔断现在以 error_category 作为比较 key（对 LLM 措辞抖动免疫），
    分类映射稳定性直接决定熔断是否能命中，需要专门保护。"""
    agent = SimpleAgent(model=DummyModel(), model_config={})
    chunk = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
    )
    assert agent._classify_error_category([chunk]) == expected
