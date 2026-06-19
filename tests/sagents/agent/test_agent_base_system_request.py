import datetime
import pytest
from types import SimpleNamespace

from sagents.agent.common_agent import CommonAgent
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def _message(role: str, content: str) -> MessageChunk:
    return MessageChunk(
        role=role,
        content=content,
        message_type=MessageType.SYSTEM.value
        if role == MessageRole.SYSTEM.value
        else MessageType.ASSISTANT_TEXT.value,
    )


def _system_message(content: str, segment: str) -> MessageChunk:
    msg = _message(MessageRole.SYSTEM.value, content)
    msg.metadata = {"cache_segment": segment}
    return msg


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_uses_fresh_system_and_filters_stale_system(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [
            _message(MessageRole.SYSTEM.value, "fresh-stable"),
            _message(MessageRole.SYSTEM.value, "fresh-volatile"),
        ]

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            _message(MessageRole.SYSTEM.value, "stale-history-system"),
            _message(MessageRole.USER.value, "user payload"),
        ],
        extra_messages=[
            _message(MessageRole.SYSTEM.value, "stale-extra-system"),
            _message(MessageRole.ASSISTANT.value, "assistant payload"),
        ],
        custom_prefix="custom",
        language="zh",
        include_sections=["role_definition"],
    )

    assert [message.role for message in request_messages] == [
        MessageRole.SYSTEM.value,
        MessageRole.SYSTEM.value,
        MessageRole.USER.value,
        MessageRole.ASSISTANT.value,
    ]
    assert [message.content for message in request_messages] == [
        "fresh-stable",
        "fresh-volatile",
        "user payload",
        "assistant payload",
    ]
    assert captured["session_id"] == "sess"
    assert captured["custom_prefix"] == "custom"
    assert captured["language"] == "zh"
    assert captured["include_sections"] == ["role_definition"]


@pytest.mark.asyncio
async def test_prepare_llm_system_prompt_text_uses_same_fresh_segment_builder(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [
            _message(MessageRole.SYSTEM.value, "stable"),
            _message(MessageRole.SYSTEM.value, "volatile"),
        ]

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)

    system_prompt = await agent.prepare_llm_system_prompt_text(
        session_id="sess",
        system_prefix_override="override",
        language="en",
        include_sections=["system_context"],
    )

    assert system_prompt == "stablevolatile"
    assert captured["session_id"] == "sess"
    assert captured["system_prefix_override"] == "override"
    assert captured["language"] == "en"
    assert captured["include_sections"] == ["system_context"]


