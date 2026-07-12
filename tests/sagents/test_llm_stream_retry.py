import pytest
import httpx

from openai import APIConnectionError
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
        self.requests = []

    async def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
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


@pytest.mark.asyncio
async def test_llm_stream_consumes_next_request_message_after_first_chunk():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None

    class FakeSessionContext:
        def __init__(self):
            self.calls = []

        def mark_llm_messages_consumed(self, message_ids, logical_request_id):
            self.calls.append((list(message_ids), logical_request_id))

        def add_llm_request(self, request, response):
            pass

    context = FakeSessionContext()
    agent._get_live_session_context = lambda session_id: context
    notice = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="internal retry guidance",
        message_id="notice-once",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    chunks = []
    async for chunk in agent._call_llm_streaming(
        messages=[MessageChunk(role=MessageRole.USER.value, content="run"), notice],
        session_id="sid",
        step_name="test",
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert len(context.calls) == 1
    assert context.calls[0][0] == ["notice-once"]
    sent_messages = client.chat.completions.requests[0]["messages"]
    assert "<runtime_diagnostic" in sent_messages[-1]["content"]


@pytest.mark.asyncio
async def test_llm_stream_consumes_only_next_request_messages_in_final_payload():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None

    class FakeSessionContext:
        def __init__(self):
            self.calls = []

        def mark_llm_messages_consumed(self, message_ids, logical_request_id):
            self.calls.append((list(message_ids), logical_request_id))

        def add_llm_request(self, request, response):
            pass

    context = FakeSessionContext()
    agent._get_live_session_context = lambda session_id: context
    included_notice = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="retry with valid arguments",
        message_id="included-notice",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )
    dropped_invalid_call = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=None,
        tool_calls=[
            {
                "id": "bad-call",
                "type": "function",
                "function": {"name": "todo_write", "arguments": '{"tasks"'},
            }
        ],
        message_id="dropped-notice",
        message_type=MessageType.TOOL_CALL.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    async for _ in agent._call_llm_streaming(
        messages=[
            MessageChunk(role=MessageRole.USER.value, content="run"),
            included_notice,
            dropped_invalid_call,
        ],
        session_id="sid",
        step_name="test",
    ):
        pass

    assert len(context.calls) == 1
    assert context.calls[0][0] == ["included-notice"]
    sent_messages = client.chat.completions.requests[0]["messages"]
    assert all(message.get("tool_calls") is None for message in sent_messages)


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
        sage_client,
        DummyObservabilityManager(),  # pyright: ignore[reportArgumentType]
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
async def test_network_retry_reuses_frozen_provider_payload(monkeypatch):
    async def fast_sleep(_seconds):
        return None

    process_calls = 0

    async def process_once(message):
        nonlocal process_calls
        process_calls += 1
        return message

    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", fast_sleep)
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(httpx.ReadTimeout("no bytes yet")),
            _attempt_yields(_content_chunk("retry succeeded")),
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._process_multimodal_content = process_once

    async for _ in agent._call_llm_streaming(
        [MessageChunk(role=MessageRole.USER.value, content="run")],
        model_config_override={"response_format": {"type": "json_object"}},
        enable_thinking=False,
    ):
        pass

    assert client.chat.completions.calls == 2
    first_request, retry_request = client.chat.completions.requests
    assert first_request["messages"] == retry_request["messages"]
    assert first_request["response_format"] == retry_request["response_format"]
    assert process_calls == 1


class _RecordingSessionContext:
    def __init__(self):
        self.llm_requests_logs = []

    def add_llm_request(self, request, response):
        self.llm_requests_logs.append({"request": request, "response": response})

    @property
    def message_manager(self):
        return self

    def update_token_ratio(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_streaming_call_records_llm_request_after_connection_error_retry_success(
    monkeypatch,
):
    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", fast_sleep)
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(
                APIConnectionError(
                    message="Connection error.",
                    request=httpx.Request(
                        "POST", "https://api.openai.com/v1/chat/completions"
                    ),
                )
            ),
            _attempt_yields(_content_chunk("retry succeeded")),
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})  # pyright: ignore[reportArgumentType]
    session_context = _RecordingSessionContext()
    agent._get_live_session_context = lambda session_id: session_context
    messages = [MessageChunk(role=MessageRole.USER.value, content="run")]

    chunks = []
    async for chunk in agent._call_llm_streaming(
        messages,
        session_id="sess_retry_log",
        step_name="direct_execution",
        enable_thinking=False,
    ):  # pyright: ignore[reportArgumentType]
        chunks.append(chunk)

    assert client.chat.completions.calls == 2
    assert len(session_context.llm_requests_logs) == 1
    recorded = session_context.llm_requests_logs[0]
    assert recorded["request"]["step_name"] == "direct_execution"
    assert recorded["response"] is not None
    assert (
        recorded["response"].choices[0].message.content  # pyright: ignore[reportOptionalMemberAccess,reportAttributeAccessIssue]
        == "retry succeeded"
    )


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
async def test_simple_agent_closes_partial_tool_call_in_low_latency_mode(monkeypatch):
    monkeypatch.setenv("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false")
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
    assert chunks[-1].message_type == MessageType.AGENT_EXECUTION_ERROR.value
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
