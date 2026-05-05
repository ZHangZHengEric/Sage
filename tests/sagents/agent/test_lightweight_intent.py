from unittest.mock import AsyncMock, MagicMock
import asyncio

from sagents.agent.lightweight_intent import (
    extract_latest_user_text,
    extract_latest_user_text_from_any,
    should_skip_preflight_for_lightweight_prompt,
)
from sagents.agent.memory_recall_agent import MemoryRecallAgent
from sagents.agent.tool_suggestion_agent import ToolSuggestionAgent
from sagents.context.messages.message import MessageChunk


def _collect_async_batches(generator):
    async def _collect():
        result = []
        async for batch in generator:
            result.append(batch)
        return result

    return asyncio.run(_collect())


def test_should_skip_preflight_for_lightweight_prompt_matches_greetings():
    assert should_skip_preflight_for_lightweight_prompt("hello")
    assert should_skip_preflight_for_lightweight_prompt("你好！")
    assert should_skip_preflight_for_lightweight_prompt("介绍下自己。")
    assert should_skip_preflight_for_lightweight_prompt("Introduce yourself")


def test_should_not_skip_preflight_for_actionable_prompt():
    assert not should_skip_preflight_for_lightweight_prompt("inspect this repo")
    assert not should_skip_preflight_for_lightweight_prompt("帮我调试这个错误")
    assert not should_skip_preflight_for_lightweight_prompt("hello, edit app.py")


def test_extract_latest_user_text_returns_last_user_message():
    messages = [
        MessageChunk(role="user", content="hello"),
        MessageChunk(role="assistant", content="hi"),
        MessageChunk(role="user", content="介绍下自己。"),
    ]

    assert extract_latest_user_text(messages) == "介绍下自己。"


def test_extract_latest_user_text_from_any_supports_dict_messages():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "Introduce yourself"},
    ]

    assert extract_latest_user_text_from_any(messages) == "Introduce yourself"


def test_memory_recall_agent_skips_lightweight_prompt():
    agent = MemoryRecallAgent(model=MagicMock(), model_config={})
    session_context = MagicMock()
    session_context.session_id = "session-1"
    session_context.tool_manager.list_all_tools_name.return_value = ["search_memory"]
    session_context.message_manager.extract_all_context_messages.return_value = [
        MessageChunk(role="user", content="hello")
    ]
    session_context.message_manager.context_budget_manager.budget_info = None

    agent._recall_memories_stream = AsyncMock()

    result = _collect_async_batches(agent.run_stream(session_context))

    assert result == [[]]
    agent._recall_memories_stream.assert_not_called()


def test_tool_suggestion_agent_skips_lightweight_prompt():
    agent = ToolSuggestionAgent(model=MagicMock(), model_config={})
    session_context = MagicMock()
    session_context.session_id = "session-1"
    session_context.get_language.return_value = "en"
    session_context.audit_status = {}
    session_context.tool_manager.list_tools_simplified.return_value = [{"name": "file_read"}]
    session_context.message_manager.extract_all_context_messages.return_value = [
        MessageChunk(role="user", content="hello")
    ]
    session_context.message_manager.context_budget_manager.budget_info = None

    agent._analyze_tool_suggestions = AsyncMock()

    result = _collect_async_batches(agent.run_stream(session_context))

    assert result == [[]]
    assert session_context.audit_status["suggested_tools"] == []
    agent._analyze_tool_suggestions.assert_not_called()
