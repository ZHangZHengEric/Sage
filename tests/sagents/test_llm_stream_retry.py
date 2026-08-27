import asyncio
import threading
from types import SimpleNamespace

import pytest
import httpx

from openai import APIConnectionError, APIError
from openai.types.chat import chat_completion_chunk
from openai.types.completion_usage import CompletionUsage

from sagents.agent.agent_base import (
    AgentBase,
    PartialStreamConsumedError,
    ProviderContextWindowExceededError,
    _is_context_length_error,
    _is_rate_limit_error,
)
from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import (
    MessageManager,
    SEARCH_MEMORY_TOOL_NAME,
)
from sagents.context.messages.token_accounting import (
    PromptBudgetManager,
    PromptTokenEstimator,
)
from sagents.llm.sage_openai import SageAsyncOpenAI
from sagents.observability.agent_runtime import ObservableAsyncOpenAI


class DummyAgent(AgentBase):
    async def run_stream(self, session_context):
        if False:
            yield []


@pytest.mark.parametrize(
    "message",
    [
        "maximum context length exceeded",
        "context_length_exceeded",
        "context_window_exceeded",
        "input_too_long",
        "Input is too long for the requested model",
        "prompt_too_long",
        "too many input tokens",
        "input length is too long",
    ],
)
def test_context_window_error_detection_accepts_provider_variants(message):
    assert _is_context_length_error(RuntimeError(message))


def test_context_window_error_detection_rejects_context_deadline_timeout():
    assert not _is_context_length_error(RuntimeError("context deadline exceeded"))


@pytest.mark.parametrize(
    "message",
    [
        "input token rate limit exceeded",
        "requested tokens exceed the tokens per minute limit",
        "rate_limit: too many input tokens",
    ],
)
def test_context_window_error_detection_rejects_token_rate_limits(message):
    assert not _is_context_length_error(RuntimeError(message))
    assert _is_rate_limit_error(RuntimeError(message))


def test_prompt_accounting_identity_uses_provider_request_resolution():
    client = FakeClient()
    client.base_url = "https://provider.example/v1"
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})

    model, provider = agent._resolve_prompt_accounting_identity()

    assert model == "gpt-test"
    assert provider == "https://provider.example/v1"


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
async def test_deepseek_tool_request_replays_tool_and_final_answer_reasoning():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "tools": [{"type": "function", "function": {"name": "weather"}}],
            "tool_choice": "required",
        },
    )
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            reasoning_content="need tool",
            message_type=MessageType.REASONING_CONTENT.value,
        ),
        MessageChunk(role="assistant", content="checking"),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="call-1"),
        MessageChunk(
            role="assistant",
            reasoning_content="compose answer",
            message_type=MessageType.REASONING_CONTENT.value,
        ),
        MessageChunk(role="assistant", content="sunny"),
        MessageChunk(role="user", content="and tomorrow?"),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request = client.chat.completions.requests[0]
    assistant_tool_call = request["messages"][1]
    assert assistant_tool_call["content"] == "checking"
    assert assistant_tool_call["reasoning_content"] == "need tool"
    assert assistant_tool_call["tool_calls"][0]["id"] == "call-1"
    final_answer = next(
        message
        for message in request["messages"]
        if message.get("role") == "assistant"
        and message.get("content") == "sunny"
        and not message.get("tool_calls")
    )
    assert final_answer["reasoning_content"] == "compose answer"
    assert "tool_choice" not in request


@pytest.mark.asyncio
async def test_deepseek_request_keeps_message_identity_and_records_provider_view():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    )
    session_context = _RecordingSessionContext()
    agent._get_live_session_context = lambda session_id: session_context
    messages = [
        MessageChunk(
            role="assistant",
            reasoning_content="response a reasoning",
            message_id="response-a",
            message_type=MessageType.REASONING_CONTENT.value,
            agent_name="agent-a",
        ),
        MessageChunk(
            role="assistant",
            content="response a answer",
            message_id="response-a",
            agent_name="agent-a",
        ),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
            message_id="response-b",
            agent_name="agent-a",
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="call-b"),
    ]

    async for _ in agent._call_llm_streaming(
        messages,
        session_id="response-identity-session",
        enable_thinking=True,
    ):
        pass

    request_messages = client.chat.completions.requests[0]["messages"]
    final_answer = next(
        message
        for message in request_messages
        if message.get("content") == "response a answer"
    )
    tool_call = next(
        message for message in request_messages if message.get("tool_calls")
    )
    assert final_answer["reasoning_content"] == "response a reasoning"
    assert tool_call["reasoning_content"] == "no thinking"
    assert all(
        not any(key.startswith("_sage_") for key in message)
        for message in request_messages
    )
    recorded_messages = session_context.llm_requests_logs[0]["request"]["messages"]
    assert recorded_messages == request_messages


