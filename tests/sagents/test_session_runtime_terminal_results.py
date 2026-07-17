from types import SimpleNamespace

import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.session_runtime import Session


@pytest.mark.asyncio
async def test_execute_agent_phase_emits_dequeued_tool_result_before_interrupt(
    monkeypatch,
):
    tool_result = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"status":"error","error":"failed"}',
        tool_call_id="call-failed",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        metadata={"tool_execution_status": "error"},
    )
    late_assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="must not escape after interruption",
    )
    live_session = SimpleNamespace()
    live_session.context = object()
    live_session.interrupted = False
    live_session.get_context = lambda: live_session.context
    live_session.should_interrupt = lambda: live_session.interrupted
    session_manager = SimpleNamespace(get_live_session=lambda _session_id: live_session)
    monkeypatch.setattr(
        "sagents.session_runtime.get_global_session_manager",
        lambda: session_manager,
    )

    class FakeAgent:
        agent_description = "fake"

        async def run_stream(self, _session_context):
            live_session.interrupted = True
            yield [tool_result, late_assistant]

    runtime = Session.__new__(Session)

    chunks = [
        chunk
        async for chunk in runtime._execute_agent_phase(
            session_id="session-1",
            agent=FakeAgent(),
            phase_name="test",
        )
    ]

    assert chunks == [[tool_result]]
