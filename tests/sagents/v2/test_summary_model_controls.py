from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sagents.v2.context import ContextReductionScope, ModelConversationSummarizer
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.model.plugins.openai_compatible import (
    OpenAIChatCompletionsModelProvider,
    OpenAICompatibleConfig,
)
from sagents.v2.model.plugins.openai_responses import (
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.model.plugins.anthropic_messages import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
)
from sagents.v2.model.plugins.gemini_generate_content import (
    GeminiGenerateContentConfig,
    GeminiGenerateContentModelProvider,
)
from sagents.v2.model.wire import minimum_reasoning_control

CAPS = ModelCapabilities(
    supports_streaming=True,
    supports_tools=True,
    supports_parallel_tool_calls=True,
    supports_reasoning=True,
    supports_multimodal_input=True,
    supports_structured_output=True,
    max_output_tokens=32768,
)


def request(**changes):
    return ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="summary",
        messages=(
            ModelMessage(role="developer", content=(TextBlock(text="hidden index"),)),
        ),
        **changes,
    )


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic", "gemini"])
def test_summary_overrides_high_reasoning_without_changing_primary_requests(protocol):
    configs = {
        "chat": (OpenAICompatibleConfig, OpenAIChatCompletionsModelProvider),
        "responses": (OpenAIResponsesConfig, OpenAIResponsesModelProvider),
        "anthropic": (AnthropicMessagesConfig, AnthropicMessagesModelProvider),
        "gemini": (GeminiGenerateContentConfig, GeminiGenerateContentModelProvider),
    }
    config_type, provider_type = configs[protocol]
    provider = provider_type(
        config_type(
            base_url="https://example.invalid",
            model="test",
            capabilities=CAPS,
            reasoning_effort="high",
        ),
        client=object(),
    )
    primary = provider.diagnostic_request(request())
    summary = provider.diagnostic_request(request(reasoning_mode="minimum"))
    if protocol == "chat":
        assert primary["messages"][0]["role"] == "system"
        assert summary["extra_body"]["reasoning_effort"] == "none"
        assert primary["extra_body"]["reasoning_effort"] == "high"
    elif protocol == "responses":
        assert summary["reasoning"]["effort"] == "none"
        assert primary["reasoning"]["effort"] == "high"
        assert primary["input"][0]["role"] == "developer"
    elif protocol == "anthropic":
        assert summary["thinking"] == {"type": "disabled"}
        assert primary["output_config"]["effort"] == "high"
    else:
        assert summary["generationConfig"]["thinkingConfig"] == {
            "includeThoughts": False,
            "thinkingLevel": "minimal",
        }
        assert primary["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"


@pytest.mark.parametrize(
    "strategy,expected",
    [
        (
            {"reasoning_disable_strategy": "thinking_type_disabled"},
            ("thinking_type_disabled", None),
        ),
        (
            {"reasoning_behavior": "none", "supported_reasoning_efforts": ["low"]},
            ("omit", None),
        ),
        (
            {
                "reasoning_behavior": "always",
                "supported_reasoning_efforts": ["high", "low", "minimal"],
            },
            ("reasoning_effort", "minimal"),
        ),
    ],
)
def test_minimum_reasoning_uses_verified_disable_or_lowest_supported_effort(
    strategy, expected
):
    assert (
        minimum_reasoning_control(strategy, default_disable="reasoning_effort_none")
        == expected
    )


def test_chat_summary_uses_probed_disable_dialect_over_configured_high_controls():
    provider = OpenAIChatCompletionsModelProvider(
        OpenAICompatibleConfig(
            base_url="https://example.invalid",
            model="test",
            capabilities=CAPS,
            reasoning_effort="high",
            extra_body={"enable_thinking": True},
            invocation_strategy={
                "reasoning_disable_strategy": "thinking_type_disabled"
            },
        ),
        client=object(),
    )
    assert provider.diagnostic_request(request(reasoning_mode="minimum"))[
        "extra_body"
    ] == {
        "thinking": {"type": "disabled"},
    }


@pytest.mark.asyncio
async def test_summary_retries_truncation_with_larger_allowance_and_minimum_reasoning():
    payload = {
        "summary": "verified",
        **{
            k: []
            for k in (
                "decisions",
                "open_tasks",
                "files_touched",
                "commands_run",
                "important_errors",
                "user_requirements",
            )
        },
    }

    def completion(reason):
        return ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id="response_1",
                text=json.dumps(payload),
                finish_reason=reason,
            ),
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completion("max_output_tokens"),)),
            ScriptedModelStep(events=(completion("completed"),)),
        ),
        capabilities=CAPS,
    )
    value = await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(
            scope=ContextReductionScope(
                context_key="context_1",
                session_id="session_1",
                run_id="run_1",
                source_sequence=1,
            ),
            messages=request().messages,
            target_tokens=4096,
        )
    )
    assert json.loads(value) == payload
    assert [r.max_output_tokens for r in model.requests] == [8192, 16384]
    assert all(r.reasoning_mode == "minimum" for r in model.requests)


