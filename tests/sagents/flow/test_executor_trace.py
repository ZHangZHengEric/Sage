import pytest

from sagents.context.session_context import SessionStatus
from sagents.flow.conditions import ConditionRegistry
from sagents.flow.executor import FlowExecutor
from sagents.flow.schema import IfNode, ParallelNode, SequenceNode, SwitchNode


class _FakeContext:
    def __init__(self):
        self.audit_status = {"trace_enabled": True, "mode": "simple"}
        self.system_context = {}

    def add_messages(self, _messages):
        raise AssertionError("test flow should not execute agent nodes")


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
