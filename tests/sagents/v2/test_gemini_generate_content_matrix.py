from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, JsonBlock, TextBlock
from sagents.v2.contracts.provider_state import read_provider_state
from sagents.v2.model import (
    GeminiGenerateContentConfig,
    GeminiGenerateContentModelProvider,
    ModelMessage,
    ModelRequest,
    ModelToolDefinition,
)
from sagents.v2.model.protocols import resolve_model_protocol
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.package.manifest.models import ModelRoute
from tests.sagents.v2.test_builtin_model_protocols_matrix import CAPABILITIES


def request(**updates):
    return ModelRequest(
        **{
            "request_id": "request_gemini",
            "run_id": "run_gemini",
            "model_binding": "primary",
            "messages": (
                ModelMessage(role="system", content=(TextBlock(text="be exact"),)),
                ModelMessage(role="user", content=(TextBlock(text="lookup"),)),
            ),
            **updates,
        }
    )


def event(parts=(), *, finish=None, **extra):
    candidate = {"index": 0, "content": {"role": "model", "parts": list(parts)}}
    if finish:
        candidate["finishReason"] = finish
    return {"candidates": [candidate], **extra}


def sse(events):
    return "".join("data: " + json.dumps(value) + "\n\n" for value in events)


def provider_for(events, **config):
    captured = []

    def handler(wire):
        captured.append(wire)
        return httpx.Response(
            200, text=sse(events), headers={"content-type": "text/event-stream"}
        )

    client = httpx.AsyncClient(
        base_url="https://gemini.invalid/v1beta/",
        transport=httpx.MockTransport(handler),
    )
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(
            model="gemini-3-test", capabilities=CAPABILITIES, **config
        ),
        client=client,
    )
    return provider, client, captured


