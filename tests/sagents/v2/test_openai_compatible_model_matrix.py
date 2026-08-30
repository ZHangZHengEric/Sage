from __future__ import annotations

from types import SimpleNamespace

import pytest

from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelToolCall,
    ModelToolDefinition,
    OpenAICompatibleConfig,
    OpenAICompatibleModelProvider,
)
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.items import JsonBlock, TextBlock


CAPABILITIES = ModelCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_parallel_tool_calls=True,
    supports_reasoning=True,
    supports_multimodal_input=False,
    supports_structured_output=True,
    max_input_tokens=128_000,
    max_output_tokens=8_192,
)


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self.chunks:
            yield chunk

    async def close(self):
        self.closed = True


class FakeCompletions:
    def __init__(self, *, stream=None, error=None):
        self.stream = stream
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def config(**changes):
    values = {
        "base_url": "https://gateway.invalid/openai/v1",
        "model": "gpt-test",
        "capabilities": CAPABILITIES,
        "default_max_output_tokens": 512,
        "reasoning_effort": "high",
    }
    values.update(changes)
    return OpenAICompatibleConfig(**values)


def request(**changes):
    values = {
        "request_id": "request_1",
        "run_id": "run_1",
        "model_binding": "primary",
        "messages": (
            ModelMessage(role="system", content=(TextBlock(text="be exact"),)),
            ModelMessage(role="user", content=(JsonBlock(value={"q": "hi"}),)),
            ModelMessage(
                role="assistant",
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="call_old",
                        name="lookup",
                        arguments={"q": "old"},
                    ),
                ),
            ),
            ModelMessage(
                role="tool",
                tool_call_id="call_old",
                content=(TextBlock(text="old result"),),
            ),
        ),
        "tools": (
            ModelToolDefinition(
                name="lookup",
                description="look up a value",
                input_schema={"type": "object"},
            ),
        ),
    }
    values.update(changes)
    return ModelRequest(**values)


def chunk(*, content=None, reasoning=None, tool_calls=(), finish=None, usage=None):
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        id="response_1",
        choices=(SimpleNamespace(delta=delta, finish_reason=finish),),
        usage=usage,
    )