@pytest.mark.asyncio
async def test_deepseek_request_does_not_move_reasoning_between_agents_with_same_message_id():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    )
    messages = [
        MessageChunk(
            role="assistant",
            reasoning_content="agent a reasoning",
            message_id="shared-response",
            message_type=MessageType.REASONING_CONTENT.value,
            agent_name="agent-a",
        ),
        MessageChunk(
            role="assistant",
            content="agent b answer",
            message_id="shared-response",
            agent_name="agent-b",
        ),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request_messages = client.chat.completions.requests[0]["messages"]
    final_answer = next(
        message
        for message in request_messages
        if message.get("content") == "agent b answer"
    )
    assert final_answer["reasoning_content"] == "no thinking"


@pytest.mark.asyncio
async def test_deepseek_request_adopts_visible_agent_for_ownerless_reasoning():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    )
    messages = [
        MessageChunk(
            role="assistant",
            reasoning_content="legacy reasoning",
            message_id="shared-response",
            message_type=MessageType.REASONING_CONTENT.value,
        ),
        MessageChunk(
            role="assistant",
            content="agent a answer",
            message_id="shared-response",
            agent_name="agent-a",
        ),
        MessageChunk(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
            message_id="shared-response",
            agent_name="agent-b",
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="call-b"),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request_messages = client.chat.completions.requests[0]["messages"]
    final_answer = next(
        message
        for message in request_messages
        if message.get("content") == "agent a answer"
    )
    tool_call = next(
        message for message in request_messages if message.get("tool_calls")
    )
    assert final_answer["reasoning_content"] == "legacy reasoning"
    assert tool_call["reasoning_content"] == "no thinking"


@pytest.mark.asyncio
async def test_deepseek_replays_tool_call_reasoning_when_current_request_has_no_tools():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    )
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            content="checking",
            reasoning_content="need tool",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="call-1"),
        MessageChunk(role="user", content="summarize without tools"),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request = client.chat.completions.requests[0]
    assistant_tool_call = request["messages"][1]
    assert assistant_tool_call["reasoning_content"] == "need tool"
    assert assistant_tool_call["tool_calls"][0]["id"] == "call-1"
    assert "tools" not in request


@pytest.mark.asyncio
async def test_deepseek_thinking_fills_legacy_tool_turn_without_reasoning():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    )
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            content="checking",
            tool_calls=[
                {
                    "id": "legacy-call",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="legacy-call"),
        MessageChunk(role="assistant", content="It is sunny."),
        MessageChunk(role="user", content="and tomorrow?"),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request_messages = client.chat.completions.requests[0]["messages"]
    tool_call_message = next(
        message for message in request_messages if message.get("tool_calls")
    )
    assert tool_call_message["reasoning_content"] == "no thinking"
    assert tool_call_message["content"] == "checking"
    final_answer = next(
        message
        for message in request_messages
        if message.get("role") == "assistant"
        and message.get("content") == "It is sunny."
    )
    assert final_answer["reasoning_content"] == "no thinking"
    assert [message.get("content") for message in request_messages] == [
        "weather",
        "checking",
        "sunny",
        "It is sunny.",
        "and tomorrow?",
    ]


@pytest.mark.asyncio
async def test_third_party_deepseek_slug_uses_generic_chat_completions_contract():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "deepseek-v4-flash",
            "base_url": "https://example.com/openai/v1",
            "tools": [{"type": "function", "function": {"name": "weather"}}],
            "tool_choice": "required",
        },
    )
    messages = [
        MessageChunk(role="user", content="weather"),
        MessageChunk(
            role="assistant",
            content="checking",
            reasoning_content="private provider-specific reasoning",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "weather", "arguments": "{}"},
                }
            ],
        ),
        MessageChunk(role="tool", content="sunny", tool_call_id="call-1"),
    ]

    async for _ in agent._call_llm_streaming(messages, enable_thinking=True):
        pass

    request = client.chat.completions.requests[0]
    assistant_tool_call = next(
        message for message in request["messages"] if message.get("tool_calls")
    )
    assert "reasoning_content" not in assistant_tool_call
    assert "content" not in assistant_tool_call
    assert request["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_llm_stream_strips_historical_search_memory_at_request_boundary():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    messages = [
        MessageChunk(role=MessageRole.USER.value, content="old request"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=[
                {
                    "id": "search-old",
                    "type": "function",
                    "function": {
                        "name": SEARCH_MEMORY_TOOL_NAME,
                        "arguments": "{}",
                    },
                }
            ],
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content='{"status":"success"}',
            tool_call_id="search-old",
        ),
        MessageChunk(role=MessageRole.USER.value, content="current request"),
    ]

    async for _ in agent._call_llm_streaming(
        messages=messages,
        session_id="sid",
        step_name="test",
    ):
        pass

    sent_messages = client.chat.completions.requests[0]["messages"]
    assert [message["role"] for message in sent_messages] == ["user", "user"]
    assert [message["content"] for message in sent_messages] == [
        "old request",
        "current request",
    ]