@pytest.mark.asyncio
async def test_native_parallel_calls_and_signatures_are_replayed_with_results():
    parts = [
        {"text": "checking", "thought": True},
        {
            "functionCall": {"name": "lookup", "args": {"q": "first"}},
            "thoughtSignature": "opaque-first",
        },
        {"functionCall": {"id": "native-2", "name": "lookup", "args": {"q": "second"}}},
    ]
    provider, client, captured = provider_for(
        [
            event(parts, finish="STOP", responseId="google-response"),
            {
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "cachedContentTokenCount": 3,
                    "candidatesTokenCount": 5,
                    "thoughtsTokenCount": 2,
                }
            },
        ]
    )
    try:
        events = [value async for value in provider.stream(request())]
        response = events[-1].response
        assert response.response_id == "google-response"
        assert response.reasoning == "checking"
        assert len(response.tool_calls) == 2
        assert response.usage.output_tokens == 7
        assert response.usage.input_tokens == 12
        assert response.usage.cached_input_tokens == 3
        assert response.usage.reasoning_tokens == 2
        assert (
            captured[0].url.path == "/v1beta/models/gemini-3-test:streamGenerateContent"
        )
        assert captured[0].url.params["alt"] == "sse"
        state = read_provider_state(response.provider_state, "gemini_generate_content")
        assert state["parts"] == parts
        messages = (
            *request().messages,
            ModelMessage(
                role="assistant",
                tool_calls=response.tool_calls,
                provider_state=response.provider_state,
            ),
            *(
                ModelMessage(
                    role="tool",
                    tool_call_id=call.tool_call_id,
                    content=(JsonBlock(value={"result": index}),),
                )
                for index, call in enumerate(response.tool_calls)
            ),
        )
        replay = provider.diagnostic_request(request(messages=messages))["contents"]
        assert replay[-2] == {"role": "model", "parts": parts}
        assert replay[-1] == {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": "lookup", "response": {"result": 0}}},
                {
                    "functionResponse": {
                        "name": "lookup",
                        "id": "native-2",
                        "response": {"result": 1},
                    }
                },
            ],
        }
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_signature_only_part_and_text_deltas_survive_json_round_trip():
    parts = [
        {"text": "Hello "},
        {"text": "world"},
        {"text": "", "thoughtSignature": "opaque-last"},
    ]
    provider, client, _ = provider_for(
        [
            event([part], finish="STOP" if index == 2 else None)
            for index, part in enumerate(parts)
        ]
    )
    try:
        values = [value async for value in provider.stream(request())]
        response = values[-1].response
        assert response.text == "Hello world"
        restored = ModelMessage.model_validate_json(
            ModelMessage(
                role="assistant",
                content=(TextBlock(text=response.text),),
                provider_state=response.provider_state,
            ).model_dump_json()
        )
        outgoing = provider.diagnostic_request(
            request(messages=(*request().messages, restored))
        )
        assert outgoing["contents"][-1]["parts"] == parts
        assert len(values) == 3
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("model", "effort", "control"),
    [
        ("gemini-2.5-flash", "medium", {"thinkingBudget": 4096}),
        ("models/gemini-3-pro", "low", {"thinkingLevel": "low"}),
    ],
)
def test_request_uses_native_thinking_tools_json_and_media(model, effort, control):
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(
            model=model, capabilities=CAPABILITIES, reasoning_effort=effort
        ),
        client=object(),
    )
    payload = provider.diagnostic_request(
        request(
            messages=(
                *request().messages,
                ModelMessage(
                    role="user",
                    content=(
                        ImageBlock(
                            uri="data:image/png;base64,YQ==", mime_type="image/png"
                        ),
                    ),
                ),
            ),
            tools=(
                ModelToolDefinition(
                    name="lookup",
                    description="look up",
                    input_schema={"type": "object"},
                ),
            ),
            tool_choice="required",
            response_schema={"type": "object"},
            max_output_tokens=128,
        )
    )
    assert payload["systemInstruction"] == {"parts": [{"text": "be exact"}]}
    assert payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        **control,
    }
    assert payload["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert payload["generationConfig"]["maxOutputTokens"] == 128
    assert payload["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"] == {
        "type": "object"
    }
    assert payload["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert payload["contents"][-1]["parts"][-1] == {
        "inlineData": {"mimeType": "image/png", "data": "YQ=="}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "code"),
    [
        ([event([{"text": "partial"}])], "model.stream_incomplete"),
        ([{"promptFeedback": {"blockReason": "SAFETY"}}], "model.response_blocked"),
        ([event([], finish="SAFETY")], "model.response_rejected"),
        (
            [event([{"functionCall": {"name": "lookup", "args": []}}], finish="STOP")],
            "model.tool_arguments_not_object",
        ),
        (
            [event([{"inlineData": {"data": "a"}}], finish="STOP")],
            "model.response_unsupported",
        ),
        (
            [{"error": {"code": 429, "message": "rate limited"}}],
            "model.provider_transient",
        ),
    ],
)
async def test_stream_failures_are_not_successful_completions(events, code):
    provider, client, _ = provider_for(events)
    try:
        with pytest.raises(SageV2Error) as error:
            [value async for value in provider.stream(request())]
        assert error.value.info.code == code
        if code == "model.provider_transient":
            assert error.value.info.retryable is True
        if code == "model.stream_incomplete":
            assert error.value.info.retryable is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_thinking_only_token_limit_is_a_continuable_response():
    provider, client, _ = provider_for(
        [event([{"text": "thinking", "thought": True}], finish="MAX_TOKENS")]
    )
    try:
        values = [value async for value in provider.stream(request())]
        assert values[-1].response.finish_reason == "max_tokens"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_owned_client_uses_api_key_header_and_preserves_gateway_base_path(
    monkeypatch,
):
    seen = []
    original = httpx.AsyncClient

    def handler(wire):
        seen.append(wire)
        return httpx.Response(200, text=sse([event([{"text": "ok"}], finish="STOP")]))

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(
            model="models/gemini-test",
            base_url="https://gateway.invalid/custom/v1beta",
            capabilities=CAPABILITIES,
        ),
        CredentialMaterial(
            credential_id="gemini", secret=SecretStr("test-secret"), source="test"
        ),
    )
    [value async for value in provider.stream(request())]
    await provider.close()
    assert provider.raw_client.is_closed
    assert (
        seen[-1].url.path == "/custom/v1beta/models/gemini-test:streamGenerateContent"
    )
    assert seen[-1].headers["x-goog-api-key"] == "test-secret"
    assert "test-secret" not in str(seen[-1].url)


