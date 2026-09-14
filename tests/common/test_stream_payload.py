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
