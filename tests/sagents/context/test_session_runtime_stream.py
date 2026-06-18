import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.flow.schema import AgentFlow, AgentNode
from sagents.session_runtime import Session


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

    session = Session(session_id="child-session", enable_obs=False)
    session.configure_runtime(
        session_space=str(tmp_path),
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
