"""Exercise all native SSE readers through the public model-route factory."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelEventKind, ModelMessage, ModelToolCall
from sagents.v2.model.plugins._shared.stream_idle import StreamIdleTimeout
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.package.manifest.models import ModelRoute
from tests.sagents.v2.test_builtin_model_protocols_matrix import request


@pytest.mark.asyncio
async def test_idle_budget_excludes_slow_downstream_processing():
    timeout = 0.05
    idle = StreamIdleTimeout(timeout, provider="test")

    async def upstream():
        for event in ("text", "tool arguments", "finish"):
            yield event

    received = []
    async for event in idle.iterate(upstream()):
        received.append(event)
        if event == "finish":
            idle.finish()
        else:
            idle.progress()
        await asyncio.sleep(2 * timeout)

    assert received == ["text", "tool arguments", "finish"]


@pytest.mark.asyncio
async def test_idle_budget_accumulates_heartbeat_reads_across_downstream_pauses():
    timeout = 0.12
    idle = StreamIdleTimeout(timeout, provider="test")

    async def upstream():
        for _ in range(12):
            await asyncio.sleep(0.035)
            yield "heartbeat"

    received = []
    with pytest.raises(SageV2Error) as caught:
        async for event in idle.iterate(upstream()):
            received.append(event)
            await asyncio.sleep(1.1 * timeout)

    assert 2 <= len(received) < 12
    assert caught.value.info.code == "model.stream_idle_timeout"
    assert caught.value.info.metadata["stream_idle_phase"] == "first_chunk"


def _frames(protocol):
    fragments = ('{"q":', '"', "a", "b", "c", "d", "e", "f", '"', "}")
    if protocol == "anthropic-messages":

        def delta(value):
            return {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": value},
            }

        start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "call_1",
                "name": "lookup",
                "input": {},
            },
        }
        return (
            [start, *map(delta, fragments)],
            delta(""),
            [
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ],
        )
    if protocol == "openai-responses":

        def delta(value):
            return {
                "type": "response.function_call_arguments.delta",
                "item_id": "item_1",
                "delta": value,
            }

        start = {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "id": "item_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "",
            },
        }
        return (
            [start, *map(delta, fragments)],
            delta(""),
            [
                {
                    "type": "response.completed",
                    "response": {"id": "response_1", "status": "completed"},
                },
            ],
        )

    def candidate(parts, **fields):
        return {"candidates": [{"index": 0, "content": {"parts": parts}, **fields}]}

    call = {"functionCall": {"id": "call_1", "name": "lookup", "args": {"q": "abcdef"}}}
    return (
        [candidate([{"text": token, "thought": True}]) for token in "working on it"],
        candidate([{"text": ""}]),
        [
            candidate([call], finishReason="STOP"),
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol", ["anthropic-messages", "openai-responses", "gemini-generate-content"]
)
@pytest.mark.parametrize("phase", ["complete", "first_chunk", "mid_stream"])
async def test_other_protocols_time_model_progress_not_sse_heartbeats(protocol, phase):
    # Allow the first SDK read to initialize its event schemas on a cold run.
    timeout = 0.4
    interval = 0.05
    progress, empty, terminal = _frames(protocol)
    if protocol == "gemini-generate-content":
        call_before_finish = dict(terminal[0]["candidates"][0])
        call_before_finish.pop("finishReason")
        before_idle = [{"candidates": [call_before_finish]}]
    else:
        before_idle = progress[:1]
    base_url = "https://example.invalid/v1"

    class Body(httpx.AsyncByteStream):
        closed = False
        heartbeat_count = 0

        async def __aiter__(self):
            for frame in (
                progress
                if phase == "complete"
                else before_idle
                if phase == "mid_stream"
                else ()
            ):
                await asyncio.sleep(interval)
                yield encode(frame)
            if phase == "complete":
                for frame in terminal:
                    yield encode(frame)
                return
            for _ in range(30):
                await asyncio.sleep(interval)
                self.heartbeat_count += 1
                yield b": keepalive\n\n"
                yield encode(empty)

        async def aclose(self):
            self.closed = True

    def encode(frame):
        return b"data: " + json.dumps(frame).encode() + b"\n\n"

    body = Body()

    def respond(wire):
        assert "stream_idle_timeout_seconds" not in json.loads(wire.content)
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=body
        )

    route = ModelRoute.model_validate(
        {
            "provider": protocol,
            "model": "model-test",
            "base_url": base_url,
            "request": {"extra": {"stream_idle_timeout_seconds": timeout}},
        }
    )
    async with httpx.AsyncClient(
        base_url=base_url, transport=httpx.MockTransport(respond)
    ) as http_client:
        client = (
            AsyncOpenAI(
                api_key="test",
                base_url=base_url,
                max_retries=0,
                http_client=http_client,
            )
            if protocol == "openai-responses"
            else http_client
        )
        provider = create_registered_model_provider(route, client=client)
        model_request = request(
            messages=(
                ModelMessage(
                    role="user", content=(TextBlock(text="Look up the value"),)
                ),
            )
        )
        events = []
        start = asyncio.get_running_loop().time()
        if phase == "complete":
            events = [event async for event in provider.stream(model_request)]
            assert asyncio.get_running_loop().time() - start > timeout
            assert events[-1].kind == ModelEventKind.COMPLETED
            assert events[-1].response is not None
            assert events[-1].response.tool_calls == (
                ModelToolCall(
                    tool_call_id="call_1", name="lookup", arguments={"q": "abcdef"}
                ),
            )
        else:
            with pytest.raises(SageV2Error) as caught:
                async for event in provider.stream(model_request):
                    events.append(event)
            info = caught.value.info
            assert info.code == "model.stream_idle_timeout"
            assert info.retryable and info.safe_to_resume
            assert info.metadata["stream_idle_phase"] == phase
            failure = info.metadata["model_failure"]
            assert failure["kind"] == "stream"
            assert failure["response_started"] is (phase == "mid_stream")
            assert failure["has_tool_calls"] is (phase == "mid_stream")
            assert 0 < body.heartbeat_count < 30
            assert all(event.kind != ModelEventKind.COMPLETED for event in events)
    assert body.closed
