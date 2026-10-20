from __future__ import annotations

from sagents.v2.runtime.extensions import CapabilityKey, ProviderSet

from tests.sagents.v2.model_fixture import FULL_MODEL_CAPABILITIES as CAPABILITIES

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

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
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.credentials import CredentialMaterial


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
async def test_openai_responses_closes_only_the_client_it_constructed(monkeypatch):
    class ClosableClient:
        def __init__(self):
            self.responses = FakeResponses(FakeAsyncStream(()))
            self.close_calls = 0

        async def close(self):
            self.close_calls += 1

    owned = ClosableClient()
    monkeypatch.setattr(
        "sagents.v2.model.plugins.openai_responses.AsyncOpenAI",
        lambda **kwargs: owned,
    )
    credential = CredentialMaterial(
        credential_id="model", secret=SecretStr("secret"), source="test"
    )
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(
            base_url="https://api.invalid/v1",
            model="gpt-test",
            capabilities=CAPABILITIES,
        ),
        credential,
    )
    await provider.close()

    injected = ClosableClient()
    injected_provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(
            base_url="https://api.invalid/v1",
            model="gpt-test",
            capabilities=CAPABILITIES,
        ),
        client=injected,
    )
    await injected_provider.close()

    assert owned.close_calls == 1
    assert injected.close_calls == 0


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


def test_openai_responses_preserves_image_blocks_in_tool_output():
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=object(),
    )
    image_uri = "data:image/png;base64,AA=="
    outgoing = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(
                    role="assistant",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_image",
                            name="analyze_image",
                            arguments={"image_path": "/workspace/cat.png"},
                        ),
                    ),
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id="call_image",
                    content=(
                        TextBlock(text="Inspect this image."),
                        ImageBlock(
                            uri=image_uri,
                            mime_type="image/png",
                            alt="/workspace/cat.png",
                        ),
                    ),
                ),
            )
        )
    )

    assert outgoing["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_image",
        "output": [
            {"type": "input_text", "text": "Inspect this image."},
            {
                "type": "input_image",
                "image_url": image_uri,
                "detail": "auto",
            },
        ],
    }


def test_openai_responses_omits_output_schema_when_tool_result_is_plain_text():
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=object(),
    )
    outgoing = provider.diagnostic_request(
        request(
            tools=(
                ModelToolDefinition(
                    name="load_skill",
                    description="Load one skill",
                    input_schema={
                        "type": "object",
                        "properties": {"skill_name": {"type": "string"}},
                    },
                    strict=True,
                    output_schema={
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "workspace_path": {"type": "string"},
                            "content_hash": {"type": "string"},
                            "active_skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "skill_name",
                            "workspace_path",
                            "content_hash",
                            "active_skills",
                        ],
                        "additionalProperties": False,
                    },
                ),
            ),
            messages=(
                ModelMessage(
                    role="assistant",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="call_skill",
                            name="load_skill",
                            arguments={"skill_name": "short-video-production"},
                        ),
                    ),
                ),
                ModelMessage(
                    role="tool",
                    tool_call_id="call_skill",
                    content=(
                        TextBlock(
                            text=(
                                "Skill short-video-production loaded. "
                                "Active skills: short-video-production."
                            )
                        ),
                    ),
                    metadata={
                        "skill_name": "short-video-production",
                        "workspace_path": "/tmp/skill",
                        "content_hash": "sha256:abc",
                        "active_skills": ["short-video-production"],
                    },
                ),
            ),
        )
    )

    assert "output_schema" not in outgoing["tools"][0]
    assert outgoing["input"][1] == {
        "type": "function_call_output",
        "call_id": "call_skill",
        "output": (
            "Skill short-video-production loaded. "
            "Active skills: short-video-production."
        ),
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


@pytest.mark.asyncio
async def test_openai_responses_rejects_stream_without_terminal_event():
    stream = FakeAsyncStream(
        ({"type": "response.output_text.delta", "delta": "partial"},)
    )
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(stream)),
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.stream_incomplete"
    assert caught.value.info.retryable is True
    assert caught.value.info.metadata["response_started"] is True
    assert stream.closed is True


