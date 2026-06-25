import pytest
import httpx

from openai.types.chat import chat_completion_chunk

from sagents.agent.agent_base import AgentBase, PartialStreamConsumedError
from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.llm.sage_openai import SageAsyncOpenAI
from sagents.observability.agent_runtime import ObservableAsyncOpenAI


class DummyAgent(AgentBase):
    async def run_stream(self, session_context):
        if False:
            yield []


class FakeCompletions:
    def __init__(self, attempts=None):
        self.calls = 0
        self.attempts = attempts

    async def create(self, **kwargs):
        self.calls += 1
        if self.attempts is not None:
            return self.attempts[self.calls - 1]()

        async def first_attempt():
            yield _tool_call_chunk("call_partial", '{"tasks')
            raise httpx.ReadTimeout("stream stalled after partial tool call")

        async def second_attempt():
            yield _tool_call_chunk("call_retry", '{"tasks":[]}')

        return first_attempt() if self.calls == 1 else second_attempt()


class FakeChat:
    def __init__(self, attempts=None):
        self.completions = FakeCompletions(attempts=attempts)


class FakeClient:
    def __init__(self, attempts=None):
        self.chat = FakeChat(attempts=attempts)


class FakeSageCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _attempt_yields(_content_chunk("ok"))()


class FakeSageClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeSageCompletions()


class DummyObservabilityManager:
    def on_llm_start(self, *args, **kwargs):
        pass

    def on_llm_end(self, *args, **kwargs):
        pass

    def on_llm_error(self, *args, **kwargs):
        pass


def _tool_call_chunk(call_id, arguments):
    return chat_completion_chunk.ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model="gpt-test",
        choices=[
            chat_completion_chunk.Choice(
                index=0,
                delta=chat_completion_chunk.ChoiceDelta(
                    tool_calls=[
                        chat_completion_chunk.ChoiceDeltaToolCall(
                            index=0,
                            id=call_id,
                            type="function",
                            function=chat_completion_chunk.ChoiceDeltaToolCallFunction(
                                name="todo_write",
                                arguments=arguments,
                            ),
                        )
                    ]
                ),
                finish_reason=None,
            )
        ],
    )


def _content_chunk(content, *, finish_reason=None):
    return chat_completion_chunk.ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model="gpt-test",
        choices=[
            chat_completion_chunk.Choice(
                index=0,
                delta=chat_completion_chunk.ChoiceDelta(content=content),
                finish_reason=finish_reason,
            )
        ],
    )


def _attempt_raises_before_yield(exc):
    async def attempt():
        if False:
            yield None
        raise exc

    return attempt


def _attempt_yields_then_raises(chunk, exc):
    async def attempt():
        yield chunk
        raise exc

    return attempt


def _attempt_yields(*chunks):
    async def attempt():
        for chunk in chunks:
            yield chunk

    return attempt


@pytest.mark.asyncio
async def test_streaming_call_does_not_retry_after_partial_chunk_is_yielded():
    client = FakeClient()
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]

    chunks = []
    with pytest.raises(PartialStreamConsumedError):
        async for chunk in agent._call_llm_streaming(messages, enable_thinking=False):  # pyright: ignore[reportArgumentType]
            chunks.append(chunk)

    assert client.chat.completions.calls == 1


@pytest.mark.asyncio
async def test_fast_model_type_survives_observable_sage_wrapper():
    standard_client = FakeSageClient()
    fast_client = FakeSageClient()
    sage_client = SageAsyncOpenAI(
        standard_client=standard_client,  # pyright: ignore[reportArgumentType]
        fast_client=fast_client,  # pyright: ignore[reportArgumentType]
        model_name="standard-model",
        fast_model_name="fast-model",
    )
    observable_client = ObservableAsyncOpenAI(
        sage_client, DummyObservabilityManager()  # pyright: ignore[reportArgumentType]
    )
    agent = DummyAgent(
        model=observable_client,  # pyright: ignore[reportArgumentType]
        model_config={
            "model": "standard-model",
            "fast_model_name": "fast-model",
        },
    )

    chunks = []
    async for chunk in agent._call_llm_streaming(
        messages=[{"role": "user", "content": "hello"}],
        step_name="tool_suggestion",
        model_config_override={"model_type": "fast"},
        enable_thinking=False,
    ):
        chunks.append(chunk)

    assert chunks
    assert standard_client.chat.completions.calls == []
    assert fast_client.chat.completions.calls[0]["model"] == "fast-model"
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_streaming_call_still_retries_if_timeout_happens_before_any_chunk(
    monkeypatch,
):
    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", fast_sleep)
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(httpx.ReadTimeout("no bytes yet")),
            _attempt_yields(_content_chunk("retry succeeded")),
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]

    chunks = []
    async for chunk in agent._call_llm_streaming(messages, enable_thinking=False):  # pyright: ignore[reportArgumentType]
        chunks.append(chunk)

    assert client.chat.completions.calls == 2
    assert [chunk.choices[0].delta.content for chunk in chunks] == ["retry succeeded"]


