"""Differential checks against the deployed algorithms, including provider extras."""

import importlib.util
from pathlib import Path
import random

import pytest
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from sagents.utils.stream_merger import merge_chat_completion_chunks
from sagents.tool.impl.compress_history_tool import (
    CompressHistoryTool,
    CompressHistoryError,
)

spec = importlib.util.spec_from_file_location(
    "latency_before",
    Path(__file__).parent / "fixtures" / "latency_algorithms_before.py",
)
before = importlib.util.module_from_spec(spec)
spec.loader.exec_module(before)


@pytest.mark.parametrize("seed", range(12))
def test_split_boundaries_identical(seed):
    rng = random.Random(seed)
    alphabet = [
        "中文",
        "hello ",
        "12345",
        "a" * 31,
        "a" * 32,
        '\\"',
        "\n",
        "🙂",
        "é",
        "\t",
        "_/+=-",
        " " * 10,
    ]
    text = "".join(rng.choice(alphabet) for _ in range(80))
    for limit in [0, 1, 16, 32, 64, 100, 256, 4096]:
        try:
            expected = before.split_before(text, limit)
        except CompressHistoryError:
            with pytest.raises(CompressHistoryError):
                CompressHistoryTool._split_compression_text_payload(text, limit)
        else:
            actual = CompressHistoryTool._split_compression_text_payload(text, limit)
            assert actual == expected
            assert "".join(actual) == text


def test_long_history_does_not_rescan_remaining_suffix(monkeypatch):
    text = "中文 abc 123 🙂 " * 1600
    original = CompressHistoryTool._estimated_text_tokens
    scanned = []

    def count(value):
        scanned.append(len(value))
        return original(value)

    monkeypatch.setattr(
        CompressHistoryTool, "_estimated_text_tokens", staticmethod(count)
    )
    expected = before.split_before(text, 256)
    old_scanned = sum(scanned)
    scanned.clear()
    actual = CompressHistoryTool._split_compression_text_payload(text, 256)
    assert actual == expected
    assert sum(scanned) < old_scanned / 3


@pytest.mark.parametrize("seed", range(12))
def test_merge_provider_extensions_tools_and_input_isolation(seed):
    rng = random.Random(seed)
    chunks = []
    for i in range(40):
        delta = {
            "content": rng.choice(["中文", "hello ", None]),
            "reasoning_content": rng.choice(["think", "", None]),
            "refusal": rng.choice(["no", None]),
            "provider_list": [{"i": i}],
            "provider_map": {str(i % 3): [i]},
            "provider_mixed": rng.choice(["text", ["item"], {"k": i}, None]),
            "tool_calls": [
                {
                    "index": i % 2,
                    "id": f"call{i % 2}" if i < 2 else None,
                    "function": {
                        "name": "tool" if i < 2 else None,
                        "arguments": str(i),
                    },
                }
            ],
        }
        chunks.append(
            ChatCompletionChunk.model_validate(
                {
                    "id": "id",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "provider_top": {"i": [i]},
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": "tool_calls" if i == 39 else None,
                            "provider_choice": {"i": i},
                        }
                    ],
                }
            )
        )
    chunks.append(
        ChatCompletionChunk.model_validate(
            {
                "id": "id",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "mock",
                "choices": [],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                    "provider_usage": [1],
                },
            }
        )
    )
    snapshots = [c.model_dump() for c in chunks]
    expected = before.merge_chat_completion_chunks(chunks).model_dump()
    result = merge_chat_completion_chunks(iter(chunks))
    assert result.model_dump() == expected
    result.choices[0].message.provider_list[0]["i"] = -999
    result.provider_top["i"].append(-1)
    assert [c.model_dump() for c in chunks] == snapshots


def test_empty_stream_unchanged():
    assert (
        merge_chat_completion_chunks([]).model_dump()
        == before.merge_chat_completion_chunks([]).model_dump()
    )


def test_custom_sdk_subclass_keeps_independent_serialization():
    from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

    class CustomDelta(ChoiceDelta):
        def model_dump(self, *args, **kwargs):
            result = super().model_dump(*args, **kwargs)
            result["custom_dump_field"] = "preserved"
            return result

    delta = CustomDelta(content="answer")
    chunk = ChatCompletionChunk(
        id="id",
        object="chat.completion.chunk",
        created=1,
        model="mock",
        choices=[Choice(index=0, delta=delta)],
    )
    expected = before.merge_chat_completion_chunks([chunk]).model_dump()
    result = merge_chat_completion_chunks([chunk]).model_dump()
    assert result == expected
    assert result["choices"][0]["message"]["custom_dump_field"] == "preserved"