@pytest.mark.asyncio
async def test_openai_responses_reads_tool_call_from_terminal_response_snapshot():
    stream = FakeAsyncStream(
        (
            {
                "type": "response.completed",
                "response": {
                    "id": "response_1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "id": "item_1",
                            "call_id": "call_1",
                            "name": "lookup",
                            "arguments": '{"q":"final"}',
                        }
                    ],
                },
            },
        )
    )
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(stream)),
    )

    events = [event async for event in provider.stream(request())]

    completed = events[-1].response
    assert completed is not None
    assert completed.tool_calls == (
        ModelToolCall(tool_call_id="call_1", name="lookup", arguments={"q": "final"}),
    )


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
                        "cache_creation_input_tokens": 2,
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
    assert completed.usage.input_tokens == 26
    assert completed.usage.output_tokens == 7
    assert completed.usage.cached_input_tokens == 4
    assert completed.usage.reported is True
    assert completed.usage.provider_usage == {
        "input_tokens": 20,
        "cache_read_input_tokens": 4,
        "cache_creation_input_tokens": 2,
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


@pytest.mark.asyncio
async def test_anthropic_messages_rejects_stream_without_message_stop():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="claude-test", capabilities=CAPABILITIES),
        client=FakeHTTPClient(
            (
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "partial"},
                },
            )
        ),
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.stream_incomplete"
    assert caught.value.info.retryable is True


@pytest.mark.asyncio
async def test_anthropic_messages_surfaces_sse_error_event():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="claude-test", capabilities=CAPABILITIES),
        client=FakeHTTPClient(({"type": "error", "error": {"message": "overloaded"}},)),
    )

    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]

    assert caught.value.info.code == "model.provider_permanent"
    assert "overloaded" in caught.value.info.message


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
@pytest.mark.asyncio
async def test_builtin_factory_uses_model_route_as_authoritative_protocol_selection(
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
    provider = await registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="agent_test",
            config={"route": route.model_dump(mode="json")},
        ),
        ProviderSet({CapabilityKey(capability="model.client"): object()}),
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
@pytest.mark.asyncio
async def test_chat_completions_factory_auto_selects_initial_token_field(
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

    provider = await registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="agent_test",
            config={"route": route.model_dump(mode="json")},
        ),
        ProviderSet({CapabilityKey(capability="model.client"): object()}),
    )

    assert provider.config.max_output_tokens_field == "auto"
    outgoing = provider.diagnostic_request(request(max_output_tokens=128))
    assert outgoing[expected_field] == 128


@pytest.mark.parametrize(
    "protocol,default",
    [
        ("openai-chat-completions", None),
        ("openai-responses", None),
        ("anthropic-messages", 4096),
    ],
)
@pytest.mark.parametrize("maximum", [None, 512])
def test_model_factory_preserves_protocol_output_defaults(protocol, default, maximum):
    from sagents.v2.model.protocols import create_registered_model_provider

    provider = create_registered_model_provider(
        ModelRoute(
            provider=protocol,
            model="test-model",
            request=ModelRequestDefaults(max_output_tokens=maximum),
        ),
        client=SimpleNamespace(),
    )
    assert provider.config.default_max_output_tokens == (
        maximum if maximum is not None else default
    )


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_text_only_binding_rejects_image_before_network(protocol):
    from sagents.v2.model.plugins.openai_compatible import (
        OpenAICompatibleConfig,
        OpenAICompatibleModelProvider,
    )

    caps = CAPABILITIES.model_copy(update={"supports_multimodal_input": False})
    if protocol == "chat":
        provider = OpenAICompatibleModelProvider(
            OpenAICompatibleConfig(
                base_url="https://example.invalid", model="text-only", capabilities=caps
            ),
            client=object(),
        )
    elif protocol == "responses":
        provider = OpenAIResponsesModelProvider(
            OpenAIResponsesConfig(
                base_url="https://example.invalid", model="text-only", capabilities=caps
            ),
            client=object(),
        )
    else:
        provider = AnthropicMessagesModelProvider(
            AnthropicMessagesConfig(
                base_url="https://example.invalid", model="text-only", capabilities=caps
            ),
            client=object(),
        )
    with pytest.raises(SageV2Error) as caught:
        provider._validate_request(request())
    assert caught.value.info.code == "model.capability_unsupported"


