import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.flow.schema import AgentFlow, AgentNode
from sagents.session_runtime import Session, initialize_global_session_manager


@pytest.mark.asyncio
async def test_run_stream_with_flow_fills_missing_session_id(monkeypatch, tmp_path):
    class FakeFlowExecutor:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, root):
            yield [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content="{}",
                    tool_call_id="call_memory",
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                ),
                {
                    "role": MessageRole.ASSISTANT.value,
                    "content": "done",
                    "message_id": "dict-message",
                },
            ]

    monkeypatch.setattr("sagents.session_runtime.FlowExecutor", FakeFlowExecutor)

    initialize_global_session_manager(str(tmp_path), enable_obs=False)
    session = Session(session_id="child-session", enable_obs=False)
    session.configure_runtime(
        model=object(),
        session_root_space=str(tmp_path),
        sandbox_agent_workspace=str(tmp_path / "workspace"),
    )

    chunks = []
    async for emitted in session.run_stream_with_flow(
        input_messages=[
            {
                "role": MessageRole.USER.value,
                "content": "hi",
                "session_id": "child-session",
            }
        ],
        flow=AgentFlow(name="fake", root=AgentNode(agent_key="simple")),
        session_id="child-session",
        user_id="user-1",
        max_loop_count=1,
        agent_mode="simple",
    ):
        chunks.extend(emitted)

    assert chunks[0].session_id == "child-session"
    assert chunks[1]["session_id"] == "child-session"


@pytest.mark.parametrize(
    ("response_language", "expected"),
    [
        ("zh-CN", "工作流执行失败: 请求过于频繁，请稍后再试"),
        ("en-US", "Workflow execution failed: Too many requests. Try again later"),
        (
            "pt-BR",
            "Falha ao executar o fluxo de trabalho: "
            "Muitas solicitacoes. Tente novamente mais tarde",
        ),
    ],
)
@pytest.mark.asyncio
async def test_handle_workflow_error_uses_session_language_for_rate_limit(
    tmp_path, response_language, expected
):
    session = Session(session_id="error-session", enable_obs=False)
    session.session_context = SessionContext(
        session_id="error-session",
        user_id="user-1",
        agent_id="agent-1",
        session_root_space=str(tmp_path),
        system_context={"response_language": response_language},
    )

    chunks = []
    async for emitted in session._handle_workflow_error(
        Exception("RateLimitError: rate_limit")
    ):
        chunks.extend(emitted)

    assert len(chunks) == 1
    assert chunks[0].content == expected
    assert chunks[0].type == "final_answer"