def tool_delta(index, *, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.mark.asyncio
async def test_stream_normalizes_reasoning_text_tool_fragments_usage_and_closes():
    usage = SimpleNamespace(
        prompt_tokens=11,
        completion_tokens=7,
        prompt_tokens_details=SimpleNamespace(cached_tokens=3),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
    )
    stream = FakeStream(
        (
            chunk(reasoning="think ", content="answer "),
            chunk(
                tool_calls=(
                    tool_delta(0, call_id="call_", name="look", arguments='{"q":'),
                    tool_delta(1, call_id="call_2", name="second", arguments="{}"),
                )
            ),
            chunk(
                content="now",
                tool_calls=(tool_delta(0, call_id="1", name="up", arguments='"x"}'),),
                finish="tool_calls",
                usage=usage,
            ),
        )
    )
    completions = FakeCompletions(stream=stream)
    provider = OpenAICompatibleModelProvider(config(), client=FakeClient(completions))

    events = [
        event
        async for event in provider.stream(
            request(tool_choice="required", response_format="json_object")
        )
    ]

    assert [event.kind for event in events] == [
        ModelEventKind.REASONING_DELTA,
        ModelEventKind.TEXT_DELTA,
        ModelEventKind.TEXT_DELTA,
        ModelEventKind.COMPLETED,
    ]
    response = events[-1].response
    assert response is not None
    assert response.text == "answer now"
    assert response.reasoning == "think"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == (
        ModelToolCall(tool_call_id="call_1", name="lookup", arguments={"q": "x"}),
        ModelToolCall(tool_call_id="call_2", name="second", arguments={}),
    )
    assert response.usage.input_tokens == 11
    assert response.usage.cached_input_tokens == 3
    assert response.usage.reasoning_tokens == 2
    assert stream.closed is True

    outgoing = completions.calls[0]
    assert outgoing["stream_options"] == {"include_usage": True}
    assert outgoing["tool_choice"] == "required"
    assert outgoing["response_format"] == {"type": "json_object"}
    assert outgoing["max_tokens"] == 512
    assert outgoing["extra_body"] == {"reasoning_effort": "high"}
    assert (
        outgoing["messages"][2]["tool_calls"][0]["function"]["arguments"]
        == '{"q":"old"}'
    )
    assert outgoing["messages"][3]["tool_call_id"] == "call_old"


@pytest.mark.asyncio
async def test_stream_accepts_common_nonstandard_text_and_reasoning_fields():
    stream = FakeStream(
        (
            {
                "id": "response_alt",
                "choices": (
                    {"delta": {"thinking": "think "}, "finish_reason": None},
                ),
            },
            {
                "id": "response_alt",
                "choices": (
                    {"delta": {"text": "answer"}, "finish_reason": "stop"},
                ),
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    assert [event.kind for event in events] == [
        ModelEventKind.REASONING_DELTA,
        ModelEventKind.TEXT_DELTA,
        ModelEventKind.COMPLETED,
    ]
    response = events[-1].response
    assert response is not None
    assert response.reasoning == "think"
    assert response.text == "answer"


@pytest.mark.asyncio
async def test_stream_accepts_structured_content_parts_from_compatible_gateway():
    stream = FakeStream(
        (
            {
                "id": "response_parts",
                "choices": (
                    {
                        "delta": {
                            "reasoning_content": [
                                {"type": "reasoning_text", "text": "think "}
                            ],
                            "content": [
                                {"type": "text", "text": "answer"}
                            ],
                        },
                        "finish_reason": "stop",
                    },
                ),
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    response = events[-1].response
    assert response is not None
    assert response.reasoning == "think"
    assert response.text == "answer"


@pytest.mark.asyncio
async def test_stream_recovers_final_message_content_from_nonstandard_chunk():
    stream = FakeStream(
        (
            {
                "id": "response_message",
                "choices": (
                    {
                        "message": {"content": '{"decision":"completed"}'},
                        "finish_reason": "stop",
                    },
                ),
                "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            },
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    response = events[-1].response
    assert response is not None
    assert response.text == '{"decision":"completed"}'


@pytest.mark.asyncio
async def test_output_tokens_without_semantic_fields_are_a_provider_error():
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=43,
        prompt_tokens_details=None,
        completion_tokens_details=None,
    )
    stream = FakeStream((chunk(finish="stop", usage=usage),))
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.empty_semantic_response"
    assert caught.value.info.category == ErrorCategory.PROVIDER_TRANSIENT
    assert caught.value.info.retryable is True
    assert caught.value.info.metadata == {
        "output_tokens": 43,
        "finish_reason": "stop",
        "observed_choice_fields": ["delta", "finish_reason"],
        "observed_delta_fields": [
            "content",
            "reasoning_content",
            "tool_calls",
        ],
        "observed_delta_field_types": {
            "content": ["null"],
            "reasoning_content": ["null"],
            "tool_calls": ["array"],
        },
    }
    assert stream.closed is True


@pytest.mark.asyncio
async def test_binding_controls_completion_token_field_and_structured_output():
    stream = FakeStream((chunk(content="{}", finish="stop"),))
    completions = FakeCompletions(stream=stream)
    provider = OpenAICompatibleModelProvider(
        config(max_output_tokens_field="max_completion_tokens"),
        client=FakeClient(completions),
    )
    schema = {"type": "object", "additionalProperties": False}
    _ = [
        event
        async for event in provider.stream(
            request(max_output_tokens=33, response_schema=schema)
        )
    ]
    outgoing = completions.calls[0]
    assert "max_tokens" not in outgoing
    assert outgoing["max_completion_tokens"] == 33
    assert outgoing["response_format"]["json_schema"]["schema"] == schema


@pytest.mark.asyncio
async def test_legacy_tool_strict_and_returns_fields_are_forwarded_exactly():
    stream = FakeStream((chunk(content="done", finish="stop"),))
    completions = FakeCompletions(stream=stream)
    provider = OpenAICompatibleModelProvider(config(), client=FakeClient(completions))
    output_schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }
    legacy_tool = ModelToolDefinition(
        name="legacy_tool",
        description="legacy description",
        input_schema={"type": "object", "additionalProperties": False},
        strict=False,
        output_schema=output_schema,
    )

    _ = [event async for event in provider.stream(request(tools=(legacy_tool,)))]

    function = completions.calls[0]["tools"][0]["function"]
    assert function == {
        "name": "legacy_tool",
        "description": "legacy description",
        "parameters": {"type": "object", "additionalProperties": False},
        "strict": False,
        "returns": output_schema,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ("{", "model.tool_arguments_invalid_json"),
        ("[]", "model.tool_arguments_not_object"),
    ],
)
async def test_invalid_tool_arguments_are_typed_and_stream_is_closed(arguments, code):
    stream = FakeStream(
        (
            chunk(
                tool_calls=(
                    tool_delta(0, call_id="call_1", name="lookup", arguments=arguments),
                ),
                finish="tool_calls",
            ),
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )
    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]
    assert caught.value.info.code == code
    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [
        (429, ErrorCategory.PROVIDER_TRANSIENT, True),
        (503, ErrorCategory.PROVIDER_TRANSIENT, True),
        (400, ErrorCategory.PROVIDER_PERMANENT, False),
        (None, ErrorCategory.PROVIDER_PERMANENT, False),
    ],
)
async def test_provider_error_matrix(status, category, retryable):
    error = RuntimeError("credential must never be echoed")
    error.status_code = status
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(error=error))
    )
    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]
    assert caught.value.info.category == category
    assert caught.value.info.retryable is retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["tools", "structured_output", "output_budget"])
async def test_declared_capabilities_are_enforced_before_network_call(unsupported):
    capabilities = CAPABILITIES.model_copy(
        update={
            "supports_tools": unsupported != "tools",
            "supports_structured_output": unsupported != "structured_output",
            "max_output_tokens": 16 if unsupported == "output_budget" else 8_192,
        }
    )
    completions = FakeCompletions(stream=FakeStream((chunk(content="x"),)))
    provider = OpenAICompatibleModelProvider(
        config(capabilities=capabilities), client=FakeClient(completions)
    )
    changed = {}
    if unsupported == "structured_output":
        changed["tools"] = ()
        changed["response_schema"] = {"type": "object"}
    elif unsupported == "output_budget":
        changed["tools"] = ()
        changed["max_output_tokens"] = 17
    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request(**changed))]
    assert caught.value.info.code in {
        "model.capability_unsupported",
        "model.output_budget_exceeded",
    }
    assert completions.calls == []


def test_config_has_no_credential_field_and_mutable_defaults_are_isolated():
    first = config()
    second = config()
    first.extra_body["x"] = 1
    assert second.extra_body == {}
    assert "api_key" not in OpenAICompatibleConfig.model_fields
