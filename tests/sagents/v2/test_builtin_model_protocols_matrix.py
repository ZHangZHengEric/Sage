from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration,
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    BuiltinModelProtocol,
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelToolCall,
    ModelToolDefinition,
    OpenAIChatCompletionsModelProvider,
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
    resolve_model_protocol,
)
from sagents.v2.contracts.items import ImageBlock, JsonBlock, TextBlock
from sagents.v2.contracts.provider_state import make_provider_state
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.official import builtin_extension_registry


CAPABILITIES = ModelCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_parallel_tool_calls=True,
    supports_reasoning=True,
    supports_multimodal_input=True,
    supports_structured_output=True,
    max_input_tokens=128_000,
    max_output_tokens=8_192,
)


def request(**changes):
    values = {
        "request_id": "request_1",
        "run_id": "run_1",
        "model_binding": "primary",
        "messages": (
            ModelMessage(role="system", content=(TextBlock(text="be exact"),)),
            ModelMessage(
                role="user",
                content=(
                    TextBlock(text="look"),
                    ImageBlock(
                        uri="https://example.invalid/cat.png",
                        mime_type="image/png",
                    ),
                ),
            ),
            ModelMessage(
                role="assistant",
                content=(TextBlock(text="checking"),),
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
                content=(JsonBlock(value={"result": 1}),),
            ),
        ),
        "tools": (
            ModelToolDefinition(
                name="lookup",
                description="look up a value",
                input_schema={"type": "object"},
                strict=True,
            ),
        ),
    }
    values.update(changes)
    return ModelRequest(**values)


class FakeAsyncStream:
    def __init__(self, values):
        self.values = values
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for value in self.values:
            yield value

    async def close(self):
        self.closed = True


class FakeResponses:
    def __init__(self, stream):
        self.stream = stream
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream


class SequencedResponses:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_openai_responses_maps_items_tools_and_stream_events():
    usage = {
        "input_tokens": 12,
        "output_tokens": 5,
        "input_tokens_details": {"cached_tokens": 3},
        "output_tokens_details": {"reasoning_tokens": 2},
    }
    stream = FakeAsyncStream(
        (
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "reasoning",
                    "id": "reasoning_1",
                    "encrypted_content": "opaque-state",
                    "summary": [],
                },
            },
            {"type": "response.reasoning_summary_text.delta", "delta": "think"},
            {"type": "response.output_text.delta", "delta": "answer"},
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "item_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item_1",
                "delta": '{"q":"new"}',
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "item_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"q":"new"}',
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "response_1",
                    "status": "completed",
                    "usage": usage,
                },
            },
        )
    )
    responses = FakeResponses(stream)
    client = SimpleNamespace(responses=responses)
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(
            model="gpt-test",
            capabilities=CAPABILITIES,
            default_max_output_tokens=256,
            reasoning_effort="high",
        ),
        client=client,
    )

    events = [
        event
        async for event in provider.stream(
            request(tool_choice="required", response_format="json_object")
        )
    ]

    assert [event.kind for event in events] == [
        ModelEventKind.REASONING_DELTA,
        ModelEventKind.TEXT_DELTA,
        ModelEventKind.COMPLETED,
    ]
    completed = events[-1].response
    assert completed is not None
    assert completed.text == "answer"
    assert completed.reasoning == "think"
    assert completed.tool_calls == (
        ModelToolCall(tool_call_id="call_1", name="lookup", arguments={"q": "new"}),
    )
    assert completed.usage.cached_input_tokens == 3
    assert completed.usage.reasoning_tokens == 2
    assert completed.usage.reported is True
    assert completed.usage.provider_usage == usage
    assert completed.provider_state == make_provider_state(
        "openai_responses",
        {
            "reasoning_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning_1",
                    "encrypted_content": "opaque-state",
                    "summary": [],
                }
            ]
        },
    )
    assert stream.closed is True

    outgoing = responses.calls[0]
    assert outgoing["store"] is False
    assert outgoing["tool_choice"] == "required"
    assert outgoing["text"] == {"format": {"type": "json_object"}}
    assert outgoing["reasoning"] == {"effort": "high"}
    assert outgoing["include"] == ["reasoning.encrypted_content"]
    assert outgoing["tools"][0] == {
        "type": "function",
        "name": "lookup",
        "description": "look up a value",
        "parameters": {"type": "object"},
        "strict": True,
    }
    assert outgoing["input"][3] == {
        "type": "function_call",
        "call_id": "call_old",
        "name": "lookup",
        "arguments": '{"q":"old"}',
    }
    assert outgoing["input"][4] == {
        "type": "function_call_output",
        "call_id": "call_old",
        "output": '{"result":1}',
    }
    replay = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(role="user", content=(TextBlock(text="go"),)),
                ModelMessage(
                    role="assistant",
                    tool_calls=completed.tool_calls,
                    provider_state=completed.provider_state,
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id="call_1",
                    content=(TextBlock(text="result"),),
                ),
            )
        )
    )
    assert replay["input"][1] == {
        "type": "reasoning",
        "id": "reasoning_1",
        "encrypted_content": "opaque-state",
        "summary": [],
    }


