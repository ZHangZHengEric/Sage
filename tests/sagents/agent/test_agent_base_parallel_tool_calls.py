import asyncio
from typing import AsyncGenerator, List

import pytest

from sagents.agent.agent_base import AgentBase, TOOL_CALL_CONCURRENCY_LIMIT
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager


class ParallelToolAgent(AgentBase):
    def __init__(self, *, expected_starts: int):
        super().__init__(model=None, model_config={})
        self.expected_starts = expected_starts
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.active_count = 0
        self.max_active_count = 0
        self.started_tool_ids: List[str] = []

    async def run_stream(
        self, session_context
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if False:
            yield []

    async def _execute_tool(
        self,
        tool_call,
        tool_manager,
        messages_input,
        session_id,
        session_context=None,
    ):
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        self.started_tool_ids.append(tool_call["id"])
        if len(self.started_tool_ids) == self.expected_starts:
            self.started.set()

        await self.release.wait()

        self.active_count -= 1
        yield [
            MessageChunk(
                role=MessageRole.TOOL.value,
                content=tool_call["id"],
                tool_call_id=tool_call["id"],
                message_type=MessageType.TOOL_CALL_RESULT.value,
            )
        ]


def _tool_call(call_id: str):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "web_search", "arguments": '{"query":"x"}'},
    }


class _FakeSessionContext:
    def __init__(self, language: str):
        self.language = language

    def get_language(self):
        return self.language


def test_next_request_runtime_metadata_keeps_visibility_and_lifecycle_fixed():
    metadata = ParallelToolAgent._next_request_runtime_metadata(
        hidden_from_chat=False,
        hide_from_chat=False,
        sse_visible=True,
        llm_scope="durable",
        llm_state="consumed",
        runtime_notice="test_notice",
    )

    assert metadata["hidden_from_chat"] is True
    assert metadata["hide_from_chat"] is True
    assert metadata["sse_visible"] is False
    assert metadata["llm_scope"] == "next_request"
    assert metadata["llm_state"] == "pending"
    assert metadata["runtime_notice"] == "test_notice"


@pytest.mark.asyncio
async def test_handle_tool_calls_runs_tools_concurrently_with_limit_10():
    agent = ParallelToolAgent(expected_starts=3)
    calls = {
        "call_1": _tool_call("call_1"),
        "call_2": _tool_call("call_2"),
        "call_3": _tool_call("call_3"),
    }
    async def collect_results():
        results = []
        async for messages, is_complete in agent._handle_tool_calls(
            tool_calls=calls,
            tool_manager=None,
            messages_input=[],
            session_id="session-1",
            emit_tool_call_message=False,
        ):
            assert is_complete is False
            results.extend(messages)
        return results

    collector = asyncio.create_task(collect_results())
    await asyncio.wait_for(agent.started.wait(), timeout=1)

    assert agent.max_active_count == 3
    assert agent.max_active_count <= TOOL_CALL_CONCURRENCY_LIMIT
    assert agent.started_tool_ids == ["call_1", "call_2", "call_3"]

    agent.release.set()
    results = await asyncio.wait_for(collector, timeout=1)

    assert [message.tool_call_id for message in results] == [
        "call_1",
        "call_2",
        "call_3",
    ]


class ImmediateResultAgent(ParallelToolAgent):
    def __init__(self):
        super().__init__(expected_starts=2)
        self.slow_release = asyncio.Event()

    async def _execute_tool(
        self,
        tool_call,
        tool_manager,
        messages_input,
        session_id,
        session_context=None,
    ):
        self.started_tool_ids.append(tool_call["id"])
        if len(self.started_tool_ids) == self.expected_starts:
            self.started.set()
        if tool_call["id"] == "call_slow":
            await self.slow_release.wait()
        yield [
            MessageChunk(
                role=MessageRole.TOOL.value,
                content=tool_call["id"],
                tool_call_id=tool_call["id"],
                message_type=MessageType.TOOL_CALL_RESULT.value,
            )
        ]


@pytest.mark.asyncio
async def test_parallel_tool_result_is_yielded_before_other_tools_finish():
    agent = ImmediateResultAgent()
    calls = {
        "call_fast": _tool_call("call_fast"),
        "call_slow": _tool_call("call_slow"),
    }
    stream = agent._handle_tool_calls(
        tool_calls=calls,
        tool_manager=None,
        messages_input=[],
        session_id="session-1",
        emit_tool_call_message=False,
    )

    messages, is_complete = await asyncio.wait_for(anext(stream), timeout=1)

    assert is_complete is False
    assert [message.tool_call_id for message in messages] == ["call_fast"]
    assert agent.slow_release.is_set() is False

    agent.slow_release.set()
    remaining = []
    async for messages, _ in stream:
        remaining.extend(messages)
    assert [message.tool_call_id for message in remaining] == ["call_slow"]