@pytest.mark.asyncio
async def test_llm_stream_strips_historical_search_memory_from_dict_messages():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    messages = [
        {"role": "user", "content": "old request"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "search-old",
                    "type": "function",
                    "function": {
                        "name": SEARCH_MEMORY_TOOL_NAME,
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": '{"status":"success"}',
            "tool_call_id": "search-old",
        },
        {"role": "user", "content": "current request"},
    ]

    async for _ in agent._call_llm_streaming(
        messages=messages,
        session_id="sid",
        step_name="test",
    ):
        pass

    sent_messages = client.chat.completions.requests[0]["messages"]
    assert sent_messages == [
        {"role": "user", "content": "old request"},
        {"role": "user", "content": "current request"},
    ]


@pytest.mark.asyncio
async def test_llm_stream_consumes_next_request_message_after_terminal_reply():
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
async def test_llm_stream_keeps_next_request_message_through_tool_round_trip():
    class ClaimingSessionContext:
        def __init__(self):
            self.state = "pending"
            self.owner = None
            self.claim_calls = 0
            self.release_calls = 0
            self.consume_calls = 0

        def claim_llm_messages_for_request(self, message_ids, logical_request_id):
            assert self.state == "pending"
            self.state = "claimed"
            self.owner = logical_request_id
            self.claim_calls += 1
            return list(message_ids)

        def release_llm_message_claims(self, message_ids, logical_request_id):
            assert self.state == "claimed"
            assert self.owner == logical_request_id
            self.state = "pending"
            self.owner = None
            self.release_calls += 1
            return len(message_ids)

        def mark_llm_messages_consumed(self, message_ids, logical_request_id):
            assert self.state == "claimed"
            assert self.owner == logical_request_id
            self.state = "consumed"
            self.consume_calls += 1
            return len(message_ids)

        def add_llm_request(self, request, response):
            pass

    context = ClaimingSessionContext()
    notice = MessageChunk(
        role=MessageRole.USER.value,
        content="<runtime_diagnostic>repair and re-output</runtime_diagnostic>",
        message_id="repair-notice",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )
    tool_client = FakeClient(
        attempts=[
            _attempt_yields(
                _tool_call_chunk("call-1", '{"tasks":[]}'),
                _content_chunk("", finish_reason="tool_calls"),
            )
        ]
    )
    terminal_client = FakeClient(
        attempts=[_attempt_yields(_content_chunk("complete", finish_reason="stop"))]
    )

    for index, client in enumerate((tool_client, terminal_client)):
        agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
        agent._get_live_session = lambda session_id: None
        agent._get_live_session_context = lambda session_id: context
        request_messages = [
            MessageChunk(role=MessageRole.USER.value, content="run"),
            notice,
        ]
        if index == 1:
            request_messages.extend(
                [
                    MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=None,
                        tool_calls=[
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "todo_write",
                                    "arguments": '{"tasks":[]}',
                                },
                            }
                        ],
                    ),
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content='{"ok":true}',
                        tool_call_id="call-1",
                    ),
                ]
            )
        async for _ in agent._call_llm_streaming(
            messages=request_messages,
            session_id="sid",
            step_name="direct_execution",
        ):
            pass

    for client in (tool_client, terminal_client):
        sent_messages = client.chat.completions.requests[0]["messages"]
        assert any(
            "repair and re-output" in str(message.get("content", ""))
            for message in sent_messages
        )
    assert context.claim_calls == 2
    assert context.release_calls == 1
    assert context.consume_calls == 1
    assert context.state == "consumed"


