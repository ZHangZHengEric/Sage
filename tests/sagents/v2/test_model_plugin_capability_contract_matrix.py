from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    ModelCapabilities,
    ModelCapabilityProbeOutcome,
    ModelCapabilityProbeRequest,
    ModelCapabilityProbeStatus,
    ModelCapabilityProfile,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    OpenAIChatCompletionsConfig,
    OpenAIChatCompletionsModelProvider,
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    model_protocol_descriptors,
)
from sagents.v2.package.manifest.models import ModelRequestDefaults, ModelRoute


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


def _supported_outcomes():
    return tuple(
        ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.SUPPORTED,
            response="ok",
        )
        for name in (
            "connection",
            "multimodal",
            "structured_output",
            "json_object",
            "tool_calling",
            "reasoning_control",
        )
    )


class _SemanticProbeMixin:
    async def _stream(self, request):
        if "multimodal" in request.request_id:
            if (
                hasattr(self.config, "image_detail_mode")
                and self.config.image_detail_mode == "include"
            ):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.provider_permanent",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message="image_url.detail is not accepted",
                        provider_code="400",
                    )
                )
            response = ModelResponse(
                response_id="response_image",
                text="red",
                finish_reason="stop",
            )
        elif "structured" in request.request_id or "json_object" in request.request_id:
            response = ModelResponse(
                response_id="response_json",
                text='{"ok":true}',
                finish_reason="stop",
            )
        elif "tool" in request.request_id:
            response = ModelResponse(
                response_id="response_tool",
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="call_probe",
                        name="sage_capability_probe",
                        arguments={"value": "OK"},
                    ),
                ),
                finish_reason="tool_calls",
            )
        else:
            reasoning_effort = getattr(self.config, "reasoning_effort", None)
            response = ModelResponse(
                response_id="response_text",
                text="323" if reasoning_effort else "OK",
                reasoning="checked" if reasoning_effort else "",
                finish_reason="stop",
            )
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)


class _ChatProbeProvider(_SemanticProbeMixin, OpenAIChatCompletionsModelProvider):
    pass


class _ResponsesProbeProvider(_SemanticProbeMixin, OpenAIResponsesModelProvider):
    pass


class _AnthropicProbeProvider(_SemanticProbeMixin, AnthropicMessagesModelProvider):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "protocol", "plugin_id"),
    [
        (
            _ChatProbeProvider(
                OpenAIChatCompletionsConfig(
                    model="DeepSeek-V4-Flash-Vision-Exp",
                    base_url="https://example.invalid/v1",
                    capabilities=CAPABILITIES,
                    default_max_output_tokens=128,
                ),
                client=object(),
            ),
            "openai-chat-completions",
            "sage.model.openai-chat-completions",
        ),
        (
            _ResponsesProbeProvider(
                OpenAIResponsesConfig(
                    model="gpt-test",
                    capabilities=CAPABILITIES,
                    default_max_output_tokens=128,
                ),
                client=object(),
            ),
            "openai-responses",
            "sage.model.openai-responses",
        ),
        (
            _AnthropicProbeProvider(
                AnthropicMessagesConfig(
                    model="claude-test",
                    capabilities=CAPABILITIES,
                    default_max_output_tokens=128,
                ),
                client=object(),
            ),
            "anthropic-messages",
            "sage.model.anthropic-messages",
        ),
    ],
)
async def test_every_builtin_model_plugin_returns_owned_versioned_profile(
    provider, protocol, plugin_id
):
    profile = await provider.probe_capabilities(
        ModelCapabilityProbeRequest(
            model_binding="primary",
            route_fingerprint="sha256:route",
            max_output_tokens=128,
            reasoning_efforts=("low",),
        )
    )

    assert profile.schema_version == 1
    assert profile.plugin_id == plugin_id
    assert profile.plugin_version == "3.0.0"
    assert profile.protocol == protocol
    assert profile.route_fingerprint == "sha256:route"
    assert profile.supports("connection") is True
    assert profile.supports("multimodal") is True
    assert profile.invocation_strategy["supported_reasoning_efforts"] == ["low"]

    if protocol == "openai-chat-completions":
        assert profile.invocation_strategy["image_transport"] == "data_uri"
        assert profile.invocation_strategy["image_detail_mode"] == "omit"
        assert "responses" not in profile.invocation_strategy


def test_every_builtin_protocol_advertises_the_probe_contract_version():
    descriptors = model_protocol_descriptors()

    assert len(descriptors) == 3
    assert all("multimodal" in value.capabilities for value in descriptors)
    assert {
        value.plugin_id for value in descriptors
    } == {
        "sage.model.openai-chat-completions",
        "sage.model.openai-responses",
        "sage.model.anthropic-messages",
    }


def test_chat_plugin_reuses_its_recorded_image_and_token_dialect():
    profile = ModelCapabilityProfile(
        plugin_id="sage.model.openai-chat-completions",
        plugin_version="3.0.0",
        protocol="openai-chat-completions",
        route_fingerprint="sha256:route",
        effective_max_output_tokens=512,
        outcomes=_supported_outcomes(),
        invocation_strategy={
            "max_output_tokens_field": "max_completion_tokens",
            "image_detail_mode": "omit",
        },
    )
    provider = create_registered_model_provider(
        ModelRoute(
            provider="openai-chat-completions",
            model="DeepSeek-V4-Flash-Vision-Exp",
            request=ModelRequestDefaults(max_output_tokens=8_192),
            capability_profile=profile,
        ),
        client=object(),
    )

    assert provider.config.default_max_output_tokens == 512
    assert provider.config.max_output_tokens_field == "max_completion_tokens"
    assert provider.config.image_detail_mode == "omit"
    payload = provider.diagnostic_request(
        ModelRequest(
            request_id="request_1",
            run_id="run_1",
            model_binding="primary",
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(text="inspect"),
                        ImageBlock(
                            uri="data:image/png;base64,AA==",
                            mime_type="image/png",
                        ),
                    ),
                ),
            ),
        )
    )
    assert "input" not in payload
    assert payload["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AA=="},
    }
    assert payload["max_completion_tokens"] == 512


def test_profile_from_another_protocol_is_rejected_instead_of_falling_back():
    profile = ModelCapabilityProfile(
        plugin_id="sage.model.openai-responses",
        plugin_version="3.0.0",
        protocol="openai-responses",
        route_fingerprint="sha256:route",
        effective_max_output_tokens=512,
        outcomes=_supported_outcomes(),
    )

    with pytest.raises(ValueError, match="protocol does not match"):
        create_registered_model_provider(
            ModelRoute(
                provider="openai-chat-completions",
                model="DeepSeek-V4-Flash-Vision-Exp",
                capability_profile=profile,
            ),
            client=object(),
        )
