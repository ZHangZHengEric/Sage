import pytest

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionStatus
from sagents.flow.conditions import ConditionRegistry
from sagents.flow.executor import FlowExecutor
from sagents.flow.schema import AgentNode, IfNode, ParallelNode, SequenceNode, SwitchNode


class _FakeContext:
    def __init__(self):
        self.audit_status = {"trace_enabled": True, "mode": "simple"}
        self.system_context = {}
        self.added_messages = []

    def add_messages(self, _messages):
        self.added_messages.append(_messages)


class _FakeSession:
    def __init__(self):
        self.context = _FakeContext()

    def should_interrupt(self):
        return False

    def get_status(self):
        return SessionStatus.RUNNING

    def get_context(self):
        return self.context


class _FakeSessionManager:
    def __init__(self):
        self.session = _FakeSession()

    def get_live_session(self, _session_id):
        return self.session


@pytest.mark.asyncio
async def test_flow_executor_emits_one_trace_for_nested_control_flow(monkeypatch):
    ConditionRegistry.register("trace_enabled")(
        lambda session_context, session=None: session_context.audit_status[
            "trace_enabled"
        ]
    )
    info_messages = []
    monkeypatch.setattr(
        "sagents.flow.executor.logger.info",
        lambda message, *args, **kwargs: info_messages.append(message),
    )

    flow = SequenceNode(
        steps=[
            IfNode(
                condition="trace_enabled",
                true_body=SwitchNode(
                    variable="mode",
                    cases={
                        "simple": ParallelNode(
                            branches=[
                                SequenceNode(steps=[]),
                                SequenceNode(steps=[]),
                            ]
                        )
                    },
                ),
            )
        ]
    )
    executor = FlowExecutor(
        tool_manager=None,
        session_runtime=None,
        session_id="trace-session",
        session_manager=_FakeSessionManager(),
    )

    chunks = [chunk async for chunk in executor.execute(flow)]

    trace_messages = [
        message
        for message in info_messages
        if message.startswith("FlowExecutor: Trace ")
    ]
    assert chunks == []
    assert trace_messages == [
        "FlowExecutor: Trace sequence -> if(trace_enabled=True) -> switch(mode=simple) -> parallel(branches=2) -> sequence -> sequence -> parallel_done(2)"
    ]


@pytest.mark.asyncio
async def test_flow_executor_suppresses_hidden_chunks_for_any_agent():
    hidden = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="hidden diagnostic",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"hidden_from_chat": True, "sse_visible": False},
    )
    visible = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="visible",
        message_type=MessageType.DO_SUBTASK_RESULT.value,
    )
    session_manager = _FakeSessionManager()

    class FakeAgent:
        agent_name = "fake_agent"

    class FakeRuntime:
        def _get_agent(self, _agent_key):
            return FakeAgent()

        async def _execute_agent_phase(self, *args, **kwargs):
            yield [hidden, visible]

    executor = FlowExecutor(
        tool_manager=None,
        session_runtime=FakeRuntime(),
        session_id="flow-session",
        session_manager=session_manager,
    )

    chunks = [chunk async for chunk in executor.execute(AgentNode(agent_key="simple"))]

    assert chunks == [[visible]]
    assert session_manager.session.context.added_messages == [[hidden, visible]]