@pytest.mark.asyncio
async def test_openai_responses_retries_rejected_reasoning_control_once():
    error = RuntimeError("reasoning is unsupported by this deployment")
    error.status_code = 422
    responses = SequencedResponses(
        [
            error,
            FakeAsyncStream(
                (
                    {
                        "type": "response.output_text.delta",
                        "delta": "done",
                    },
                    {
                        "type": "response.completed",
                        "response": {"id": "response_1", "status": "completed"},
                    },
                )
            ),
        ]
    )
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(
            model="gpt-test",
            capabilities=CAPABILITIES,
            reasoning_effort="minimal",
            reasoning_parameter_fallback=True,
        ),
        client=SimpleNamespace(responses=responses),
    )

    events = [event async for event in provider.stream(request())]

    assert len(responses.calls) == 2
    assert responses.calls[0]["reasoning"] == {"effort": "minimal"}
    assert "reasoning" not in responses.calls[1]
    assert "include" not in responses.calls[1]
    completed = events[-1].response
    assert completed is not None
    assert completed.provider_metadata["compatibility_fallback"] == {
        "kind": "reasoning_controls_omitted",
        "removed": ["reasoning"],
        "provider_status": 422,
    }
    assert "reasoning" not in provider.diagnostic_request(request())


class FakeHTTPResponse:
    def __init__(self, events):
        self.events = events
        self.status_checked = False

    def raise_for_status(self):
        self.status_checked = True

    async def aiter_lines(self):
        for event in self.events:
            yield f"event: {event['type']}"
            yield "data: " + json.dumps(event)
            yield ""


class FakeHTTPStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class FakeHTTPClient:
    def __init__(self, events):
        self.response = FakeHTTPResponse(events)
        self.calls = []

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeHTTPStream(self.response)


@pytest.mark.asyncio
async def test_anthropic_messages_preserves_system_tool_blocks_and_sse_usage():
    client = FakeHTTPClient(
        (
            {
                "type": "message_start",
                "message": {
                    "id": "message_1",
                    "usage": {
                        "input_tokens": 20,
                        "cache_read_input_tokens": 4,
                    },
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "think"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "signed"},
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "answer"},
            },
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '"new"}'},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 7},
            },
            {"type": "message_stop"},
        )
    )
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="claude-test", capabilities=CAPABILITIES),
        client=client,
    )

    events = [
        event
        async for event in provider.stream(
            request(tool_choice="required", response_format="json_object")
        )
    ]

    completed = events[-1].response
    assert completed is not None
    assert completed.response_id == "message_1"
    assert completed.text == "answer"
    assert completed.reasoning == "think"
    assert completed.provider_state == make_provider_state(
        "anthropic_messages",
        {
            "thinking_blocks": [
                {"type": "thinking", "thinking": "think", "signature": "signed"}
            ]
        },
    )
    assert completed.finish_reason == "tool_use"
    assert completed.tool_calls[0].arguments == {"q": "new"}
    assert completed.usage.input_tokens == 20
    assert completed.usage.output_tokens == 7
    assert completed.usage.cached_input_tokens == 4
    assert completed.usage.reported is True
    assert completed.usage.provider_usage == {
        "input_tokens": 20,
        "cache_read_input_tokens": 4,
        "output_tokens": 7,
    }
    assert client.response.status_checked is True

    method, url, call = client.calls[0]
    assert (method, url) == ("POST", "/v1/messages")
    outgoing = call["json"]
    assert outgoing["system"] == [{"type": "text", "text": "be exact"}]
    assert outgoing["tool_choice"] == {"type": "any"}
    assert "output_config" not in outgoing
    assert outgoing["messages"][1]["content"][-1] == {
        "type": "tool_use",
        "id": "call_old",
        "name": "lookup",
        "input": {"q": "old"},
    }
    assert outgoing["messages"][2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call_old",
            "content": '{"result":1}',
        }
    ]
    assert outgoing["tools"][0]["input_schema"] == {"type": "object"}
    replay = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(role="user", content=(TextBlock(text="go"),)),
                ModelMessage(
                    role="assistant",
                    tool_calls=completed.tool_calls,
                    provider_state=completed.provider_state,
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id="call_1",
                    content=(TextBlock(text="result"),),
                ),
            )
        )
    )
    assert replay["messages"][1]["content"][0] == {
        "type": "thinking",
        "thinking": "think",
        "signature": "signed",
    }


