"""Offline CPU comparison; no model calls or production traffic.

Run from repository root with PYTHONPATH=. Uses frozen pre-fix test fixtures.
"""

import importlib.util
import json
import pathlib
import statistics
import time

from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from sagents.tool.impl.compress_history_tool import CompressHistoryTool
from sagents.utils.stream_merger import merge_chat_completion_chunks


def main():
    fixture = pathlib.Path("tests/sagents/utils/fixtures/latency_algorithms_before.py")
    spec = importlib.util.spec_from_file_location("latency_before", fixture)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)

    def compare(name, old, new, normalize=lambda x: x, reset=None):
        expected = normalize(old())
        assert normalize(new()) == expected
        values = {}
        for label, fn in [("before", old), ("after", new)]:
            samples = []
            for _ in range(3):
                if reset is not None:
                    reset()
                started = time.thread_time()
                value = fn()
                samples.append((time.thread_time() - started) * 1000)
                assert normalize(value) == expected
            values[label + "_cpu_ms"] = round(statistics.median(samples), 3)
        print("BENCH", name, json.dumps(values), flush=True)

    for tool in [False, True]:
        chunks = [
            ChatCompletionChunk.model_validate(
                {
                    "id": "mock",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "tool" if i == 0 else None,
                                            "arguments": "x" * 64,
                                        },
                                    }
                                ]
                            }
                            if tool
                            else {"content": "abc"},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            for i in range(5000)
        ]
        compare(
            "5000_tool_chunks" if tool else "5000_text_chunks",
            lambda: before.merge_chat_completion_chunks(chunks),
            lambda: merge_chat_completion_chunks(chunks),
            lambda x: x.model_dump(),
        )
    text = "".join(f"中文 abc {i:08x} 🙂 " for i in range(1200))
    from sagents.context.messages import token_accounting

    def cold_cache():
        with token_accounting._text_estimate_cache_lock:
            token_accounting._text_estimate_cache.clear()

    compare(
        "long_history_split",
        lambda: before.split_before(text, 256),
        lambda: CompressHistoryTool._split_compression_text_payload(text, 256),
        reset=cold_cache(),
    )
    original = CompressHistoryTool._estimated_text_tokens
    scans = []

    def counted(value):
        scans.append(len(value))
        return original(value)

    CompressHistoryTool._estimated_text_tokens = staticmethod(counted)
    try:
        before.split_before(text, 256)
        old_count, old_chars = len(scans), sum(scans)
        scans.clear()
        CompressHistoryTool._split_compression_text_payload(text, 256)
        print(
            "SCANS",
            json.dumps(
                {
                    "before_calls": old_count,
                    "after_calls": len(scans),
                    "before_chars": old_chars,
                    "after_chars": sum(scans),
                }
            ),
        )
    finally:
        CompressHistoryTool._estimated_text_tokens = staticmethod(original)


if __name__ == "__main__":
    main()