@pytest.mark.asyncio
async def test_injected_client_is_not_closed_by_provider():
    provider, client, _ = provider_for([])
    await provider.close()
    assert not client.is_closed
    await client.aclose()


def test_registry_selects_gemini_by_explicit_protocol_not_model_name():
    assert resolve_model_protocol("gemini").value == "gemini-generate-content"
    registry = builtin_extension_registry()
    provider = registry.get("sage.model.gemini-generate-content").factory(
        ExtensionScopeContext(
            scope=ExtensionScope.RUN,
            scope_id="run_gemini",
            config={
                "route": ModelRoute(
                    provider="gemini", model="custom-gateway-model"
                ).model_dump(mode="json"),
                "client": object(),
            },
        ),
        {},
    )
    assert isinstance(provider, GeminiGenerateContentModelProvider)
    assert (
        provider.config.base_url == "https://generativelanguage.googleapis.com/v1beta"
    )


@pytest.mark.parametrize(
    "field",
    [
        "contents",
        "generationConfig",
        "toolConfig",
        "tools",
        "systemInstruction",
        "generation_config",
        "tool_config",
        "system_instruction",
    ],
)
def test_extensions_cannot_replace_host_owned_fields(field):
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(
            model="gemini-test", capabilities=CAPABILITIES, extra_body={field: {}}
        ),
        client=object(),
    )
    with pytest.raises(SageV2Error) as error:
        provider.diagnostic_request(request())
    assert error.value.info.code == "model.extra_body_conflict"


def test_replay_rejects_mismatched_call_state():
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(model="gemini-test", capabilities=CAPABILITIES),
        client=object(),
    )
    message = ModelMessage(
        role="assistant",
        provider_state={
            "gemini_generate_content": {
                "parts": [
                    {"functionCall": {"name": "lookup"}, "thoughtSignature": "opaque"}
                ],
                "tool_call_ids": [],
            }
        },
    )
    with pytest.raises(SageV2Error) as error:
        provider.diagnostic_request(request(messages=(message,)))
    assert error.value.info.code == "model.provider_state_invalid"


