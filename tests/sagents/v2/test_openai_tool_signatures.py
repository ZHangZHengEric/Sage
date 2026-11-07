from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING, cast

import httpx
import pytest
from openai import AsyncOpenAI

from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.provider_state import make_provider_state
from sagents.v2.model import ModelMessage, ModelToolCall, OpenAICompatibleModelProvider
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.tool import SideEffectLevel, ToolDefinition, ToolExecutionResult
from tests.sagents.v2.test_openai_compatible_model_matrix import (
    FakeClient,
    FakeCompletions,
    FakeStream,
    chunk,
    config,
    request,
)
from tests.sagents.v2.test_session_history_context_matrix import (
    CONTEXT,
    command,
    execute,
)

if TYPE_CHECKING:
    from sagents.v2.runtime.session.contracts import SessionStore


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("with_text", [False, True])
async def test_historical_memory_pruning_preserves_signed_tool_group(parallel, with_text):
    calls = (ModelToolCall(tool_call_id="memory", name="search_memory", arguments={}),)
    if parallel:
        calls += (ModelToolCall(tool_call_id="lookup", name="lookup", arguments={}),)
    assistant = ModelMessage(
        role="assistant",
        content=(TextBlock(text="Checking memory"),) if with_text else (),
        tool_calls=calls,
        provider_state=make_provider_state(
            "openai_compatible",
            {"tool_call_thought_signatures": {"memory": "opaque-signature"}},
        ),
    )
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="first question"),)),
        assistant,
        *(
            ModelMessage(
                role="tool",
                tool_call_id=call.tool_call_id,
                content=(TextBlock(text="result"),),
            )
            for call in calls
        ),
        ModelMessage(role="user", content=(TextBlock(text="follow up"),)),
    )
    positions: list[int] = []
    assert DefaultContextAssembler._strip_historical_search_memory(
        ledger, source_positions=positions
    ) == ledger
    assert positions == list(range(len(ledger)))
    prepared = await DefaultContextAssembler().prepare_messages(
        command("follow up", "signed-memory"), ledger
    )
    provider = OpenAICompatibleModelProvider(config(), client=object())
    wire = provider.diagnostic_request(request(messages=prepared))["messages"]
    replay = next(message for message in wire if message.get("tool_calls"))
    assert [call["id"] for call in replay["tool_calls"]] == [
        call.tool_call_id for call in calls
    ]
    assert replay["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "opaque-signature"}
    }
    assert [message["tool_call_id"] for message in wire if message["role"] == "tool"] == [
        call.tool_call_id for call in calls
    ]


def tool(index, call_id=None, arguments=None, signature=None):
    value: dict[str, Any] = {"index": index, "function": {}}
    if call_id is not None:
        value["id"] = call_id
        value["type"] = "function"
        value["function"]["name"] = "lookup"
    if arguments is not None:
        value["function"]["arguments"] = arguments
    if signature is not None:
        value["extra_content"] = {
            "google": {"thought_signature": signature, "unrelated": "discard"},
            "other_vendor": {"arbitrary": "discard"},
        }
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("cumulative", [False, True], ids=["fragmented", "cumulative"])
async def test_parallel_signatures_follow_final_call_ids_and_history_round_trip(
    cumulative,
):
    # Index 2 arrives first; only signed calls may gain extension fields on replay.
    final_delta = tool(
        0, arguments='{"q":"x"}' if cumulative else '"x"}', signature="sig-zero"
    )
    final_delta["id"] = "call_0" if cumulative else "0"
    stream = FakeStream(
        (
            chunk(tool_calls=(tool(2, "call_2", "{}", "sig-two"),)),
            chunk(tool_calls=(tool(0, "call_", '{"q":', "sig-zero"),)),
            chunk(
                tool_calls=(
                    final_delta,
                    tool(1, "call_1", "{}"),
                ),
                finish="tool_calls",
            ),
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )
    response = [event async for event in provider.stream(request())][-1].response
    assert response is not None
    history = ModelMessage(
        role="assistant",
        tool_calls=response.tool_calls,
        provider_state=response.provider_state,
    )
    restored = ModelMessage.model_validate_json(history.model_dump_json())
    calls = provider.diagnostic_request(request(messages=(restored,)))["messages"][0][
        "tool_calls"
    ]
    assert [call["id"] for call in calls] == ["call_0", "call_1", "call_2"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "x"}
    assert calls[0]["extra_content"] == {"google": {"thought_signature": "sig-zero"}}
    assert "extra_content" not in calls[1]
    assert calls[2]["extra_content"] == {"google": {"thought_signature": "sig-two"}}
    assert "discard" not in history.model_dump_json()
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("signature", ["", 42, {"nested": "invalid"}])
async def test_invalid_known_signature_is_rejected_before_completion(signature):
    stream = FakeStream(
        (chunk(tool_calls=(tool(0, "call_0", "{}", signature),), finish="tool_calls"),)
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )
    with pytest.raises(SageV2Error) as raised:
        _ = [event async for event in provider.stream(request())]
    assert raised.value.info.code == "model.provider_state_invalid"
    assert stream.closed


@pytest.mark.asyncio
async def test_signature_accumulation_is_bounded(monkeypatch):
    from sagents.v2.model.plugins import openai_compatible

    monkeypatch.setattr(
        openai_compatible, "MAX_PROVIDER_STATE_BYTES", 12, raising=False
    )
    stream = FakeStream(
        (
            chunk(
                tool_calls=(
                    tool(0, "call_0", "{}", "a" * 8),
                    tool(1, "call_1", "{}", "b" * 8),
                ),
                finish="tool_calls",
            ),
        )
    )
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )
    with pytest.raises(SageV2Error) as raised:
        _ = [event async for event in provider.stream(request())]
    assert raised.value.info.code == "model.provider_state_invalid"
    assert stream.closed


