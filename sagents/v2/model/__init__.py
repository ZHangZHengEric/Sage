"""SAgents V2 module for model/__init__.py."""

from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ModelToolDefinition,
)
from sagents.v2.model.capability_probe import (
    ModelCapabilityProbeOutcome,
    ModelCapabilityProbeReport,
    ModelCapabilityProbeStatus,
    probe_model_capabilities,
    probe_model_connection,
    probe_model_json_object,
    probe_model_tool_calling,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.plugins.openai_compatible import (
    OpenAIChatCompletionsConfig,
    OpenAIChatCompletionsModelProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleModelProvider,
)
from sagents.v2.model.plugins.openai_responses import (
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.model.plugins.anthropic_messages import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
)
from sagents.v2.model.protocols import (
    BuiltinModelProtocol,
    ModelProtocolDescriptor,
    model_protocol_descriptor,
    model_protocol_descriptors,
    resolve_model_protocol,
)
from sagents.v2.model.registry import ModelProviderRegistry
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.model.middleware.recording import RecordingModelProvider

__all__ = [
    "ModelCapabilities",
    "ModelCapabilityProbeOutcome",
    "ModelCapabilityProbeReport",
    "ModelCapabilityProbeStatus",
    "ModelEventKind",
    "ModelMessage",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelToolCall",
    "ModelToolDefinition",
    "AnthropicMessagesConfig",
    "AnthropicMessagesModelProvider",
    "BuiltinModelProtocol",
    "ModelProviderRegistry",
    "ModelProtocolDescriptor",
    "model_protocol_descriptor",
    "model_protocol_descriptors",
    "resolve_model_protocol",
    "OpenAIChatCompletionsConfig",
    "OpenAIChatCompletionsModelProvider",
    "OpenAICompatibleConfig",
    "OpenAICompatibleModelProvider",
    "OpenAIResponsesConfig",
    "OpenAIResponsesModelProvider",
    "RecordingModelProvider",
    "probe_model_capabilities",
    "probe_model_connection",
    "probe_model_json_object",
    "probe_model_tool_calling",
    "ScriptedModelProvider",
    "ScriptedModelStep",
]