@pytest.mark.asyncio
async def test_responses_invalid_tool_arguments_preserve_terminal_diagnostics():
    class Stream:
        async def __aiter__(self):
            yield {
                "type": "response.incomplete",
                "response": {
                    "id": "response_1",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {"input_tokens": 10, "output_tokens": 8192},
                    "output": [
                        {
                            "type": "function_call",
                            "id": "item_1",
                            "call_id": "call_1",
                            "name": "file_write",
                            "arguments": '{"content":"partial',
                        }
                    ],
                },
            }

        async def close(self):
            pass

    class Responses:
        async def create(self, **kwargs):
            return Stream()

    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(
            model="test",
            capabilities=CAPS,
        ),
        client=SimpleNamespace(responses=Responses()),
    )
    with pytest.raises(SageV2Error) as caught:
        _ = [event async for event in provider.stream(request())]
    metadata = caught.value.info.metadata
    assert metadata["finish_reason"] == "max_output_tokens"
    assert metadata["tool_name"] == "file_write"
    assert metadata["raw_arguments"] == '{"content":"partial'
    assert metadata["usage"]["output_tokens"] == 8192


def test_responses_summary_uses_lowest_probed_effort_when_reasoning_is_mandatory():
    profile = SimpleNamespace(
        effective_max_output_tokens=16384,
        invocation_strategy={
            "reasoning_disable_strategy": "omit",
            "reasoning_behavior": "always",
            "supported_reasoning_efforts": ["high", "low"],
            "reasoning_effort_strategy": "reasoning_effort",
        },
    )
    config = OpenAIResponsesModelProvider.apply_capability_profile(
        OpenAIResponsesConfig(
            model="test",
            capabilities=CAPS,
            reasoning_effort="high",
        ),
        profile,
    )
    provider = OpenAIResponsesModelProvider(config, client=object())
    assert provider.diagnostic_request(request(reasoning_mode="minimum"))[
        "reasoning"
    ] == {"effort": "low"}


@pytest.mark.asyncio
async def test_summary_output_allowance_respects_model_limit():
    payload = {
        "summary": "verified",
        **{
            k: []
            for k in (
                "decisions",
                "open_tasks",
                "files_touched",
                "commands_run",
                "important_errors",
                "user_requirements",
            )
        },
    }
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="response_1",
                            text=json.dumps(payload),
                            finish_reason="completed",
                        ),
                    ),
                )
            ),
        ),
        capabilities=CAPS.model_copy(update={"max_output_tokens": 2048}),
    )
    await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(
            scope=ContextReductionScope(
                context_key="context_1",
                session_id="session_1",
                run_id="run_1",
                source_sequence=1,
            ),
            messages=request().messages,
            target_tokens=4096,
        )
    )
    assert model.requests[0].max_output_tokens == 2048