@pytest.mark.parametrize(
    "signatures", [[], {"other_call": "signature"}, {"call_0": 42}]
)
def test_invalid_replay_state_is_not_sent(signatures):
    provider = OpenAICompatibleModelProvider(config(), client=object())
    message = ModelMessage(
        role="assistant",
        tool_calls=(ModelToolCall(tool_call_id="call_0", name="lookup", arguments={}),),
        provider_state=make_provider_state(
            "openai_compatible", {"tool_call_thought_signatures": signatures}
        ),
    )
    with pytest.raises(SageV2Error) as raised:
        provider.diagnostic_request(request(messages=(message,)))
    assert raised.value.info.code == "model.provider_state_invalid"


@pytest.mark.asyncio
async def test_unrelated_tool_extensions_are_not_retained():
    call = tool(0, "call_0", "{}")
    call["extra_content"] = {"other_vendor": {"arbitrary": "discard"}}
    stream = FakeStream((chunk(tool_calls=(call,), finish="tool_calls"),))
    provider = OpenAICompatibleModelProvider(
        config(), client=FakeClient(FakeCompletions(stream=stream))
    )
    response = [event async for event in provider.stream(request())][-1].response
    assert response is not None
    assert response.provider_state == {}


@pytest.mark.asyncio
async def test_real_sdk_tool_round_trip_preserves_signature_after_session_restart(
    tmp_path,
):
    def wire(delta, finish=None):
        return {
            "id": "response",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gemini-test",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    batches = [
        [
            wire(
                {"tool_calls": [tool(0, "call_0", "{}", "opaque-signature")]},
                "tool_calls",
            )
        ],
        [wire({"content": "done"}, "stop")],
        [wire({"content": "remembered"}, "stop")],
    ]
    captured = []

    def handler(http_request):
        captured.append(json.loads(http_request.content))
        data = "".join(
            f"data: {json.dumps(event)}\n\n" for event in batches[len(captured) - 1]
        )
        return httpx.Response(
            200,
            text=data + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    client = AsyncOpenAI(
        api_key="placeholder",
        base_url="https://gemini.invalid/v1/",
        # OpenAI 3 accepts legacy httpx clients at runtime but annotates httpx2.
        # Keep this transport usable with the project's OpenAI 1+ dependency.
        http_client=cast(Any, httpx.AsyncClient(transport=httpx.MockTransport(handler))),
    )
    provider = OpenAICompatibleModelProvider(config(), client=client)
    definition = ToolDefinition(
        name="lookup",
        description="lookup",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )

    async def lookup(call, _context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="found"),),
        )

    path = tmp_path / "session"
    store = FilesystemSessionStore(path)
    runtime = HarnessRuntime(cast("SessionStore", store))
    try:
        first = await runtime.start_run(command("look up", "signed-first"), CONTEXT)
        await execute(
            runtime,
            first,
            provider,
            definitions=(definition,),
            handlers={"lookup": lookup},
        )
        assert len(captured) == 2
        call = next(
            message["tool_calls"][0]
            for message in captured[1]["messages"]
            if message.get("tool_calls")
        )
        assert call["extra_content"] == {
            "google": {"thought_signature": "opaque-signature"}
        }
        await store.close()
        store = FilesystemSessionStore(path)
        runtime = HarnessRuntime(cast("SessionStore", store))
        second = await runtime.start_run(
            command("follow up", "signed-second", session_id=first.session_id), CONTEXT
        )
        await execute(runtime, second, provider)
        restored = next(
            message["tool_calls"][0]
            for message in captured[2]["messages"]
            if message.get("tool_calls")
        )
        assert restored == call
    finally:
        await store.close()
        await client.close()