class _RecordingSessionContext(_FakeSessionContext):
    def __init__(self):
        super().__init__("zh-CN")
        self.messages = []

    def add_messages(self, messages):
        self.messages.extend(messages)


class _CancellingToolManager:
    def __init__(self):
        self.slow_started = asyncio.Event()
        self.slow_release = asyncio.Event()

    async def run_tool_async(
        self, tool_name, session_id, user_id=None, tool_call_id=None, **kwargs
    ):
        if tool_call_id == "call_fast":
            return '{"error":true,"error_type":"EXECUTION_ERROR","message":"failed"}'
        self.slow_started.set()
        await self.slow_release.wait()
        return '{"ok":true}'


@pytest.mark.asyncio
async def test_cancellation_persists_only_the_cancelled_tool_terminal_result(monkeypatch):
    agent = ParallelToolAgent(expected_starts=0)
    agent._execute_tool = AgentBase._execute_tool.__get__(agent, ParallelToolAgent)
    session_context = _RecordingSessionContext()
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda _session_id: session_context
    )
    tool_manager = _CancellingToolManager()
    calls = {
        "call_fast": _tool_call("call_fast"),
        "call_slow": _tool_call("call_slow"),
    }

    stream = agent._handle_tool_calls(
        tool_calls=calls,
        tool_manager=tool_manager,
        messages_input=[],
        session_id="session-1",
        emit_tool_call_message=False,
    )
    fast_messages, _ = await asyncio.wait_for(anext(stream), timeout=1)
    assert fast_messages[0].metadata["tool_execution_status"] == "error"
    await asyncio.wait_for(tool_manager.slow_started.wait(), timeout=1)

    pending_next = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending_next.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_next

    assert len(session_context.messages) == 1
    cancelled = session_context.messages[0]
    assert cancelled.tool_call_id == "call_slow"
    assert cancelled.metadata["tool_execution_status"] == "cancelled"


@pytest.mark.asyncio
async def test_invalid_tool_call_arguments_become_hidden_localized_runtime_diagnostic(
    monkeypatch,
):
    agent = ParallelToolAgent(expected_starts=0)
    monkeypatch.setattr(
        agent,
        "_get_live_session_context",
        lambda session_id: _FakeSessionContext("en-US"),
    )
    calls = {
        "call_bad": {
            "id": "call_bad",
            "type": "function",
            "function": {
                "name": "file_write",
                "arguments": '{"file_path":"/tmp/demo.txt","content":"unterminated',
            },
        }
    }

    yielded = []
    async for messages, is_complete in agent._handle_tool_calls(
        tool_calls=calls,
        tool_manager=None,
        messages_input=[],
        session_id="session-1",
        emit_tool_call_message=False,
    ):
        assert is_complete is False
        yielded.extend(messages)

    assert len(yielded) == 2
    rejection, message = yielded
    assert rejection.role == MessageRole.TOOL.value
    assert rejection.tool_call_id == "call_bad"
    assert rejection.metadata["streamed_tool_rejected"] is True
    assert "invalid_tool_arguments" in rejection.content
    assert message.role == MessageRole.ASSISTANT.value
    assert message.message_type == MessageType.AGENT_EXECUTION_ERROR.value
    assert "I tried to call tool `file_write`" in message.content
    assert "Invalid JSON or incomplete argument structure" in message.content
    assert "我尝试调用工具" not in message.content
    assert message.metadata["sse_visible"] is False
    assert message.metadata["hidden_from_chat"] is True
    assert message.metadata["hide_from_chat"] is True
    assert message.metadata["llm_scope"] == "next_request"
    assert message.metadata["llm_state"] == "pending"
    assert message.metadata["runtime_diagnostic_source"] == "tool_call_argument_parse"

    request_messages = MessageManager.convert_messages_to_dict_for_request(
        [
            MessageChunk(
                role=MessageRole.ASSISTANT.value,
                tool_calls=[calls["call_bad"]],
                message_type=MessageType.TOOL_CALL.value,
            ),
            *yielded,
        ]
    )
    assert len(request_messages) == 1
    assert request_messages[0]["role"] == MessageRole.ASSISTANT.value
    assert "<runtime_diagnostic" in request_messages[0]["content"]


def test_context_over_limit_error_uses_requested_language():
    agent = ParallelToolAgent(expected_starts=0)

    message = agent._context_over_limit_error_chunk(120, 100, "en-US")

    assert message.message_type == MessageType.AGENT_EXECUTION_ERROR.value
    assert (
        "The compressed context still exceeds the model input limit" in message.content
    )
    assert "当前上下文" not in message.content
