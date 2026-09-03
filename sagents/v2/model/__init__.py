"""Model contracts and lazily loaded provider implementations."""

from sagents.v2._lazy import exported_names, resolve_export


_CONTRACTS = "sagents.v2.model.contracts"
_CAPABILITIES = "sagents.v2.model.capability_contracts"
_PROBES = "sagents.v2.model.capability_probe"
_PROTOCOLS = "sagents.v2.model.protocols"
_EXPORTS = {
    "AnthropicMessagesConfig": (
        "sagents.v2.model.plugins.anthropic_messages",
        "AnthropicMessagesConfig",
    ),
    "AnthropicMessagesModelProvider": (
        "sagents.v2.model.plugins.anthropic_messages",
        "AnthropicMessagesModelProvider",
    ),
    "BuiltinModelProtocol": (_PROTOCOLS, "BuiltinModelProtocol"),
    "ModelCapabilities": (_CONTRACTS, "ModelCapabilities"),
    "ModelCapabilityProbeOutcome": (_CAPABILITIES, "ModelCapabilityProbeOutcome"),
    "ModelCapabilityProbeReport": (_CAPABILITIES, "ModelCapabilityProbeReport"),
    "ModelCapabilityProbeRequest": (_CAPABILITIES, "ModelCapabilityProbeRequest"),
    "ModelCapabilityProbeStatus": (_CAPABILITIES, "ModelCapabilityProbeStatus"),
    "ModelCapabilityProfile": (_CAPABILITIES, "ModelCapabilityProfile"),
    "ModelEventKind": (_CONTRACTS, "ModelEventKind"),
    "ModelMessage": (_CONTRACTS, "ModelMessage"),
    "ModelProtocolDescriptor": (_PROTOCOLS, "ModelProtocolDescriptor"),
    "ModelProvider": ("sagents.v2.model.provider", "ModelProvider"),
    "ModelProviderRegistry": ("sagents.v2.model.registry", "ModelProviderRegistry"),
    "ModelRequest": (_CONTRACTS, "ModelRequest"),
    "ModelResponse": (_CONTRACTS, "ModelResponse"),
    "ModelStreamEvent": (_CONTRACTS, "ModelStreamEvent"),
    "ModelToolCall": (_CONTRACTS, "ModelToolCall"),
    "ModelToolDefinition": (_CONTRACTS, "ModelToolDefinition"),
    "OpenAIChatCompletionsConfig": (
        "sagents.v2.model.plugins.openai_compatible",
        "OpenAIChatCompletionsConfig",
    ),
    "OpenAIChatCompletionsModelProvider": (
        "sagents.v2.model.plugins.openai_compatible",
        "OpenAIChatCompletionsModelProvider",
    ),
    "OpenAICompatibleConfig": (
        "sagents.v2.model.plugins.openai_compatible",
        "OpenAICompatibleConfig",
    ),
    "OpenAICompatibleModelProvider": (
        "sagents.v2.model.plugins.openai_compatible",
        "OpenAICompatibleModelProvider",
    ),
    "OpenAIResponsesConfig": (
        "sagents.v2.model.plugins.openai_responses",
        "OpenAIResponsesConfig",
    ),
    "OpenAIResponsesModelProvider": (
        "sagents.v2.model.plugins.openai_responses",
        "OpenAIResponsesModelProvider",
    ),
    "RecordingModelProvider": (
        "sagents.v2.model.middleware.recording",
        "RecordingModelProvider",
    ),
    "ScriptedModelProvider": (
        "sagents.v2.testing.plugins.scripted_model",
        "ScriptedModelProvider",
    ),
    "ScriptedModelStep": (
        "sagents.v2.testing.plugins.scripted_model",
        "ScriptedModelStep",
    ),
    "model_capability_profile": (_PROBES, "model_capability_profile"),
    "model_protocol_descriptor": (_PROTOCOLS, "model_protocol_descriptor"),
    "model_protocol_descriptors": (_PROTOCOLS, "model_protocol_descriptors"),
    "model_protocol_implementation": (_PROTOCOLS, "model_protocol_implementation"),
    "negotiate_model_output_limit": (_PROBES, "negotiate_model_output_limit"),
    "probe_model_capabilities": (_PROBES, "probe_model_capabilities"),
    "probe_model_connection": (_PROBES, "probe_model_connection"),
    "probe_model_json_object": (_PROBES, "probe_model_json_object"),
    "probe_model_multimodal": (_PROBES, "probe_model_multimodal"),
    "probe_model_reasoning_controls": (_PROBES, "probe_model_reasoning_controls"),
    "probe_model_tool_calling": (_PROBES, "probe_model_tool_calling"),
    "resolve_model_protocol": (_PROTOCOLS, "resolve_model_protocol"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