@pytest.mark.parametrize("provider_id", ["orcarouter", " OrcaRouter "])
def test_orcarouter_resolves_to_openai_compatible_protocol(provider_id):
    from sagents.v2.model.protocols import model_protocol_default_base_url

    assert (
        resolve_model_protocol(provider_id)
        == BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS
    )
    assert (
        model_protocol_default_base_url(provider_id) == "https://api.orcarouter.ai/v1"
    )


@pytest.mark.parametrize("base_url", [None, "https://gateway.example/v1"])
def test_orcarouter_factory_uses_openai_compatible_provider(base_url):
    from sagents.v2.model.protocols import create_registered_model_provider

    provider = create_registered_model_provider(
        ModelRoute(provider="orcarouter", base_url=base_url, model="orcarouter/auto"),
        client=object(),
    )

    assert isinstance(provider, OpenAIChatCompletionsModelProvider)
    assert provider.config.base_url == (base_url or "https://api.orcarouter.ai/v1")
    assert provider.config.model == "orcarouter/auto"


@pytest.mark.parametrize(
    ("provider_id", "expected_url"),
    [
        ("openai-chat-completions", "https://api.openai.com/v1"),
        ("openai-compatible", "https://api.openai.com/v1"),
        ("openai-responses", "https://api.openai.com/v1"),
        ("anthropic-messages", "https://api.anthropic.com"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta"),
    ],
)
def test_existing_protocol_default_base_urls_are_preserved(provider_id, expected_url):
    from sagents.v2.model.protocols import model_protocol_default_base_url

    assert model_protocol_default_base_url(provider_id) == expected_url


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["response.failed", "error"])
@pytest.mark.parametrize(
    "code,expected",
    [
        ("context_length_exceeded", "model.context_window_exceeded"),
        ("server_error", "model.provider_transient"),
        ("rate_limit_exceeded", "model.provider_transient"),
        ("invalid_api_key", "model.provider_permanent"),
    ],
)
async def test_responses_stream_errors_keep_codes_for_recovery(
    event_type, code, expected
):
    payload = {"code": code, "message": "upstream rejected request"}
    event = {"type": event_type}
    if event_type == "response.failed":
        event["response"] = {"error": payload}
    else:
        event.update(payload)
    upstream = FakeAsyncStream((event,))
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(upstream)),
    )
    with pytest.raises(SageV2Error) as caught:
        _ = [e async for e in provider.stream(request())]
    assert caught.value.info.code == expected
    assert caught.value.info.provider_code == code
    assert caught.value.info.retryable == (code != "invalid_api_key")
    assert caught.value.info.metadata["response_started"] is False
    assert upstream.closed


@pytest.mark.parametrize("kind", [TimeoutError, ConnectionError])
def test_transport_errors_are_transient_without_http_status(kind):
    from sagents.v2.model.plugins._shared.wire import provider_error

    error = provider_error(kind("connection interrupted"))
    assert error.info.code == "model.provider_transient"
    assert error.info.retryable


@pytest.mark.asyncio
async def test_builtin_factory_resolves_credentials_through_declared_provider():
    from sagents.v2.runtime.credentials import MappingCredentialProvider

    route = ModelRoute(provider="openai-responses", model="model-test", credential="primary-key")
    context = ExtensionScopeContext(
        scope=ExtensionScope.AGENT, scope_id="agent", tenant_id="tenant",
        config={"route": route.model_dump(mode="json")},
    )
    providers = ProviderSet({
        CapabilityKey(capability="credentials.provider"): MappingCredentialProvider({"primary-key": "dependency-secret"}),
        CapabilityKey(capability="model.client"): object(),
    })
    provider = await builtin_extension_registry().get("sage.model.openai-responses").factory(context, providers)
    assert provider.config.api_key.get_secret_value() == "dependency-secret"
    assert context.config == {"route": route.model_dump(mode="json")}