@pytest.mark.asyncio
async def test_streaming_call_does_not_retry_after_text_chunk_is_yielded():
    client = FakeClient(
        attempts=[
            _attempt_yields_then_raises(
                _content_chunk("partial text"),
                httpx.ReadTimeout("stream stalled after text"),
            ),
            _attempt_yields(_content_chunk("should not be used")),
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]

    chunks = []
    with pytest.raises(PartialStreamConsumedError):
        async for chunk in agent._call_llm_streaming(messages, enable_thinking=False):  # pyright: ignore[reportArgumentType]
            chunks.append(chunk)

    assert client.chat.completions.calls == 1
    assert [chunk.choices[0].delta.content for chunk in chunks] == ["partial text"]


@pytest.mark.asyncio
async def test_streaming_call_rejects_raw_dict_system_messages():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("unused"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]

    with pytest.raises(ValueError, match="Raw dict system messages"):
        async for _ in agent._call_llm_streaming(
            [
                {"role": "system", "content": "stale system"},
                {"role": "user", "content": "run"},
            ],
            enable_thinking=False,
        ):
            pass

    assert client.chat.completions.calls == 0


@pytest.mark.asyncio
async def test_streaming_call_rejects_non_leading_system_message_chunks():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("unused"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]

    with pytest.raises(ValueError, match="leading request prefix"):
        async for _ in agent._call_llm_streaming(
            [
                MessageChunk(role=MessageRole.USER.value, content="run"),
                MessageChunk(role=MessageRole.SYSTEM.value, content="late system"),
            ],
            enable_thinking=False,
        ):
            pass

    assert client.chat.completions.calls == 0


@pytest.mark.asyncio
async def test_simple_agent_closes_streamed_partial_tool_call_when_stream_times_out():
    client = FakeClient()
    agent = SimpleAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "todo_write",
                "description": "write todos",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    chunks = []
    async for chunk, is_complete in agent._call_llm_and_process_response(
        messages_input=messages,
        tools_json=tools,
        tool_manager=None,
        session_id="sid",
    ):
        chunks.extend(chunk)
        if is_complete:
            break

    assert client.chat.completions.calls == 1
    assert [chunk.role for chunk in chunks] == ["assistant", "tool", "assistant"]
    assert chunks[0].tool_calls[0].id == "call_partial"
    assert chunks[1].tool_call_id == "call_partial"
    assert "discarded" in chunks[1].content.lower()
    assert chunks[-1].role == "assistant"
    assert (
        len(MessageManager.convert_messages_to_dict_for_request(messages + chunks)) == 4
    )


@pytest.mark.asyncio
async def test_simple_agent_does_not_add_synthetic_tool_result_when_tool_call_was_not_streamed(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "true")
    client = FakeClient()
    agent = SimpleAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "todo_write",
                "description": "write todos",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    chunks = []
    async for chunk, is_complete in agent._call_llm_and_process_response(
        messages_input=messages,
        tools_json=tools,
        tool_manager=None,
        session_id="sid",
    ):
        chunks.extend(chunk)
        if is_complete:
            break

    non_empty = [
        chunk for chunk in chunks if chunk.message_type != MessageType.EMPTY.value
    ]
    assert client.chat.completions.calls == 1
    assert [chunk.role for chunk in non_empty] == ["assistant"]
    assert non_empty[0].message_type == MessageType.AGENT_EXECUTION_ERROR.value
    assert "incomplete tool call was discarded" in non_empty[0].content
