import pytest

from openai.types.chat import chat_completion_chunk

from sagents.agent.agent_base import AgentBase
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.tool.impl.execute_command_tool import ExecuteCommandTool


class DummyAgent(AgentBase):
    async def run_stream(self, session_context):
        if False:
            yield []


def _content_chunk(content):
    return chat_completion_chunk.ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model="gpt-test",
        choices=[
            chat_completion_chunk.Choice(
                index=0,
                delta=chat_completion_chunk.ChoiceDelta(content=content),
                finish_reason="stop",
            )
        ],
    )


def _message_text(message):
    content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return content


def _message_has_cache_control(message):
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(item, dict) and "cache_control" in item for item in content)


@pytest.mark.asyncio
async def test_shell_completion_reminder_preserves_tool_choice_auto(monkeypatch):
    calls = []

    async def fake_create_chat_completion_with_fallback(
        client,
        *,
        model,
        messages,
        model_config,
        response_format=None,
        stream=True,
        stream_options=None,
        extra_body=None,
        **kwargs,
    ):
        calls.append(
            {
                "messages": messages,
                "model_config": dict(model_config),
                "kwargs": dict(kwargs),
            }
        )

        async def stream_gen():
            yield _content_chunk("ok")

        return stream_gen()

    monkeypatch.setattr(
        "sagents.agent.agent_base.create_chat_completion_with_fallback",
        fake_create_chat_completion_with_fallback,
    )
    monkeypatch.setattr(
        ExecuteCommandTool,
        "_COMPLETION_EVENTS",
        {
            "sid": {
                "shtask_1": {
                    "task_id": "shtask_1",
                    "command": "echo done",
                    "exit_code": 0,
                    "elapsed_ms": 12,
                    "tail": "done\n",
                }
            }
        },
    )

    agent = DummyAgent(
        model=object(),  # pyright: ignore[reportArgumentType]
        model_config={
            "model": "gpt-test",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "await_shell",
                        "description": "await shell task",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "tool_choice": "auto",
        },
    )
    messages = [MessageChunk(role=MessageRole.USER.value, content="continue")]

    async for _ in agent._call_llm_streaming(
        messages,  # pyright: ignore[reportArgumentType]
        session_id="sid",
        enable_thinking=False,  # pyright: ignore[reportArgumentType]
    ):
        pass
    async for _ in agent._call_llm_streaming(
        messages,  # pyright: ignore[reportArgumentType]
        session_id="sid",
        enable_thinking=False,  # pyright: ignore[reportArgumentType]
    ):
        pass

    assert calls[0]["model_config"]["tool_choice"] == "auto"
    assert calls[0]["kwargs"]["tool_choice"] == "auto"
    assert "<system_reminder>" in _message_text(calls[0]["messages"][-1])
    assert "shtask_1" in _message_text(calls[0]["messages"][-1])

    assert calls[1]["model_config"]["tool_choice"] == "auto"
    assert calls[1]["kwargs"]["tool_choice"] == "auto"
    assert all(
        "<system_reminder>" not in _message_text(msg) for msg in calls[1]["messages"]
    )


@pytest.mark.asyncio
async def test_llm_streaming_request_does_not_add_explicit_prompt_cache_control(
    monkeypatch,
):
    calls = []

    async def fake_create_chat_completion_with_fallback(
        client,
        *,
        model,
        messages,
        model_config,
        response_format=None,
        stream=True,
        stream_options=None,
        extra_body=None,
        **kwargs,
    ):
        calls.append({"messages": messages})

        async def stream_gen():
            yield _content_chunk("ok")

        return stream_gen()

    monkeypatch.setattr(
        "sagents.agent.agent_base.create_chat_completion_with_fallback",
        fake_create_chat_completion_with_fallback,
    )

    agent = DummyAgent(
        model=object(),  # pyright: ignore[reportArgumentType]
        model_config={"model": "gpt-test"},
    )
    messages = [
        MessageChunk(
            role=MessageRole.SYSTEM.value,
            content="stable system prompt" * 80,
            metadata={"cache_segment": "stable"},
        ),
        MessageChunk(
            role=MessageRole.USER.value,
            content="please answer" * 100,
        ),
    ]

    async for _ in agent._call_llm_streaming(
        messages,  # pyright: ignore[reportArgumentType]
        enable_thinking=False,  # pyright: ignore[reportArgumentType]
    ):
        pass

    assert calls
    assert all(not _message_has_cache_control(msg) for msg in calls[0]["messages"])