@pytest.mark.asyncio
async def test_network_retry_keeps_claim_and_consumes_once_after_terminal_reply(
    monkeypatch,
):
    async def fast_sleep(_seconds):
        return None

    class ClaimingSessionContext:
        def __init__(self):
            self.state = "pending"
            self.owner = None
            self.claim_calls = 0
            self.release_calls = 0
            self.consume_calls = 0

        def claim_llm_messages_for_request(self, message_ids, logical_request_id):
            self.state = "claimed"
            self.owner = logical_request_id
            self.claim_calls += 1
            return list(message_ids)

        def release_llm_message_claims(self, message_ids, logical_request_id):
            self.state = "pending"
            self.owner = None
            self.release_calls += 1
            return len(message_ids)

        def mark_llm_messages_consumed(self, message_ids, logical_request_id):
            assert self.state == "claimed"
            assert self.owner == logical_request_id
            self.state = "consumed"
            self.consume_calls += 1
            return len(message_ids)

        def add_llm_request(self, request, response):
            pass

    monkeypatch.setattr("sagents.agent.agent_base.asyncio.sleep", fast_sleep)
    context = ClaimingSessionContext()
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(httpx.ReadTimeout("no bytes yet")),
            _attempt_yields(_content_chunk("complete", finish_reason="stop")),
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    agent._get_live_session_context = lambda session_id: context
    notice = MessageChunk(
        role=MessageRole.USER.value,
        content="<runtime_diagnostic>repair</runtime_diagnostic>",
        message_id="retry-notice",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    async for _ in agent._call_llm_streaming(
        [MessageChunk(role=MessageRole.USER.value, content="run"), notice],
        session_id="sid",
        step_name="direct_execution",
    ):
        pass

    assert client.chat.completions.calls == 2
    assert (
        client.chat.completions.requests[0]["messages"]
        == (client.chat.completions.requests[1]["messages"])
    )
    assert context.claim_calls == 1
    assert context.release_calls == 0
    assert context.consume_calls == 1
    assert context.state == "consumed"


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


@pytest.mark.asyncio
async def test_concurrent_llm_requests_include_next_request_message_only_once():
    class ClaimingSessionContext:
        def __init__(self):
            self.lock = threading.Lock()
            self.state = "pending"
            self.owner = None

        def claim_llm_messages_for_request(self, message_ids, logical_request_id):
            with self.lock:
                if self.state != "pending":
                    return []
                self.state = "claimed"
                self.owner = logical_request_id
                return list(message_ids)

        def mark_llm_messages_consumed(self, message_ids, logical_request_id):
            with self.lock:
                if self.state != "claimed" or self.owner != logical_request_id:
                    return 0
                self.state = "consumed"
                return len(message_ids)

        def release_llm_message_claims(self, message_ids, logical_request_id):
            with self.lock:
                if self.state != "claimed" or self.owner != logical_request_id:
                    return 0
                self.state = "pending"
                self.owner = None
                return len(message_ids)

        def add_llm_request(self, request, response):
            pass

    context = ClaimingSessionContext()
    clients = [
        FakeClient(attempts=[_attempt_yields(_content_chunk("first"))]),
        FakeClient(attempts=[_attempt_yields(_content_chunk("second"))]),
    ]
    agents = [
        DummyAgent(model=client, model_config={"model": "gpt-test"})
        for client in clients
    ]
    for agent in agents:
        agent._get_live_session = lambda session_id: None
        agent._get_live_session_context = lambda session_id: context

    notice = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="internal retry guidance",
        message_id="shared-notice",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    async def collect(agent, request_notice):
        return [
            chunk
            async for chunk in agent._call_llm_streaming(
                messages=[
                    MessageChunk(role=MessageRole.USER.value, content="run"),
                    request_notice,
                ],
                session_id="sid",
                step_name="test",
            )
        ]

    await asyncio.gather(
        collect(agents[0], MessageChunk.from_dict(notice.to_dict())),
        collect(agents[1], MessageChunk.from_dict(notice.to_dict())),
    )

    provider_messages = [
        request["messages"]
        for client in clients
        for request in client.chat.completions.requests
    ]
    diagnostic_count = sum(
        "<runtime_diagnostic" in str(message.get("content", ""))
        for messages in provider_messages
        for message in messages
    )
    assert diagnostic_count == 1
    assert context.state == "consumed"


@pytest.mark.asyncio
async def test_llm_request_releases_claim_when_provider_never_responds():
    class ClaimingSessionContext:
        def __init__(self):
            self.state = "pending"
            self.owner = None

        def claim_llm_messages_for_request(self, message_ids, logical_request_id):
            self.state = "claimed"
            self.owner = logical_request_id
            return list(message_ids)

        def release_llm_message_claims(self, message_ids, logical_request_id):
            if self.state != "claimed" or self.owner != logical_request_id:
                return 0
            self.state = "pending"
            self.owner = None
            return len(message_ids)

        def add_llm_request(self, request, response):
            pass

    context = ClaimingSessionContext()
    client = FakeClient(
        attempts=[_attempt_raises_before_yield(ValueError("provider failed"))]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    agent._get_live_session = lambda session_id: None
    agent._get_live_session_context = lambda session_id: context
    notice = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="internal retry guidance",
        message_id="release-notice",
        message_type=MessageType.AGENT_EXECUTION_ERROR.value,
        metadata={"llm_scope": "next_request", "llm_state": "pending"},
    )

    with pytest.raises(ValueError, match="provider failed"):
        async for _ in agent._call_llm_streaming(
            messages=[MessageChunk(role=MessageRole.USER.value, content="run"), notice],
            session_id="sid",
            step_name="test",
        ):
            pass

    assert context.state == "pending"


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


def _usage_chunk(prompt_tokens: int):
    return chat_completion_chunk.ChatCompletionChunk(
        id="usage",
        object="chat.completion.chunk",
        created=0,
        model="gpt-test",
        choices=[],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=1,
            total_tokens=prompt_tokens + 1,
        ),
    )


