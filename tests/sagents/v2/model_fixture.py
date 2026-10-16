"""Explicit App model directory shared by deterministic assembly tests."""
TEST_MODELS = {
    "models": {"primary": {
        "provider": "openai-chat-completions", "model": "test-model",
        "base_url": "https://gateway.invalid/v1", "credential": "model_api_key",
        "request": {"max_output_tokens": 8192},
        "limits": {"context_window": 128000, "max_output_tokens": 8192},
        "capabilities": {"tool_calling": True, "reasoning": True, "parallel_tool_calls": True},
    }},
    "credentials": {"model_api_key": {"source": "env", "key": "SAGE_MODEL_API_KEY"}},
}
