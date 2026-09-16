import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.agent.memory_recall_agent import MemoryRecallAgent
from sagents.agent.tool_suggestion_agent import ToolSuggestionAgent
from sagents.utils.model_deadline import FirstChunkDeadlineStream, preflight_timeout_seconds


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '0', 'bad', '601'])
def test_invalid_budget_uses_default(monkeypatch, value):
    monkeypatch.setenv('SAGE_PREFLIGHT_TIMEOUT_SECONDS', value)
    assert preflight_timeout_seconds() == 10


@pytest.mark.asyncio
async def test_memory_stall_after_first_chunk_closes_and_continues(monkeypatch):
    monkeypatch.setenv('SAGE_PREFLIGHT_TIMEOUT_SECONDS', '.03')
    closed = []
    async def source():
        try:
            yield 'partial query'
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    stream = FirstChunkDeadlineStream(source(), asyncio.get_running_loop().time() + 1)
    async def generate(**kwargs):
        return ''.join([chunk async for chunk in stream])
    agent = MemoryRecallAgent(model=None)
    monkeypatch.setattr(agent, '_generate_search_query', generate)
    search = AsyncMock()
    monkeypatch.setattr(agent, '_search_memory', search)
    result = [chunk async for chunk in agent._recall_memories_stream([], None)]
    assert result == [[]]
    assert closed == [True]
    assert stream.closed
    search.assert_not_called()


@pytest.mark.asyncio
async def test_memory_external_cancel_propagates(monkeypatch):
    entered = asyncio.Event()
    async def generate(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    agent = MemoryRecallAgent(model=None)
    monkeypatch.setattr(agent, '_generate_search_query', generate)
    async def consume():
        return [chunk async for chunk in agent._recall_memories_stream([], None)]
    task = asyncio.create_task(consume())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_tool_selection_budget_covers_all_invalid_result_retries(monkeypatch):
    monkeypatch.setenv('SAGE_PREFLIGHT_TIMEOUT_SECONDS', '.05')
    agent = ToolSuggestionAgent(model=None)
    monkeypatch.setattr(agent, 'prepare_unified_system_messages', AsyncMock(return_value=[]))
    monkeypatch.setattr(agent, '_build_skill_context', lambda ctx: '')
    calls = []
    async def suggestions(*args):
        calls.append(True)
        await asyncio.sleep(.03)
        return []
    monkeypatch.setattr(agent, '_get_tool_suggestions', suggestions)
    ctx = SimpleNamespace(
        tool_manager=SimpleNamespace(list_tools_simplified=lambda **kw: [
            {'name': 'file_read', 'description': 'read'},
            {'name': 'custom_tool', 'description': 'custom'},
            {'name': 'complete_task', 'description': 'done'},
        ]),
        get_language=lambda: 'en', session_id='budget-test', effective_skill_manager=None,
    )
    result = await agent._analyze_tool_suggestions([], ctx)
    assert len(calls) == 2
    assert set(result) == {'file_read', 'custom_tool'}
