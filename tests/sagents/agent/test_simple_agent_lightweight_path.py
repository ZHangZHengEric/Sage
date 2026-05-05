import asyncio
from unittest.mock import AsyncMock, MagicMock

from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def _collect_async_batches(generator):
    async def _collect():
        result = []
        async for batch in generator:
            result.append(batch)
        return result

    return asyncio.run(_collect())


def test_simple_agent_lightweight_prompt_uses_minimal_tools_and_sections():
    agent = SimpleAgent(model=MagicMock(), model_config={})
    session_context = MagicMock()
    session_context.session_id = "session-1"
    session_context.get_language.return_value = "en"
    session_context.agent_config = {"max_loop_count": 50}
    session_context.audit_status = {}
    session_context.message_manager.extract_all_context_messages.return_value = [
        MessageChunk(role="user", content="hello")
    ]
    session_context.tool_manager.list_all_tools_name.return_value = ["turn_status", "todo_write"]
    session_context.tool_manager.get_openai_tools.return_value = [
        {"function": {"name": "turn_status"}},
        {"function": {"name": "todo_write"}},
    ]
    agent._should_abort_due_to_session = MagicMock(return_value=False)

    captured = {}

    async def _fake_prepare_unified_system_messages(*args, **kwargs):
        captured["include_sections"] = kwargs.get("include_sections")
        return [MessageChunk(role="system", content="sys")]

    async def _fake_execute_loop(*args, **kwargs):
        captured["tools_json"] = kwargs.get("tools_json")
        captured["system_sections"] = kwargs.get("system_sections")
        if False:
            yield []

    agent.prepare_unified_system_messages = AsyncMock(side_effect=_fake_prepare_unified_system_messages)
    agent._execute_loop = _fake_execute_loop

    result = _collect_async_batches(agent.run_stream(session_context))

    assert result == []
    assert captured["tools_json"] == [{"function": {"name": "turn_status"}}]
    assert captured["include_sections"] == ["role_definition", "system_context"]
    assert captured["system_sections"] == ["role_definition", "system_context"]


def test_simple_agent_requests_turn_status_after_lightweight_text_response():
    agent = SimpleAgent(model=MagicMock(), model_config={})

    chunks = [
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="Hello! I'm your AI Execution Assistant.",
            message_type=MessageType.DO_SUBTASK_RESULT.value,
        )
    ]
    tools_json = [{"function": {"name": "turn_status"}}]

    assert agent._should_request_turn_status_after_text_response(chunks, tools_json)
