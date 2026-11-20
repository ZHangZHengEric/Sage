"""Responses reasoning stays separate from answers in both wire dialects."""

from types import SimpleNamespace

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import (
    ModelEventKind,
    ModelMessage,
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.contracts.provider_state import read_provider_state
from tests.sagents.v2.test_builtin_model_protocols_matrix import (
    CAPABILITIES,
    FakeAsyncStream,
    FakeResponses,
    request,
)


@pytest.mark.parametrize("with_tool", [False, True])
@pytest.mark.parametrize(
    "summary,content,delta_type",
    [
        ("Check the workspace.", None, "response.reasoning_summary_text.delta"),
        ("Check the workspace.", "Check the workspace.", "response.reasoning_summary_text.delta"),
        ("Check the workspace.", "Detailed workspace analysis.", "response.reasoning_summary_text.delta"),
        (None, "Check the workspace.", "response.reasoning_text.delta"),
        ("Check the workspace.", None, None),
        (None, "Check the workspace.", None),
    ],
)
async def test_reasoning_dialects_preserve_display_text_and_continuation(
    summary, content, delta_type, with_tool
):
    thinking = summary or content
    reasoning_item = {
        "type": "reasoning",
        "id": "reasoning_1",
        "summary": [{"type": "summary_text", "text": summary}] if summary else [],
        "content": [{"type": "reasoning_text", "text": content}] if content else None,
        "encrypted_content": "opaque-state" if content is None else None,
        "status": "completed",
    }
    output = [reasoning_item]
    if with_tool:
        output.append({
            "type": "function_call", "id": "tool_1", "call_id": "call_1",
            "name": "list_dir", "arguments": '{"path":"."}',
        })
    else:
        output.append({
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "The answer."}],
        })
    wire_events = [{"type": "response.output_item.added", "item": reasoning_item}]
    if delta_type:
        wire_events.extend(
            {"type": delta_type, "item_id": reasoning_item["id"], "delta": part}
            for part in (thinking[:6], thinking[6:])
        )
    wire_events.append({
        "type": "response.completed",
        "response": {"id": "response_1", "status": "completed", "output": output},
    })
    stream = FakeAsyncStream(wire_events)
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="fixture", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(stream)),
    )
    events = [event async for event in provider.stream(request(
        messages=(ModelMessage(role="user", content=(TextBlock(text="Check."),)),),
        tools=(),
    ))]

    response = events[-1].response
    assert response is not None
    assert response.reasoning == thinking
    assert "".join(event.delta for event in events if event.kind == ModelEventKind.REASONING_DELTA) == thinking
    assert response.text == ("" if with_tool else "The answer.")
    assert [call.name for call in response.tool_calls] == (["list_dir"] if with_tool else [])
    assert stream.closed
    saved = read_provider_state(response.provider_state, "openai_responses")["reasoning_items"][0]
    assert saved["summary"] == reasoning_item["summary"]
    if content:
        assert saved["content"] == reasoning_item["content"]
    if content is None:
        assert saved["encrypted_content"] == "opaque-state"
    replay = provider.diagnostic_request(request(messages=(
        ModelMessage(role="assistant", provider_state=response.provider_state),
    ), tools=()))
    assert replay["input"][0] == saved


@pytest.mark.parametrize(
    ("field", "block_type"), [("summary", "summary_text"), ("content", "reasoning_text")]
)
async def test_final_reasoning_fills_only_items_without_streamed_deltas(field, block_type):
    streamed = {
        "type": "reasoning",
        "id": "rs_streamed",
        "summary": [{"type": "summary_text", "text": "First. "}],
    }
    final_only = {
        "type": "reasoning",
        "id": "rs_final",
        "summary": [],
        field: [{"type": block_type, "text": "Second."}],
        "encrypted_content": "opaque-state",
    }
    stream = FakeAsyncStream([
        {"type": "response.reasoning_summary_text.delta", "item_id": streamed["id"], "delta": "First. "},
        {"type": "response.output_item.done", "item": final_only},
        {"type": "response.completed", "response": {
            "id": "response_1",
            "status": "completed",
            "output": [streamed, final_only, {
                "type": "message", "content": [{"type": "output_text", "text": "Done."}],
            }],
        }},
    ])
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="fixture", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(stream)),
    )
    events = [event async for event in provider.stream(request(messages=(), tools=()))]

    assert [event.delta for event in events if event.kind == ModelEventKind.REASONING_DELTA] == [
        "First. ", "Second.",
    ]
    response = events[-1].response
    assert response is not None
    assert response.reasoning == "First. Second."
    assert response.text == "Done."
    state = read_provider_state(response.provider_state, "openai_responses")
    assert {item["id"]: item for item in state["reasoning_items"]} == {
        streamed["id"]: streamed, final_only["id"]: final_only,
    }


async def test_unknown_message_content_is_still_rejected():
    stream = FakeAsyncStream([{
        "type": "response.completed",
        "response": {
            "id": "response_1", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "unknown"}]}],
        },
    }])
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="fixture", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(stream)),
    )
    with pytest.raises(SageV2Error) as error:
        _ = [event async for event in provider.stream(request(
            messages=(ModelMessage(role="user", content=(TextBlock(text="Check."),)),),
            tools=(),
        ))]
    assert error.value.info.code == "model.response_unsupported"
    assert stream.closed


@pytest.mark.parametrize("source", ["final", "streamed", "delta_without_id", "item_without_id"])
async def test_reasoning_reaches_agui_display_once(source):
    from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
    from sagents.v2.contracts.items import ReasoningItemData
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, RunState, setup_loop

    thinking = "Check the workspace before answering."
    streamed = source != "final"
    wire_events = []
    if streamed:
        wire_events.append({
            "type": "response.reasoning_summary_text.delta",
            "delta": thinking,
            **({"item_id": "reasoning_1"} if source != "delta_without_id" else {}),
        })
    wire_events.append({
        "type": "response.completed",
        "response": {
            "id": "response_1", "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    **({"id": "reasoning_1"} if source != "item_without_id" else {}),
                    "summary": [{"type": "summary_text", "text": thinking}] if streamed else [],
                    "content": [{"type": "reasoning_text", "text": thinking}],
                },
                {"type": "message", "content": [{"type": "output_text", "text": "Done."}]},
            ],
        },
    })
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="fixture", capabilities=CAPABILITIES),
        client=SimpleNamespace(responses=FakeResponses(FakeAsyncStream(wire_events))),
    )
    runtime, handle, loop, _ = await setup_loop(provider, tools=())
    result = await loop.execute(handle.run_id, CONTEXT)
    runtime_events = await runtime.session_store.read_events(handle.run_id)

    assert result.state == RunState.COMPLETED
    completed = [event.data.item for event in runtime_events if event.type == "reasoning.completed"]
    assert len(completed) == 1
    assert isinstance(completed[0].data, ReasoningItemData)
    assert completed[0].data.content[0].text == thinking
    adapter = AgUiProtocolAdapter()
    frames = [frame for event in runtime_events for frame in adapter.translate(event).frames]
    assert "".join(frame.payload["delta"] for frame in frames if frame.name == "REASONING_MESSAGE_CONTENT") == thinking
    assistant_ids = {
        frame.payload["messageId"] for frame in frames
        if frame.name == "TEXT_MESSAGE_START" and frame.payload["role"] == "assistant"
    }
    assert "".join(
        frame.payload["delta"] for frame in frames
        if frame.name == "TEXT_MESSAGE_CONTENT" and frame.payload["messageId"] in assistant_ids
    ) == "Done."
