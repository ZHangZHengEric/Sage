import asyncio
from typing import AsyncGenerator, List

import pytest

import sagents.agent.agent_base as agent_base_module
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


@pytest.mark.asyncio
async def test_handle_tool_calls_runs_tools_concurrently_with_limit_10(monkeypatch):
    agent = ParallelToolAgent(expected_starts=3)
    calls = {
        "call_1": _tool_call("call_1"),
        "call_2": _tool_call("call_2"),
        "call_3": _tool_call("call_3"),
    }
    seen_limits = []
    original_runner = agent_base_module.run_with_concurrency_limit_ordered

    async def run_with_limit_spy(
        limit, coros, progress_callback=None, *, return_exceptions=False
    ):
        seen_limits.append(limit)
        return await original_runner(
            limit,
            coros,
            progress_callback,
            return_exceptions=return_exceptions,
        )

    monkeypatch.setattr(
        agent_base_module,
        "run_with_concurrency_limit_ordered",
        run_with_limit_spy,
    )

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
    assert agent.started_tool_ids == ["call_1", "call_2", "call_3"]
    assert seen_limits == [TOOL_CALL_CONCURRENCY_LIMIT]

    agent.release.set()
    results = await asyncio.wait_for(collector, timeout=1)

    assert [message.tool_call_id for message in results] == [
        "call_1",
        "call_2",
        "call_3",
    ]


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