def _reasoning_chunk(reasoning_content):
    return chat_completion_chunk.ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model="gpt-test",
        choices=[
            chat_completion_chunk.Choice(
                index=0,
                delta=chat_completion_chunk.ChoiceDelta(
                    reasoning_content=reasoning_content
                ),
                finish_reason=None,
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
async def test_provider_guard_preserves_prepared_history_and_uses_provider_authority():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("ok"))])
    agent = DummyAgent(
        model=client,
        model_config={
            "model": "gpt-test",
            "max_model_len": 200,
            # Output configuration must not affect the input threshold.
            "max_tokens": 100_000,
        },
    )
    messages = [
        MessageChunk(role=MessageRole.SYSTEM.value, content="system"),
        MessageChunk(role=MessageRole.USER.value, content="old request"),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="x" * 2000),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="old final answer"),
        MessageChunk(role=MessageRole.USER.value, content="latest request"),
        MessageChunk(
            role=MessageRole.USER.value,
            content="runtime repair notice",
            message_id="repair-notice",
            metadata={"llm_scope": "next_request", "llm_state": "pending"},
        ),
    ]

    async for _ in agent._call_llm_streaming(messages, step_name="custom"):
        pass

    sent = client.chat.completions.requests[0]["messages"]
    assert sent[0]["role"] == "system"
    assert any(message.get("content") == "latest request" for message in sent)
    assert sent[-1]["content"] == "runtime repair notice"
    assert any(message.get("content") == "x" * 2000 for message in sent)
    assert any(message.get("content") == "old final answer" for message in sent)


