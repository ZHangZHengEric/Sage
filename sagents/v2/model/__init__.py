"""Model contracts and lazily loaded provider implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.model.plugins._shared.usage import CanonicalTokenUsage as CanonicalTokenUsage
    from sagents.v2.model.plugins._shared.usage import canonical_token_usage as canonical_token_usage
    from sagents.v2.model.plugins._shared.usage import has_token_usage as has_token_usage
    from sagents.v2.model.plugins.gemini_generate_content import GeminiGenerateContentConfig as GeminiGenerateContentConfig
    from sagents.v2.model.plugins.gemini_generate_content import GeminiGenerateContentModelProvider as GeminiGenerateContentModelProvider
    from sagents.v2.model.plugins.anthropic_messages import AnthropicMessagesConfig as AnthropicMessagesConfig
    from sagents.v2.model.plugins.anthropic_messages import AnthropicMessagesModelProvider as AnthropicMessagesModelProvider
    from sagents.v2.model.protocols import BuiltinModelProtocol as BuiltinModelProtocol
    from sagents.v2.model.contracts import ModelCapabilities as ModelCapabilities
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeOutcome as ModelCapabilityProbeOutcome
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeReport as ModelCapabilityProbeReport
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeRequest as ModelCapabilityProbeRequest
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeStatus as ModelCapabilityProbeStatus
    from sagents.v2.model.capability_contracts import ModelCapabilityProfile as ModelCapabilityProfile
    from sagents.v2.model.contracts import ModelEventKind as ModelEventKind
    from sagents.v2.model.contracts import ModelMessage as ModelMessage
    from sagents.v2.model.protocols import ModelProtocolDescriptor as ModelProtocolDescriptor
    from sagents.v2.model.provider import ModelProvider as ModelProvider
    from sagents.v2.model.registry import ModelProviderRegistry as ModelProviderRegistry
    from sagents.v2.model.contracts import ModelRequest as ModelRequest
    from sagents.v2.model.contracts import ModelResponse as ModelResponse
    from sagents.v2.model.contracts import ModelStreamEvent as ModelStreamEvent
    from sagents.v2.model.contracts import ModelToolCall as ModelToolCall
    from sagents.v2.model.contracts import ModelToolDefinition as ModelToolDefinition
    from sagents.v2.model.plugins.openai_compatible import OpenAIChatCompletionsConfig as OpenAIChatCompletionsConfig
    from sagents.v2.model.plugins.openai_compatible import OpenAIChatCompletionsModelProvider as OpenAIChatCompletionsModelProvider
    from sagents.v2.model.plugins.openai_compatible import OpenAICompatibleConfig as OpenAICompatibleConfig
    from sagents.v2.model.plugins.openai_compatible import OpenAICompatibleModelProvider as OpenAICompatibleModelProvider
    from sagents.v2.model.plugins.openai_responses import OpenAIResponsesConfig as OpenAIResponsesConfig
    from sagents.v2.model.plugins.openai_responses import OpenAIResponsesModelProvider as OpenAIResponsesModelProvider
    from sagents.v2.model.plugins.concurrency_budget import ModelConcurrencyBudget as ModelConcurrencyBudget
    from sagents.v2.model.middleware.recording import RecordingModelProvider as RecordingModelProvider
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider as ScriptedModelProvider
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep as ScriptedModelStep
    from sagents.v2.model.capability_probe import model_capability_profile as model_capability_profile
    from sagents.v2.model.protocols import model_protocol_descriptor as model_protocol_descriptor
    from sagents.v2.model.protocols import model_protocol_descriptors as model_protocol_descriptors
    from sagents.v2.model.protocols import model_protocol_implementation as model_protocol_implementation
    from sagents.v2.model.capability_probe import negotiate_model_output_limit as negotiate_model_output_limit
    from sagents.v2.model.capability_probe import probe_model_capabilities as probe_model_capabilities
    from sagents.v2.model.capability_probe import probe_model_connection as probe_model_connection
    from sagents.v2.model.capability_probe import probe_model_json_object as probe_model_json_object
    from sagents.v2.model.capability_probe import probe_model_multimodal as probe_model_multimodal
    from sagents.v2.model.capability_probe import probe_model_reasoning_controls as probe_model_reasoning_controls
    from sagents.v2.model.capability_probe import probe_model_tool_calling as probe_model_tool_calling
    from sagents.v2.model.protocols import resolve_model_protocol as resolve_model_protocol


from sagents.v2._lazy import exported_names, resolve_export


_CONTRACTS = "sagents.v2.model.contracts"
_CAPABILITIES = "sagents.v2.model.capability_contracts"
_PROBES = "sagents.v2.model.capability_probe"
_PROTOCOLS = "sagents.v2.model.protocols"
_EXPORTS = {
    "CanonicalTokenUsage": (
        "sagents.v2.model.plugins._shared.usage",
        "CanonicalTokenUsage",
    ),
    "canonical_token_usage": (
        "sagents.v2.model.plugins._shared.usage",
        "canonical_token_usage",
    ),
    "has_token_usage": (
        "sagents.v2.model.plugins._shared.usage",
        "has_token_usage",
    ),
    "GeminiGenerateContentConfig": (
        "sagents.v2.model.plugins.gemini_generate_content",
        "GeminiGenerateContentConfig",
    ),
    "GeminiGenerateContentModelProvider": (
        "sagents.v2.model.plugins.gemini_generate_content",
        "GeminiGenerateContentModelProvider",
    ),
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
    "ModelConcurrencyBudget": (
        "sagents.v2.model.plugins.concurrency_budget",
        "ModelConcurrencyBudget",
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

__all__ = [
    "CanonicalTokenUsage",
    "canonical_token_usage",
    "has_token_usage",
    "GeminiGenerateContentConfig",
    "GeminiGenerateContentModelProvider",
    "AnthropicMessagesConfig",
    "AnthropicMessagesModelProvider",
    "BuiltinModelProtocol",
    "ModelCapabilities",
    "ModelCapabilityProbeOutcome",
    "ModelCapabilityProbeReport",
    "ModelCapabilityProbeRequest",
    "ModelCapabilityProbeStatus",
    "ModelCapabilityProfile",
    "ModelEventKind",
    "ModelMessage",
    "ModelProtocolDescriptor",
    "ModelProvider",
    "ModelProviderRegistry",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelToolCall",
    "ModelToolDefinition",
    "OpenAIChatCompletionsConfig",
    "OpenAIChatCompletionsModelProvider",
    "OpenAICompatibleConfig",
    "OpenAICompatibleModelProvider",
    "OpenAIResponsesConfig",
    "OpenAIResponsesModelProvider",
    "ModelConcurrencyBudget",
    "RecordingModelProvider",
    "ScriptedModelProvider",
    "ScriptedModelStep",
    "model_capability_profile",
    "model_protocol_descriptor",
    "model_protocol_descriptors",
    "model_protocol_implementation",
    "negotiate_model_output_limit",
    "probe_model_capabilities",
    "probe_model_connection",
    "probe_model_json_object",
    "probe_model_multimodal",
    "probe_model_reasoning_controls",
    "probe_model_tool_calling",
    "resolve_model_protocol",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
