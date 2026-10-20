from __future__ import annotations

from tests.sagents.v2.model_fixture import FULL_MODEL_CAPABILITIES as CAPABILITIES

import json

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.context import (
    DefaultContextAssembler,
    RunMetadataContextProvider,
)
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    ModelRequest,
    ModelToolDefinition,
    OpenAIChatCompletionsConfig,
    OpenAIChatCompletionsModelProvider,
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)


class _UnusedClient:
    pass


async def normalized_request() -> ModelRequest:
    command = StartRun(
        agent_id="agent_1",
        input=(
            InputItem(
                role="user",
                content=(
                    TextBlock(text="inspect this"),
                    ImageBlock(
                        uri="https://example.invalid/input.png",
                        mime_type="image/png",
                    ),
                ),
            ),
        ),
        config={
            "metadata": {
                "response_language": "zh-CN",
                "identity_documents": {"SOUL": "Be exact."},
                "system_context": {"session_id": "session_1"},
                "working_directory": "/workspace/project",
                "current_time": "2026-08-28T12:00:00+08:00",
            }
        },
        resolved_spec_hash="sha256:spec",
        idempotency_key="start_1",
    )
    assembler = DefaultContextAssembler(
        developer_instructions="Use tools only when needed.",
        providers=(RunMetadataContextProvider(),),
    )
    messages = await assembler.prepare_messages(
        command, await assembler.initial_ledger(command)
    )
    return ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="primary",
        messages=messages,
        tools=(
            ModelToolDefinition(
                name="lookup",
                description="Look up a value.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                strict=True,
            ),
        ),
        max_output_tokens=512,
    )


@pytest.mark.asyncio
async def test_three_protocol_payload_golden_preserves_prompt_and_tool_semantics():
    request = await normalized_request()
    chat = OpenAIChatCompletionsModelProvider(
        OpenAIChatCompletionsConfig(
            model="gpt-test",
            base_url="https://example.invalid/v1",
            capabilities=CAPABILITIES,
        ),
        client=_UnusedClient(),
    ).diagnostic_request(request)
    responses = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="gpt-test", capabilities=CAPABILITIES),
        client=_UnusedClient(),
    ).diagnostic_request(request)
    anthropic = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="claude-test", capabilities=CAPABILITIES),
        client=_UnusedClient(),
    ).diagnostic_request(request)

    assert "input" not in chat
    assert [value["role"] for value in chat["messages"]] == ["system", "user"]
    # This contract belongs to the protocol boundary: preserve the assembled
    # prompt exactly. Locale wording is tested by the context/locale suites.
    expected_system = request.messages[0].content[0].text
    assert "Use tools only when needed." in expected_system
    assert "<soul>\nBe exact.\n</soul>" in expected_system
    assert chat["messages"][0]["content"] == expected_system
    assert chat["messages"][-1]["content"] == [
        {
            "type": "text",
            "text": (
                "<runtime_context>\n<system_context>\n"
                "  <current_time>2026-08-28T12:00:00+08:00</current_time>\n"
                "  <session_id>session_1</session_id>\n"
                "  <working_directory>/workspace/project</working_directory>\n"
                "</system_context>\n</runtime_context>"
                "\n\n<user_request>"
            ),
        },
        {"type": "text", "text": "inspect this"},
        {
            "type": "image_url",
            "image_url": {
                "url": "https://example.invalid/input.png",
                "detail": "auto",
            },
        },
        {"type": "text", "text": "</user_request>"},
    ]
    assert responses["input"][-1] == {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": chat["messages"][-1]["content"][0]["text"]},
            {"type": "input_text", "text": "inspect this"},
            {
                "type": "input_image",
                "image_url": "https://example.invalid/input.png",
                "detail": "auto",
            },
            {"type": "input_text", "text": "</user_request>"},
        ],
    }
    assert [value["text"] for value in anthropic["system"]] == [expected_system]
    assert (
        anthropic["messages"][-1]["content"][0]["text"]
        == chat["messages"][-1]["content"][0]["text"]
    )

    assert (
        chat["tools"][0]["function"]["parameters"]
        == responses["tools"][0]["parameters"]
    )
    assert anthropic["tools"][0]["input_schema"] == responses["tools"][0]["parameters"]
    assert chat["max_tokens"] == 512
    assert responses["max_output_tokens"] == 512
    assert anthropic["max_tokens"] == 512
    for payload in (chat, responses):
        assert "cache_control" not in json.dumps(payload, sort_keys=True)
    assert anthropic["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert anthropic["tools"][-1]["cache_control"] == {"type": "ephemeral"}