@pytest.mark.asyncio
async def test_successful_request_seeds_profile_checkpoint_from_prompt_usage():
    client = FakeClient(
        attempts=[_attempt_yields(_content_chunk("ok"), _usage_chunk(321))]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    budget_manager = PromptBudgetManager()
    context = SimpleNamespace(
        prompt_budget_manager=budget_manager,
        message_manager=MessageManager(),
        add_llm_request=lambda request, response: None,
    )
    context.message_manager.update_token_ratio = lambda *args, **kwargs: pytest.fail(
        "request-scoped usage must not update the legacy process-global ratio"
    )
    agent._get_live_session = lambda session_id: None
    agent._get_live_session_context = lambda session_id: context

    async for _ in agent._call_llm_streaming(
        [MessageChunk(role=MessageRole.USER.value, content="hello")],
        session_id="checkpoint-session",
        step_name="custom",
    ):
        pass

    checkpoints = budget_manager.to_dict()
    assert len(checkpoints) == 1
    assert next(iter(checkpoints.values()))["actual_prompt_tokens"] == 321


@pytest.mark.asyncio
async def test_conservative_preflight_does_not_block_provider_authority():
    client = FakeClient(attempts=[_attempt_yields(_content_chunk("accepted"))])
    agent = DummyAgent(
        model=client,
        model_config={"model": "gpt-test", "max_model_len": 100},
    )
    messages = [
        MessageChunk(role=MessageRole.USER.value, content="🧑🏽‍💻🚀" * 300)
    ]

    chunks = [chunk async for chunk in agent._call_llm_streaming(messages)]

    assert client.chat.completions.calls == 1
    assert [chunk.choices[0].delta.content for chunk in chunks] == ["accepted"]


@pytest.mark.asyncio
async def test_auxiliary_context_overflow_degrades_without_aborting_flow():
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(
                RuntimeError("maximum context length exceeded")
            )
        ]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})

    chunks = [
        chunk
        async for chunk in agent._call_aux_llm_streaming(
            [MessageChunk(role=MessageRole.USER.value, content="request")],
            step_name="optional_stage",
        )
    ]

    assert chunks == []
    assert client.chat.completions.calls == 1


@pytest.mark.asyncio
async def test_multimodal_checkpoint_uses_unredacted_provider_manifest():
    client = FakeClient(
        attempts=[_attempt_yields(_content_chunk("ok"), _usage_chunk(321))]
    )
    agent = DummyAgent(model=client, model_config={"model": "gpt-test"})
    budget_manager = PromptBudgetManager()
    context = SimpleNamespace(
        prompt_budget_manager=budget_manager,
        message_manager=MessageManager(),
        add_llm_request=lambda request, response: None,
    )
    agent._get_live_session = lambda session_id: None
    agent._get_live_session_context = lambda session_id: context

    message = MessageChunk(
        role=MessageRole.USER.value,
        content=[
            {"type": "text", "text": "inspect"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + "A" * 4096},
            },
        ],
    )
    async for _ in agent._call_llm_streaming(
        [message], session_id="multimodal-checkpoint", step_name="custom"
    ):
        pass

    sent_manifest = PromptTokenEstimator.manifest(
        client.chat.completions.requests[-1]["messages"]
    )
    checkpoint = next(iter(budget_manager.to_dict().values()))
    assert checkpoint["components"] == [
        component.to_dict() for component in sent_manifest.components
    ]


@pytest.mark.asyncio
async def test_provider_context_error_is_delegated_to_session_recovery():
    old_response = "old assistant response " * 400
    context_error = APIError(
        "maximum context length exceeded",
        request=httpx.Request("POST", "https://provider.example/chat"),
        body=None,
    )
    client = FakeClient(
        attempts=[_attempt_raises_before_yield(context_error)]
    )
    agent = DummyAgent(
        model=client,
        model_config={"model": "gpt-test", "max_model_len": 4000},
    )
    messages = [
        MessageChunk(role=MessageRole.SYSTEM.value, content="system"),
        MessageChunk(role=MessageRole.USER.value, content="old request"),
        MessageChunk(role=MessageRole.ASSISTANT.value, content=old_response),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="old final answer"),
        MessageChunk(role=MessageRole.USER.value, content="latest request"),
    ]

    with pytest.raises(ProviderContextWindowExceededError):
        async for _ in agent._call_llm_streaming(
            messages, enable_thinking=False
        ):
            pass

    assert client.chat.completions.calls == 1
    first_request = client.chat.completions.requests[0]
    assert any(
        message.get("content") == old_response for message in first_request["messages"]
    )
    assert any(
        message.get("content") == "old final answer"
        for message in first_request["messages"]
    )
    assert first_request["messages"][-1]["content"] == "latest request"


@pytest.mark.asyncio
async def test_runtime_context_error_is_normalized_for_session_recovery():
    context_error = RuntimeError("maximum context length exceeded")
    client = FakeClient(
        attempts=[_attempt_raises_before_yield(context_error)]
    )
    agent = DummyAgent(
        model=client,
        model_config={"model": "gpt-test", "max_model_len": 4000},
    )
    intermediate = "intermediate assistant work " * 400
    messages = [
        MessageChunk(role=MessageRole.SYSTEM.value, content="system"),
        MessageChunk(role=MessageRole.USER.value, content="old request"),
        MessageChunk(role=MessageRole.ASSISTANT.value, content=intermediate),
        MessageChunk(role=MessageRole.ASSISTANT.value, content="old final answer"),
        MessageChunk(role=MessageRole.USER.value, content="latest request"),
    ]

    with pytest.raises(ProviderContextWindowExceededError):
        async for _ in agent._call_llm_streaming(
            messages, enable_thinking=False
        ):
            pass

    assert client.chat.completions.calls == 1
    assert any(
        message.get("content") == intermediate
        for message in client.chat.completions.requests[0]["messages"]
    )