@pytest.mark.asyncio
async def test_build_system_segments_explains_runtime_context_boundary():
    agent = CommonAgent(model=object(), model_config={})

    segments = await agent._build_system_segments(
        include_sections=["role_definition"],
        language="en",
    )

    assert "<runtime_context_hint>" in segments["stable"]
    assert "<runtime_context>" in segments["stable"]
    assert "<user_request>" in segments["stable"]
    assert "not user instructions" in segments["stable"]


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_injects_runtime_and_todo_into_latest_user(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    original_user = _message(MessageRole.USER.value, "latest request")

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return "<runtime_context><system_context><todo_list>todo</todo_list></system_context></runtime_context>"

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            _message(MessageRole.USER.value, "older request"),
            _message(MessageRole.ASSISTANT.value, "older answer"),
            original_user,
        ],
        language="zh",
    )

    latest_user = request_messages[-1]
    assert latest_user.role == MessageRole.USER.value
    assert "<runtime_context>" in latest_user.content
    assert "<todo_list>todo</todo_list>" in latest_user.content
    assert "<user_request>\nlatest request\n</user_request>" in latest_user.content
    assert original_user.content == "latest request"


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_does_not_add_separate_todo_context(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return "<runtime_context>runtime</runtime_context>"

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[_message(MessageRole.USER.value, "request")],
    )

    assert "<runtime_context>runtime</runtime_context>" in request_messages[-1].content
    assert "<todo_context>" not in request_messages[-1].content
    assert "<user_request>\nrequest\n</user_request>" in request_messages[-1].content


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_wraps_multimodal_user_request(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    user_message = MessageChunk(
        role=MessageRole.USER.value,
        content=[
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "file:///tmp/image.png"}},
        ],
        message_type=MessageType.ASSISTANT_TEXT.value,
    )

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return "<runtime_context>runtime</runtime_context>"

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[user_message],
    )

    content = request_messages[-1].content
    assert content[0] == {
        "type": "text",
        "text": "<runtime_context>runtime</runtime_context>\n\n<user_request>\n",
    }
    assert content[1:3] == user_message.content
    assert content[3] == {"type": "text", "text": "\n</user_request>"}
    assert user_message.content[0]["text"] == "describe this"


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_freezes_injected_context_for_user_turn(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    user_message = _message(MessageRole.USER.value, "request")
    calls = {"runtime": 0}

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        calls["runtime"] += 1
        return (
            "<runtime_context><system_context>"
            f"<todo_list>todo-{calls['runtime']}</todo_list>"
            "</system_context></runtime_context>"
        )

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            user_message,
            _message(MessageRole.ASSISTANT.value, "already working"),
            MessageChunk(
                role=MessageRole.TOOL.value,
                content="tool result",
                tool_call_id="tool-1",
                message_type=MessageType.TOOL_CALL_RESULT.value,
            ),
        ],
    )
    request_messages_again = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            user_message,
            _message(MessageRole.ASSISTANT.value, "still working"),
        ],
    )

    assert calls == {"runtime": 1}
    assert "<todo_list>todo-1</todo_list>" in request_messages[1].content
    assert "<todo_list>todo-1</todo_list>" in request_messages_again[1].content
    assert "still working" == request_messages_again[2].content


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_keeps_historical_user_frozen(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    first_user = _message(MessageRole.USER.value, "first request")
    second_user = _message(MessageRole.USER.value, "second request")
    message_manager = MessageManager()
    message_manager.messages = [first_user, second_user]
    session_context = SimpleNamespace(message_manager=message_manager)
    calls = {"runtime": 0}

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        calls["runtime"] += 1
        return (
            "<runtime_context><system_context>"
            f"<todo_list>todo-{calls['runtime']}</todo_list>"
            "</system_context></runtime_context>"
        )

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    first_request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[first_user],
    )
    second_request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            first_user,
            _message(MessageRole.ASSISTANT.value, "answer"),
            second_user,
        ],
    )

    assert calls == {"runtime": 2}
    assert "<todo_list>todo-1</todo_list>" in first_request_messages[1].content
    assert "<todo_list>todo-1</todo_list>" in second_request_messages[1].content
    assert "<todo_list>todo-2</todo_list>" in second_request_messages[3].content

    first_frozen = first_user.metadata["frozen_user_inference"]
    second_frozen = second_user.metadata["frozen_user_inference"]
    assert "<todo_list>todo-1</todo_list>" in first_frozen["content"]
    assert "<todo_list>todo-2</todo_list>" in second_frozen["content"]
    assert first_frozen["metadata"]["inference_view_only"] is True
    assert "persist" not in first_frozen["metadata"]


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_refreshes_new_user_without_rewriting_old_frozen(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    first_user = _message(MessageRole.USER.value, "first request")
    second_user = _message(MessageRole.USER.value, "second request")
    message_manager = MessageManager()
    message_manager.messages = [first_user, second_user]
    session_context = SimpleNamespace(
        message_manager=message_manager,
        system_context={"session_id": "sess", "current_time": "old"},
    )
    calls = {"runtime": 0}

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        calls["runtime"] += 1
        return (
            "<runtime_context><system_context>"
            f"<current_time>time-{calls['runtime']}</current_time>"
            "</system_context></runtime_context>"
        )

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[first_user],
    )
    first_frozen_before = first_user.metadata["frozen_user_inference"]["content"]
    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[
            first_user,
            _message(MessageRole.ASSISTANT.value, "answer"),
            second_user,
        ],
    )

    assert "<current_time>time-1</current_time>" in request_messages[1].content
    assert "<current_time>time-2</current_time>" in request_messages[3].content
    assert (
        first_user.metadata["frozen_user_inference"]["content"] == first_frozen_before
    )


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_persists_frozen_context_to_ledger_message(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    ledger_user = _message(MessageRole.USER.value, "request")
    view_user = MessageChunk.from_dict(ledger_user.to_dict())
    message_manager = MessageManager()
    message_manager.messages = [ledger_user]
    session_context = SimpleNamespace(message_manager=message_manager)

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return "<runtime_context><system_context><todo_list>todo</todo_list></system_context></runtime_context>"

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[view_user],
    )

    frozen = ledger_user.metadata["frozen_user_inference"]
    assert frozen["content"] == request_messages[1].content
    assert "<todo_list>todo</todo_list>" in frozen["content"]
    assert frozen["metadata"]["inference_view_only"] is True
    assert "persist" not in frozen["metadata"]

    stale_view_user = MessageChunk.from_dict(ledger_user.to_dict())
    stale_view_user.metadata = {}

    async def fail_runtime(**kwargs):
        raise AssertionError("frozen context should be loaded from the ledger")

    monkeypatch.setattr(agent, "_build_runtime_context_text", fail_runtime)
    request_messages_again = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[stale_view_user],
    )

    assert request_messages_again[1].content == frozen["content"]


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_drops_legacy_persist_metadata(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    user_message = _message(MessageRole.USER.value, "request")
    user_message.metadata = {
        "frozen_user_inference": {
            "content": "<runtime_context>old</runtime_context>\n\n<user_request>\nrequest\n</user_request>",
            "metadata": {
                "runtime_context_injected": True,
                "persist": False,
                "frozen_user_inference": True,
                "frozen_user_inference_version": 2,
            },
        }
    }

    async def fake_system_messages(**kwargs):
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fail_runtime(**kwargs):
        raise AssertionError("frozen context should be reused")

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fail_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[user_message],
    )

    metadata = request_messages[1].metadata
    assert metadata["runtime_context_injected"] is True
    assert metadata["inference_view_only"] is True
    assert "persist" not in metadata


