"""Protocol metadata and constructors used by registered model plugins.

This module does not select a provider. Selection belongs to
``ModelProviderRegistry``; each registration calls the constructor only after
the extension resolver has selected its stable plugin ID.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.model.plugins.anthropic_messages import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
)
from sagents.v2.model.contracts import ModelCapabilities
from sagents.v2.model.plugins.openai_compatible import (
    OpenAIChatCompletionsConfig,
    OpenAIChatCompletionsModelProvider,
)
from sagents.v2.model.plugins.openai_responses import (
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.capability_contracts import ModelCapabilityProfile


class BuiltinModelProtocol(str, Enum):
    """Stable protocol ids accepted by `ModelRoute.provider`."""

    OPENAI_CHAT_COMPLETIONS = "openai-chat-completions"
    OPENAI_RESPONSES = "openai-responses"
    ANTHROPIC_MESSAGES = "anthropic-messages"


_PROTOCOL_PROVIDERS = {
    BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS: OpenAIChatCompletionsModelProvider,
    BuiltinModelProtocol.OPENAI_RESPONSES: OpenAIResponsesModelProvider,
    BuiltinModelProtocol.ANTHROPIC_MESSAGES: AnthropicMessagesModelProvider,
}


class ModelProtocolDescriptor(StrictModel):
    """Non-secret metadata that hosts can expose in settings and diagnostics."""

    protocol: BuiltinModelProtocol
    name: str
    value: str
    default_base_url: str
    aliases: tuple[str, ...] = ()
    config_driven: bool = True
    capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def plugin_id(self) -> str:
        return _PROTOCOL_PROVIDERS[self.protocol].plugin_id


_DESCRIPTORS = (
    ModelProtocolDescriptor(
        protocol=BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS,
        name=OpenAIChatCompletionsModelProvider.name,
        value=OpenAIChatCompletionsModelProvider.description,
        default_base_url="https://api.openai.com/v1",
        aliases=("openai-compatible", "chat-completions", "completions"),
        capabilities=("streaming", "tools", "structured-output", "multimodal"),
    ),
    ModelProtocolDescriptor(
        protocol=BuiltinModelProtocol.OPENAI_RESPONSES,
        name=OpenAIResponsesModelProvider.name,
        value=OpenAIResponsesModelProvider.description,
        default_base_url="https://api.openai.com/v1",
        aliases=("responses",),
        capabilities=(
            "streaming",
            "tools",
            "structured-output",
            "reasoning",
            "multimodal",
        ),
        notes=("Sage keeps the authoritative conversation ledger by default.",),
    ),
    ModelProtocolDescriptor(
        protocol=BuiltinModelProtocol.ANTHROPIC_MESSAGES,
        name=AnthropicMessagesModelProvider.name,
        value=AnthropicMessagesModelProvider.description,
        default_base_url="https://api.anthropic.com",
        aliases=("anthropic", "claude", "claude-messages"),
        capabilities=(
            "streaming",
            "tools",
            "structured-output",
            "reasoning",
            "multimodal",
        ),
    ),
)


def model_protocol_descriptors() -> tuple[ModelProtocolDescriptor, ...]:
    return _DESCRIPTORS


def model_protocol_implementation(protocol: BuiltinModelProtocol):
    """Return the implementation class registered for one built-in protocol."""

    return _PROTOCOL_PROVIDERS[protocol]


def resolve_model_protocol(provider_id: str) -> BuiltinModelProtocol:
    normalized = provider_id.strip().lower()
    for descriptor in _DESCRIPTORS:
        if normalized in {descriptor.protocol.value, *descriptor.aliases}:
            return descriptor.protocol
    raise ValueError(f"unknown built-in model protocol {provider_id!r}")


def model_protocol_descriptor(provider_id: str) -> ModelProtocolDescriptor:
    protocol = resolve_model_protocol(provider_id)
    return next(value for value in _DESCRIPTORS if value.protocol == protocol)


def create_registered_model_provider(
    route: ModelRoute,
    credential: CredentialMaterial | None = None,
    *,
    client: Any | None = None,
    provider_instance_id: str | None = None,
    capability_profile: ModelCapabilityProfile | None = None,
) -> ModelProvider:
    """Construct the implementation selected by a real plugin registration."""

    protocol = resolve_model_protocol(route.provider)
    descriptor = model_protocol_descriptor(route.provider)
    implementation = _PROTOCOL_PROVIDERS[protocol]
    capability_profile = capability_profile or route.capability_profile
    if capability_profile is not None:
        if capability_profile.protocol != protocol.value:
            raise ValueError("model capability profile protocol does not match route")
        if capability_profile.plugin_id != implementation.plugin_id:
            raise ValueError("model capability profile owner does not match route")
        if capability_profile.plugin_version != implementation.plugin_version:
            raise ValueError("model capability profile version is stale")
    declaration = route.capabilities
    capabilities = ModelCapabilities(
        supports_streaming=True,
        supports_tools=bool(declaration.tool_calling),
        supports_parallel_tool_calls=bool(declaration.parallel_tool_calls),
        supports_reasoning=bool(declaration.reasoning),
        supports_multimodal_input=bool(declaration.multimodal),
        supports_structured_output=bool(declaration.structured_output),
        max_input_tokens=route.limits.context_window,
        max_output_tokens=route.limits.max_output_tokens,
    )
    common = {
        "provider_id": provider_instance_id or route.provider,
        "base_url": route.base_url or descriptor.default_base_url,
        "model": route.model,
        "capabilities": capabilities,
        "default_max_output_tokens": route.request.max_output_tokens,
        "default_temperature": route.request.temperature,
        "default_top_p": route.request.top_p,
    }
    extra = dict(route.request.extra)
    if protocol == BuiltinModelProtocol.OPENAI_CHAT_COMPLETIONS:
        maximum_field = str(
            extra.pop(
                "max_output_tokens_field",
                "auto",
            )
        )
        if maximum_field not in {"auto", "max_tokens", "max_completion_tokens"}:
            raise ValueError(
                "max_output_tokens_field must be auto, max_tokens, or "
                "max_completion_tokens"
            )
        config = OpenAIChatCompletionsConfig(
            **common,
            reasoning_effort=route.request.reasoning_effort,
            max_output_tokens_field=maximum_field,
            reasoning_parameter_fallback=bool(
                extra.pop("reasoning_parameter_fallback", False)
            ),
            extra_body=extra,
        )
        if capability_profile is not None:
            config = implementation.apply_capability_profile(
                config, capability_profile
            )
        return OpenAIChatCompletionsModelProvider(config, credential, client=client)
    if protocol == BuiltinModelProtocol.OPENAI_RESPONSES:
        config = OpenAIResponsesConfig(
            **common,
            reasoning_effort=route.request.reasoning_effort,
            store=bool(extra.pop("store", False)),
            reasoning_parameter_fallback=bool(
                extra.pop("reasoning_parameter_fallback", False)
            ),
            extra_body=extra,
        )
        if capability_profile is not None:
            config = implementation.apply_capability_profile(
                config, capability_profile
            )
        return OpenAIResponsesModelProvider(config, credential, client=client)
    config = AnthropicMessagesConfig(
        **common,
        reasoning_effort=route.request.reasoning_effort,
        anthropic_version=str(extra.pop("anthropic_version", "2023-06-01")),
        extra_headers=dict(extra.pop("extra_headers", {})),
        extra_body=extra,
    )
    if capability_profile is not None:
        config = implementation.apply_capability_profile(config, capability_profile)
    return AnthropicMessagesModelProvider(config, credential, client=client)