@pytest.mark.asyncio
async def test_native_tool_round_trip_survives_session_store_restart(tmp_path):
    from sagents.v2.runtime import HarnessRuntime
    from sagents.v2.runtime.session import FilesystemSessionStore
    from sagents.v2.tool import ToolDefinition, SideEffectLevel, ToolExecutionResult
    from tests.sagents.v2.test_session_history_context_matrix import (
        CONTEXT,
        command,
        execute,
    )

    signed_call = {
        "functionCall": {"name": "lookup", "args": {"q": "persist"}},
        "thoughtSignature": "persistent-signature",
    }
    signed_answer = {"text": "done", "thoughtSignature": "answer-signature"}
    batches = [
        [event([signed_call], finish="STOP")],
        [event([signed_answer], finish="STOP")],
        [event([{"text": "remembered"}], finish="STOP")],
    ]
    captured = []

    def handler(wire):
        captured.append(json.loads(wire.content))
        return httpx.Response(200, text=sse(batches[len(captured) - 1]))

    client = httpx.AsyncClient(
        base_url="https://gemini.invalid/v1beta/",
        transport=httpx.MockTransport(handler),
    )
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(model="gemini-3-test", capabilities=CAPABILITIES),
        client=client,
    )
    definition = ToolDefinition(
        name="lookup",
        description="lookup",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )

    async def lookup(call, _context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="found"),),
        )

    path = tmp_path / "gemini.sqlite3"
    store = FilesystemSessionStore(path)
    runtime = HarnessRuntime(store)
    try:
        first = await runtime.start_run(command("look up", "gemini-first"), CONTEXT)
        await execute(
            runtime,
            first,
            provider,
            definitions=(definition,),
            handlers={"lookup": lookup},
        )
        assert len(captured) == 2
        assert captured[1]["contents"][-2]["parts"] == [signed_call]
        assert captured[1]["contents"][-1]["parts"] == [
            {"functionResponse": {"name": "lookup", "response": {"output": "found"}}}
        ]
        await store.close()
        store = FilesystemSessionStore(path)
        runtime = HarnessRuntime(store)
        second = await runtime.start_run(
            command("follow up", "gemini-second", session_id=first.session_id), CONTEXT
        )
        await execute(runtime, second, provider)
        assert len(captured) == 3
        restored = captured[2]["contents"]
        assert {"role": "model", "parts": [signed_call]} in restored
        assert {"role": "model", "parts": [signed_answer]} in restored
        assert restored[-1] == {"role": "user", "parts": [{"text": "follow up"}]}
    finally:
        await store.close()
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message", "code", "retryable"),
    [
        (
            400,
            "The input token count (129000) exceeds the maximum number of tokens allowed (128000).",
            "model.context_window_exceeded",
            True,
        ),
        (401, "API key invalid", "model.provider_permanent", False),
        (503, "Service unavailable", "model.provider_transient", True),
    ],
)
async def test_http_errors_preserve_context_recovery_and_retry_classification(
    status, message, code, retryable
):
    client = httpx.AsyncClient(
        base_url="https://gemini.invalid/v1beta/",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                status, json={"error": {"message": message}}
            )
        ),
    )
    provider = GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(model="gemini-test", capabilities=CAPABILITIES),
        client=client,
    )
    try:
        with pytest.raises(SageV2Error) as error:
            [value async for value in provider.stream(request())]
        assert error.value.info.code == code
        assert error.value.info.retryable is retryable
    finally:
        await client.aclose()


@pytest.mark.parametrize(("effort", "expected_budget"), [(None, 0), ("high", 8192)])
def test_factory_reuses_probed_thinking_dialect_without_overriding_enabled_reasoning(
    effort, expected_budget
):
    from sagents.v2.model import (
        ModelCapabilityProfile,
        ModelCapabilityProbeOutcome,
        ModelCapabilityProbeStatus,
    )
    from sagents.v2.model.protocols import create_registered_model_provider
    from sagents.v2.package.manifest.models import (
        ModelCapabilityDeclaration,
        ModelRequestDefaults,
    )
    from app.v2.desktop.backend.catalog import DesktopModelCompatibilityProfile

    profile = ModelCapabilityProfile(
        plugin_id=GeminiGenerateContentModelProvider.plugin_id,
        plugin_version=GeminiGenerateContentModelProvider.plugin_version,
        protocol="gemini-generate-content",
        route_fingerprint="sha256:gemini-test",
        effective_max_output_tokens=4096,
        outcomes=tuple(
            ModelCapabilityProbeOutcome(
                name=name, status=ModelCapabilityProbeStatus.SUPPORTED
            )
            for name in (
                "connection",
                "multimodal",
                "structured_output",
                "json_object",
                "tool_calling",
                "reasoning_control",
            )
        ),
        invocation_strategy={
            "thinking_control": "budget",
            "reasoning_disable_strategy": "thinking_budget_zero",
        },
    )
    desktop = DesktopModelCompatibilityProfile(
        route_fingerprint=profile.route_fingerprint,
        reasoning_disable_strategy="thinking_budget_zero",
        plugin_profile=profile,
    )
    provider = create_registered_model_provider(
        ModelRoute(
            provider="gemini-generate-content",
            model="gateway-model",
            capabilities=ModelCapabilityDeclaration(reasoning=True),
            request=ModelRequestDefaults(
                max_output_tokens=8192, reasoning_effort=effort
            ),
            capability_profile=desktop.plugin_profile,
        ),
        client=object(),
    )
    payload = provider.diagnostic_request(request())
    assert payload["generationConfig"]["maxOutputTokens"] == 4096
    assert (
        payload["generationConfig"]["thinkingConfig"]["thinkingBudget"]
        == expected_budget
    )