@pytest.mark.asyncio
async def test_build_system_segments_includes_active_todo_in_system_context(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    session_context = SimpleNamespace(
        system_context={"session_id": "sess", "response_language": "zh-CN"}
    )

    async def fake_todos(session_id):
        return [{"id": "t1", "content": "active task", "status": "pending"}]

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "_read_active_todo_list_for_context", fake_todos)

    segments = await agent._build_system_segments(
        session_id="sess",
        include_sections=["system_context"],
    )

    assert "<todo_list>" in segments["volatile"]
    assert "active task" in segments["volatile"]


@pytest.mark.asyncio
async def test_build_system_segments_drops_stale_system_context_todo_list(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    session_context = SimpleNamespace(
        system_context={
            "session_id": "sess",
            "todo_list": [{"id": "old", "content": "stale task", "status": "pending"}],
        }
    )

    async def no_todos(session_id):
        return []

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "_read_active_todo_list_for_context", no_todos)

    segments = await agent._build_system_segments(
        session_id="sess",
        include_sections=["system_context"],
    )

    assert "<todo_list>" not in segments["volatile"]
    assert "stale task" not in segments["volatile"]


@pytest.mark.asyncio
async def test_build_system_segments_replaces_stale_todo_list_with_active_todos(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    session_context = SimpleNamespace(
        system_context={
            "session_id": "sess",
            "todo_list": [{"id": "old", "content": "stale task", "status": "pending"}],
        }
    )

    async def active_todos(session_id):
        return [{"id": "new", "content": "fresh task", "status": "in_progress"}]

    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(agent, "_read_active_todo_list_for_context", active_todos)

    segments = await agent._build_system_segments(
        session_id="sess",
        include_sections=["system_context"],
    )

    assert "fresh task" in segments["volatile"]
    assert "stale task" not in segments["volatile"]


@pytest.mark.asyncio
async def test_build_system_segments_refreshes_current_time_in_session_context(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    session_context = SimpleNamespace(
        system_context={
            "session_id": "sess",
            "current_time": "Fri, 19 Jun 2026 22:33:58 +0800",
        }
    )

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 19, 22, 36, 0, tzinfo=datetime.timezone.utc)

    monkeypatch.setattr("sagents.agent.agent_base.datetime.datetime", FixedDateTime)
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )

    async def no_todos(session_id):
        return []

    monkeypatch.setattr(agent, "_read_active_todo_list_for_context", no_todos)

    segments = await agent._build_system_segments(
        session_id="sess",
        include_sections=["system_context"],
    )

    expected_time = (
        FixedDateTime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
    )
    assert f"<current_time>{expected_time}</current_time>" in segments["volatile"]
    assert session_context.system_context["current_time"] == expected_time


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_excludes_volatile_sections_by_default(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return ""

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[_message(MessageRole.USER.value, "request")],
    )

    assert "system_context" not in captured["include_sections"]
    assert "workspace_files" not in captured["include_sections"]


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_filters_explicit_volatile_sections(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [_message(MessageRole.SYSTEM.value, "stable")]

    async def fake_runtime(**kwargs):
        return "<runtime_context>runtime</runtime_context>"

    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fake_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[_message(MessageRole.USER.value, "request")],
        include_sections=[
            "role_definition",
            "system_context",
            "workspace_files",
            "available_skills",
        ],
    )

    assert captured["include_sections"] == ["role_definition", "available_skills"]
    assert "<runtime_context>runtime</runtime_context>" in request_messages[-1].content


