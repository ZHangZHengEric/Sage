"""Explicit model inputs shared by deterministic assembly and wire tests."""

from sagents.v2.model import ModelCapabilities

TEST_MODELS = {
    "models": {
        "primary": {
            "provider": "openai-chat-completions",
            "model": "test-model",
            "base_url": "https://gateway.invalid/v1",
            "credential": "model_api_key",
            "request": {"max_output_tokens": 8192},
            "limits": {"context_window": 128000, "max_output_tokens": 8192},
            "capabilities": {
                "tool_calling": True,
                "reasoning": True,
                "parallel_tool_calls": True,
            },
        }
    },
    "credentials": {"model_api_key": {"source": "env", "key": "SAGE_MODEL_API_KEY"}},
}


FULL_MODEL_CAPABILITIES = ModelCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_parallel_tool_calls=True,
    supports_reasoning=True,
    supports_multimodal_input=True,
    supports_structured_output=True,
    max_input_tokens=128_000,
    max_output_tokens=8_192,
)
