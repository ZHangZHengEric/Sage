from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

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
from sagents.v2.contracts.provider_state import make_provider_state
from sagents.v2.runtime.credentials import CredentialMaterial


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


class SequencedCompletions:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


@pytest.mark.asyncio
async def test_openai_compatible_closes_only_the_client_it_constructed(monkeypatch):
    class ClosableClient(FakeClient):
        def __init__(self):
            super().__init__(FakeCompletions())
            self.close_calls = 0

        async def close(self):
            self.close_calls += 1

    owned = ClosableClient()
    monkeypatch.setattr(
        "sagents.v2.model.plugins.openai_compatible.AsyncOpenAI",
        lambda **kwargs: owned,
    )
    credential = CredentialMaterial(
        credential_id="model", secret=SecretStr("secret"), source="test"
    )
    provider = OpenAICompatibleModelProvider(config(), credential)
    await provider.close()

    injected = ClosableClient()
    injected_provider = OpenAICompatibleModelProvider(config(), client=injected)
    await injected_provider.close()

    assert owned.close_calls == 1
    assert injected.close_calls == 0


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


def chunk(
    *,
    content=None,
    reasoning=None,
    reasoning_details=None,
    tool_calls=(),
    finish=None,
    usage=None,
):
    delta_values = {
        "content": content,
        "reasoning_content": reasoning,
        "tool_calls": tool_calls,
    }
    if reasoning_details is not None:
        delta_values["reasoning_details"] = reasoning_details
    delta = SimpleNamespace(**delta_values)
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
    assert response.usage.reported is True
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
async def test_stream_normalizes_cumulative_tool_call_snapshots():
    stream = FakeStream(
        (
            chunk(
                tool_calls=(
                    tool_delta(0, call_id="call_", name="look", arguments='{"q":'),
                )
            ),
            chunk(
                tool_calls=(
                    tool_delta(
                        0,
                        call_id="call_1",
                        name="lookup",
                        arguments='{"q":"x"}',
                    ),
                ),
                finish="tool_calls",
            ),
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    response = events[-1].response
    assert response is not None
    assert response.tool_calls == (
        ModelToolCall(tool_call_id="call_1", name="lookup", arguments={"q": "x"}),
    )


def test_extra_body_cannot_override_host_owned_request_fields():
    provider = OpenAICompatibleModelProvider(
        config(extra_body={"model": "shadow-model"}),
        client=FakeClient(FakeCompletions()),
    )

    with pytest.raises(SageV2Error) as conflict:
        provider.diagnostic_request(request())

    assert conflict.value.info.code == "model.extra_body_conflict"
    assert conflict.value.info.metadata["fields"] == ["model"]


@pytest.mark.asyncio
async def test_stream_normalizes_responses_style_usage_from_chat_gateway():
    raw_usage = {
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": 2,
        "cache_write_tokens": 1,
    }
    stream = FakeStream(
        (
            chunk(content="answer", finish="stop"),
            {"id": "response_1", "choices": [], "usage": raw_usage},
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    response = events[-1].response
    assert response is not None
    assert response.usage.reported is True
    assert response.usage.input_tokens == 13
    assert response.usage.output_tokens == 5
    assert response.usage.cached_input_tokens == 2
    assert response.usage.provider_usage == raw_usage


@pytest.mark.asyncio
async def test_stream_marks_usage_unreported_when_gateway_omits_it():
    stream = FakeStream((chunk(content="answer", finish="stop"),))
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]

    response = events[-1].response
    assert response is not None
    assert response.usage.reported is False
    assert response.usage.provider_usage == {}
    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0


@pytest.mark.asyncio
async def test_reasoning_details_use_latest_snapshot_and_replay_after_tool_call():
    stream = FakeStream(
        (
            chunk(
                reasoning="think",
                reasoning_details=[{"type": "reasoning", "value": "first"}],
            ),
            chunk(
                reasoning="thinking",
                reasoning_details=[{"type": "reasoning", "value": "complete"}],
                tool_calls=(
                    tool_delta(0, call_id="call_1", name="lookup", arguments="{}"),
                ),
                finish="tool_calls",
            ),
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    events = [event async for event in provider.stream(request())]
    response = events[-1].response

    assert response is not None
    assert response.reasoning == "thinking"
    assert [
        event.delta for event in events if event.kind == ModelEventKind.REASONING_DELTA
    ] == ["think", "ing"]
    assert response.provider_state == make_provider_state(
        "openai_compatible",
        {
            "reasoning_content": "thinking",
            "reasoning_details": [{"type": "reasoning", "value": "complete"}],
        },
    )
    replay = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(role="user", content=(TextBlock(text="go"),)),
                ModelMessage(
                    role="assistant",
                    tool_calls=response.tool_calls,
                    provider_state=response.provider_state,
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id="call_1",
                    content=(TextBlock(text="result"),),
                ),
            )
        )
    )
    assert replay["messages"][1]["reasoning_content"] == "thinking"
    assert replay["messages"][1]["reasoning_details"] == [
        {"type": "reasoning", "value": "complete"}
    ]


@pytest.mark.asyncio
async def test_stream_accepts_common_nonstandard_text_and_reasoning_fields():
    stream = FakeStream(
        (
            {
                "id": "response_alt",
                "choices": ({"delta": {"thinking": "think "}, "finish_reason": None},),
            },
            {
                "id": "response_alt",
                "choices": ({"delta": {"text": "answer"}, "finish_reason": "stop"},),
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
                            "content": [{"type": "text", "text": "answer"}],
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
@pytest.mark.parametrize(
    ("model", "initial", "alternate"),
    [
        ("third-party-model", "max_tokens", "max_completion_tokens"),
        ("gpt-5-compatible", "max_completion_tokens", "max_tokens"),
    ],
)
async def test_auto_token_field_negotiates_once_and_learns_route(
    model, initial, alternate
):
    error = RuntimeError("Provider rejected the request")
    error.status_code = 422
    completions = SequencedCompletions(
        [
            error,
            FakeStream((chunk(content="first", finish="stop"),)),
            FakeStream((chunk(content="second", finish="stop"),)),
        ]
    )
    provider = OpenAICompatibleModelProvider(
        config(
            model=model,
            reasoning_effort=None,
            max_output_tokens_field="auto",
        ),
        client=FakeClient(completions),
    )

    first_events = [event async for event in provider.stream(request())]
    second_events = [event async for event in provider.stream(request())]

    assert completions.calls[0][initial] == 512
    assert alternate not in completions.calls[0]
    assert completions.calls[1][alternate] == 512
    assert initial not in completions.calls[1]
    assert completions.calls[2][alternate] == 512
    assert initial not in completions.calls[2]
    first_response = first_events[-1].response
    second_response = second_events[-1].response
    assert first_response is not None
    assert second_response is not None
    assert first_response.provider_metadata["compatibility_fallback"] == {
        "kind": "output_token_field_switched",
        "from": initial,
        "to": alternate,
        "provider_status": 422,
    }
    assert "compatibility_fallback" not in second_response.provider_metadata
    assert provider.diagnostic_request(request())[alternate] == 512


@pytest.mark.asyncio
async def test_explicit_token_field_does_not_negotiate():
    error = RuntimeError("Provider rejected the request")
    error.status_code = 422
    completions = FakeCompletions(error=error)
    provider = OpenAICompatibleModelProvider(
        config(
            reasoning_effort=None,
            max_output_tokens_field="max_tokens",
        ),
        client=FakeClient(completions),
    )

    with pytest.raises(SageV2Error):
        _ = [event async for event in provider.stream(request())]

    assert len(completions.calls) == 1
    assert completions.calls[0]["max_tokens"] == 512


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
    completions = FakeCompletions(error=error)
    provider = OpenAICompatibleModelProvider(config(), client=FakeClient(completions))
    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]
    assert caught.value.info.category == category
    assert caught.value.info.retryable is retryable
    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_chat_compatible_rejects_stream_without_finish_reason():
    stream = FakeStream((chunk(content="partial"),))
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.stream_incomplete"
    assert caught.value.info.retryable is False
    assert stream.closed is True


@pytest.mark.asyncio
async def test_reasoning_control_422_retries_once_without_controls_and_learns_route():
    error = RuntimeError("reasoning_effort is unsupported by this deployment")
    error.status_code = 422
    completions = SequencedCompletions(
        [error, FakeStream((chunk(content="done", finish="stop"),))]
    )
    provider = OpenAICompatibleModelProvider(
        config(
            reasoning_effort="minimal",
            reasoning_parameter_fallback=True,
        ),
        client=FakeClient(completions),
    )

    events = [event async for event in provider.stream(request())]

    assert len(completions.calls) == 2
    assert completions.calls[0]["extra_body"] == {"reasoning_effort": "minimal"}
    assert "extra_body" not in completions.calls[1]
    response = events[-1].response
    assert response is not None
    assert response.provider_metadata["compatibility_fallback"] == {
        "kind": "reasoning_controls_omitted",
        "removed": ["reasoning_effort"],
        "provider_status": 422,
    }
    assert "extra_body" not in provider.diagnostic_request(request())


@pytest.mark.asyncio
async def test_422_without_reasoning_controls_is_not_retried():
    error = RuntimeError("response_format is unsupported")
    error.status_code = 422
    completions = FakeCompletions(error=error)
    provider = OpenAICompatibleModelProvider(
        config(reasoning_effort=None), client=FakeClient(completions)
    )

    with pytest.raises(SageV2Error):
        _ = [event async for event in provider.stream(request())]

    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_provider_context_overflow_has_a_distinct_retryable_code():
    error = RuntimeError(
        "context_length_exceeded: maximum context length is 128000 tokens"
    )
    error.status_code = 400
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(error=error))
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.context_window_exceeded"
    assert caught.value.info.category == ErrorCategory.VALIDATION
    assert caught.value.info.retryable is True
    assert caught.value.info.metadata["response_started"] is False


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