@pytest.mark.asyncio
async def test_simple_agent_uses_llm_compression_when_rule_trim_cannot_shrink():
    old_response = "old assistant response " * 400
    context_error = APIError(
        "maximum context length exceeded",
        request=httpx.Request("POST", "https://provider.example/chat"),
        body=None,
    )
    client = FakeClient(
        attempts=[
            _attempt_raises_before_yield(context_error),
            _attempt_yields(_content_chunk("continued after compression")),
        ]
    )
    agent = SimpleAgent(
        model=client,
        model_config={"model": "gpt-test", "max_model_len": 4000},
    )
    agent._get_live_session = lambda session_id: None
    agent._get_live_session_context = lambda session_id: None
    recovery_flags = []

    async def fake_prepare_context(
        messages_input,
        session_id,
        *,
        provider_overflow_recovery=False,
        **kwargs,
    ):
        recovery_flags.append(provider_overflow_recovery)
        if provider_overflow_recovery:
            yield (
                [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content="compressed by model",
                        tool_call_id="compress-1",
                    )
                ],
                False,
            )
            yield (
                [
                    MessageChunk(
                        role=MessageRole.USER.value, content="compressed request"
                    )
                ],
                True,
            )
        else:
            yield (list(messages_input), True)

    async def passthrough_request_messages(*, history_messages=None, **kwargs):
        return list(history_messages or [])

    agent._prepare_context_messages_for_llm = fake_prepare_context
    agent.prepare_llm_request_messages = passthrough_request_messages

    emitted = []
    async for messages, _ in agent._call_llm_and_process_response(
        messages_input=[
                MessageChunk(role=MessageRole.USER.value, content="old request"),
                MessageChunk(role=MessageRole.ASSISTANT.value, content=old_response),
                MessageChunk(
                    role=MessageRole.ASSISTANT.value, content="old final answer"
                ),
                MessageChunk(role=MessageRole.USER.value, content="request"),
        ],
        tools_json=[],
        tool_manager=None,
        session_id="context-recovery",
    ):
        emitted.extend(messages)

    assert client.chat.completions.calls == 2
    assert recovery_flags == [False, True]
    assert any(message.content == "compressed by model" for message in emitted)
    assert any(message.content == "continued after compression" for message in emitted)
    assert any(
        message.get("content") == old_response
        for message in client.chat.completions.requests[0]["messages"]
    )
    assert not any(
        message.get("content") == old_response
        for message in client.chat.completions.requests[-1]["messages"]
    )
    assert client.chat.completions.requests[-1]["messages"] == [
        {"role": "user", "content": "compressed request"}
    ]


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
    provider_attempts = recorded["request"]["_provider_request_attempts"]
    assert len(provider_attempts) == 2
    assert provider_attempts[-1]["model"] == "gpt-test"
    assert provider_attempts[-1]["messages"] == [{"role": "user", "content": "run"}]
    assert provider_attempts[-1]["stream"] is True
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
async def test_simple_agent_persists_reasoning_and_tool_calls_as_one_message(
    monkeypatch,
):
    monkeypatch.setenv("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "true")
    client = FakeClient(
        attempts=[
            _attempt_yields(
                _reasoning_chunk("need a tool"),
                _tool_call_chunk("call-1", '{"tasks":[]}'),
            )
        ]
    )
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

    response_chunks = [
        chunk
        for chunk in chunks
        if chunk.role == MessageRole.ASSISTANT.value
        and (chunk.reasoning_content or chunk.tool_calls)
    ]
    assert len({chunk.message_id for chunk in response_chunks}) == 1

    manager = MessageManager()
    manager.add_messages(chunks)
    persisted = [
        message
        for message in manager.messages
        if message.message_id == response_chunks[0].message_id
    ]
    assert len(persisted) == 1
    assert persisted[0].reasoning_content == "need a tool"
    assert persisted[0].tool_calls[0]["id"] == "call-1"
    assert persisted[0].message_type == MessageType.TOOL_CALL.value


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
