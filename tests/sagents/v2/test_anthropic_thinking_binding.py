"""Wire-level regression coverage for thinking binding and durable replay."""

import copy

import pytest

from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    ModelMessage,
)
from tests.sagents.v2.test_builtin_model_protocols_matrix import (
    CAPABILITIES,
    FakeHTTPClient,
    request,
)


async def captured_turn(**config):
    transformations = [
        {
            "type": "thinking_dropped",
            "path": "messages.1.content.0",
            "reason": "prefix_binding_mismatch",
        }
    ]
    blocks = [
        {"type": "text", "text": "Before thinking"},
        {"type": "thinking", "thinking": "reason", "signature": "signed"},
        {"type": "redacted_thinking", "data": "opaque"},
        {
            "type": "tool_use",
            "id": "question",
            "name": "lookup",
            "input": {"q": "question"},
        },
    ]
    client = FakeHTTPClient(
        (
            {
                "type": "message_start",
                "message": {"id": "response", "input_transformations": transformations},
            },
            *(
                {"type": "content_block_start", "index": index, "content_block": block}
                for index, block in enumerate(blocks)
            ),
            {"type": "message_stop"},
        )
    )
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(model="test", capabilities=CAPABILITIES, **config),
        client=client,
    )
    events = [event async for event in provider.stream(request())]
    response = events[-1].response
    assistant = ModelMessage(
        role="assistant",
        tool_calls=response.tool_calls,
        provider_state=response.provider_state,
    )
    reply = ModelMessage(
        role="tool", tool_call_id="question", content=(TextBlock(text="answer"),)
    )
    return provider, response, assistant, reply, blocks, transformations


@pytest.mark.asyncio
async def test_order_and_transformations_survive_restart():
    (
        provider,
        response,
        assistant,
        reply,
        blocks,
        transformations,
    ) = await captured_turn()
    restarted = AnthropicMessagesModelProvider(
        provider.config, client=FakeHTTPClient(())
    )
    wire = restarted.diagnostic_request(
        request(run_id="new-run", messages=(*request().messages, assistant, reply))
    )
    assert wire["messages"][-2]["content"] == blocks
    assert response.provider_metadata["input_transformations"] == transformations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["compression", "questionnaire", "sandbox", "system", "tools", "child_agent"],
)
async def test_changed_prefix_drops_only_thinking(change):
    provider, _, assistant, reply, _, _ = await captured_turn()
    messages = list(request().messages)
    changes = {}
    if change in {"sandbox", "system", "child_agent"}:
        messages[0] = ModelMessage(role="system", content=(TextBlock(text=change),))
    elif change == "compression":
        messages = [
            messages[0],
            ModelMessage(role="user", content=(TextBlock(text="summary"),)),
        ]
    elif change == "questionnaire":
        messages[1] = ModelMessage(
            role="user", content=(TextBlock(text="original user text"),)
        )
    else:
        changes["tools"] = ()
    original = copy.deepcopy(assistant.provider_state)
    wire = provider.diagnostic_request(
        request(messages=(*messages, assistant, reply), **changes)
    )
    assert [block["type"] for block in wire["messages"][-2]["content"]] == [
        "text",
        "tool_use",
    ]
    assert wire["messages"][-1]["content"][0]["tool_use_id"] == "question"
    assert assistant.provider_state == original
    # A separate agent's request cannot poison the first agent's history.
    unchanged = provider.diagnostic_request(
        request(messages=(*request().messages, assistant, reply))
    )
    assert unchanged["messages"][-2]["content"][1]["signature"] == "signed"


@pytest.mark.asyncio
async def test_beta_merges_and_server_controls_legacy_or_changed_history():
    provider, _, assistant, reply, blocks, _ = await captured_turn(
        reasoning_effort="high",
        thinking_prefix_mismatch_behavior="drop_block",
        extra_headers={
            "Anthropic-Beta": "other-beta,thinking-binding-controls-2026-08-01"
        },
        extra_body={"thinking": {"display": "omitted"}},
    )
    wire = provider.diagnostic_request(
        request(
            messages=(
                ModelMessage(role="user", content=(TextBlock(text="summary"),)),
                assistant,
                reply,
            )
        )
    )
    assert wire["thinking"] == {
        "type": "adaptive",
        "display": "omitted",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert wire["messages"][1]["content"] == blocks
    assert provider.raw_client.calls[0][2]["headers"] == {
        "anthropic-beta": "other-beta,thinking-binding-controls-2026-08-01"
    }
    assert provider.config.extra_body == {"thinking": {"display": "omitted"}}


def test_partial_extra_body_thinking_merges_with_native_defaults():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(
            model="test",
            capabilities=CAPABILITIES,
            reasoning_effort="high",
            extra_headers={"anthropic-beta": "existing"},
            extra_body={
                "thinking": {
                    "block_binding": {"prefix_mismatch_behavior": "drop_block"}
                }
            },
        ),
        client=FakeHTTPClient(()),
    )
    payload = provider.diagnostic_request(request())
    assert payload["thinking"]["type"] == "adaptive"
    assert payload["thinking"]["display"] == "summarized"
    assert (
        payload["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    )
    assert (
        provider.request_headers()["anthropic-beta"]
        == "existing,thinking-binding-controls-2026-08-01"
    )


@pytest.mark.asyncio
async def test_first_mismatch_removes_all_later_thinking():
    provider, _, assistant, reply, _, _ = await captured_turn()
    first_messages = (*request().messages, assistant, reply)
    events = [
        event async for event in provider.stream(request(messages=first_messages))
    ]
    second = ModelMessage(
        role="assistant", provider_state=events[-1].response.provider_state
    )
    # A compaction changes the first response's prefix; neither signed response
    # can survive, but both tool calls and results must remain.
    wire = provider.diagnostic_request(
        request(messages=(*first_messages[1:], second, reply))
    )
    assert not any(
        block["type"] in {"thinking", "redacted_thinking"}
        for message in wire["messages"]
        for block in message["content"]
    )
    assert (
        sum(
            block["type"] == "tool_use"
            for message in wire["messages"]
            for block in message["content"]
        )
        == 3
    )