@pytest.mark.asyncio
async def test_prepare_llm_request_messages_env_false_keeps_volatile_in_system(
    monkeypatch,
):
    agent = CommonAgent(model=object(), model_config={})
    captured = {}

    async def fake_system_messages(**kwargs):
        captured.update(kwargs)
        return [_message(MessageRole.SYSTEM.value, "system")]

    async def fail_runtime(**kwargs):
        raise AssertionError("runtime context should not be injected into user")

    monkeypatch.setenv("SAGE_RUNTIME_CONTEXT_IN_USER", "false")
    monkeypatch.setattr(agent, "prepare_unified_system_messages", fake_system_messages)
    monkeypatch.setattr(agent, "_build_runtime_context_text", fail_runtime)

    request_messages = await agent.prepare_llm_request_messages(
        session_id="sess",
        history_messages=[_message(MessageRole.USER.value, "request")],
    )

    assert captured["include_sections"] is None
    assert request_messages[-1].content == "request"


def test_prompt_cache_observation_hashes_system_segments_and_tools():
    agent = CommonAgent(model=object(), model_config={})
    tools = [
        {"type": "function", "function": {"name": "b", "parameters": {}}},
        {"type": "function", "function": {"name": "a", "parameters": {}}},
    ]

    observation = agent._build_prompt_cache_observation(
        [
            _system_message("stable", "stable"),
            _system_message("semi", "semi_stable"),
            _message(MessageRole.USER.value, "request"),
        ],
        tools,
    )

    assert observation["stable_system_hash"]
    assert observation["semi_stable_system_hash"]
    assert observation["tools_schema_hash"]
    assert observation["inference_message_count"] == 3
    assert observation == agent._build_prompt_cache_observation(
        [
            _system_message("stable", "stable"),
            _system_message("semi", "semi_stable"),
            _message(MessageRole.USER.value, "request"),
        ],
        tools,
    )