def test_anthropic_thinking_uses_native_adaptive_effort_parameters():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(
            model="claude-sonnet-5",
            capabilities=CAPABILITIES,
            reasoning_effort="xhigh",
            default_temperature=0.4,
            default_top_p=0.9,
        ),
        client=object(),
    )

    outgoing = provider.diagnostic_request(request())

    assert outgoing["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
    }
    assert outgoing["output_config"] == {"effort": "xhigh"}
    assert "temperature" not in outgoing
    assert "top_p" not in outgoing


@pytest.mark.parametrize(
    ("provider_id", "provider_type", "protocol"),
    [
        (
            "openai-chat-completions",
            OpenAIChatCompletionsModelProvider,
            BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS,
        ),
        (
            "openai-compatible",
            OpenAIChatCompletionsModelProvider,
            BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS,
        ),
        (
            "openai-responses",
            OpenAIResponsesModelProvider,
            BuiltinModelProtocol.OPENAI_RESPONSES,
        ),
        (
            "claude",
            AnthropicMessagesModelProvider,
            BuiltinModelProtocol.ANTHROPIC_MESSAGES,
        ),
    ],
)
def test_builtin_factory_uses_model_route_as_authoritative_protocol_selection(
    provider_id, provider_type, protocol
):
    route = ModelRoute(
        provider=provider_id,
        model="model-test",
        request=ModelRequestDefaults(max_output_tokens=512),
        limits=ModelLimits(context_window=100_000, max_output_tokens=4_096),
        capabilities=ModelCapabilityDeclaration(
            multimodal=True,
            structured_output=True,
            tool_calling=True,
            reasoning=True,
            parallel_tool_calls=True,
        ),
    )
    resolved_protocol = resolve_model_protocol(provider_id)
    registration = builtin_extension_registry().get(
        f"sage.model.{resolved_protocol.value}"
    )
    provider = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="agent_test",
            config={"route": route.model_dump(mode="json"), "client": object()},
        ),
        {},
    )

    assert isinstance(provider, provider_type)
    assert resolved_protocol == protocol
    assert provider.config.model == "model-test"
    assert provider.config.capabilities.max_input_tokens == 100_000


def test_registry_selection_rejects_unknown_protocol_instead_of_guessing_from_model_name():
    with pytest.raises(ValueError, match="unknown built-in model protocol"):
        resolve_model_protocol("unknown")


@pytest.mark.parametrize(
    ("model", "expected_field"),
    [
        ("gpt-5.6-luna", "max_completion_tokens"),
        ("o4-mini", "max_completion_tokens"),
        ("gpt-4o", "max_tokens"),
        ("third-party-model", "max_tokens"),
    ],
)
def test_chat_completions_factory_auto_selects_initial_token_field(
    model, expected_field
):
    route = ModelRoute(
        provider="openai-chat-completions",
        model=model,
        request=ModelRequestDefaults(max_output_tokens=128),
    )
    registration = builtin_extension_registry().get(
        "sage.model.openai-chat-completions"
    )

    provider = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="agent_test",
            config={"route": route.model_dump(mode="json"), "client": object()},
        ),
        {},
    )

    assert provider.config.max_output_tokens_field == "auto"
    outgoing = provider.diagnostic_request(request(max_output_tokens=128))
    assert outgoing[expected_field] == 128
