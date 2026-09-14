import json
from unittest.mock import patch
import pytest
from common.utils.stream_payload import (
    should_filter_stream_payload,
    should_filter_stream_chunk,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "hidden", "content": "中文🙂" * 100},
        {"type": "assistant_text", "content": "x"},
        {"content": "without type"},
        {"type": None},
        {"type": 123},
        {"type": ("a", "b")},
        {"type": ["a"]},
        {"type": {"nested": "type"}},
    ],
)
def test_structured_filter_matches_json_wire_rules(payload):
    raw = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        expected = should_filter_stream_chunk(raw, {"hidden"})
    except TypeError:
        with pytest.raises(TypeError):
            should_filter_stream_payload(payload, {"hidden"})
    else:
        assert should_filter_stream_payload(payload, {"hidden"}) == expected
        if type(payload.get("type")) in (str, type(None)):
            with patch(
                "common.utils.stream_payload.json.loads",
                side_effect=AssertionError("reparse"),
            ):
                assert should_filter_stream_payload(payload, {"hidden"}) == expected
    assert should_filter_stream_payload(payload, None) is False


@pytest.mark.parametrize(
    "raw", ["broken", "{}", "[1,2]", "null", '{"type":"hidden"}', b'{"type":"hidden"}']
)
def test_resume_strings_keep_fallback(raw):
    try:
        parsed = json.loads(raw)
        expected = isinstance(parsed, dict) and parsed.get("type") == "hidden"
    except Exception:
        expected = False
    assert should_filter_stream_chunk(raw, {"hidden"}) == expected


@pytest.mark.asyncio
async def test_large_encoding_runs_in_worker_and_small_events_stay_light(monkeypatch):
    import threading
    from common.utils import stream_payload

    loop_thread = threading.get_ident()
    original = json.dumps
    calls = []

    def observed(*args, **kwargs):
        calls.append(threading.get_ident())
        return original(*args, **kwargs)

    payloads = [
        ({"type": "assistant_text", "content": "small"}, False),
        ({"type": "assistant_text", "content": "中文🙂" * 20000}, True),
        ({"type": "tool_call_result", "content": {"items": list(range(200))}}, True),
    ]
    monkeypatch.setattr(stream_payload.json, "dumps", observed)
    for payload, background in payloads:
        calls.clear()
        encoded = await stream_payload.encode_stream_payload(payload)
        assert calls and (calls[0] != loop_thread) is background
        assert encoded == original(payload, ensure_ascii=False) + "\n"


@pytest.mark.asyncio
async def test_large_encoder_does_not_block_event_loop(monkeypatch):
    import asyncio
    import threading
    from common.utils import stream_payload

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    original = json.dumps

    def observed(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(1), "encoder blocked the event loop"
        return original(*args, **kwargs)

    monkeypatch.setattr(stream_payload.json, "dumps", observed)
    task = asyncio.create_task(
        stream_payload.encode_stream_payload({"content": "x" * 20000})
    )
    await asyncio.wait_for(started.wait(), 2)
    release.set()
    assert json.loads(await task)["content"] == "x" * 20000


@pytest.mark.asyncio
async def test_cyclic_payload_raises_original_error_without_unbounded_inspection():
    from common.utils.stream_payload import (
        encode_stream_payload,
        _needs_background_encoding,
    )

    payload = {}
    payload["self"] = payload
    assert _needs_background_encoding(payload)
    with pytest.raises(ValueError, match="Circular reference"):
        await encode_stream_payload(payload)
