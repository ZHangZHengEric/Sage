import asyncio
from typing import AsyncGenerator, List

import pytest

import sagents.agent.agent_base as agent_base_module
from sagents.agent.agent_base import AgentBase, TOOL_CALL_CONCURRENCY_LIMIT
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


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
