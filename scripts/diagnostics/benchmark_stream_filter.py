"""Offline wire-equivalence and CPU replay; no provider/network requests."""

import gc
import json
import statistics
import time

from common.utils.stream_payload import (
    should_filter_stream_payload,
    should_filter_stream_chunk,
)
from openai.types.chat import ChatCompletionChunk


def median_cpu(fn):
    values = []
    for _ in range(5):
        started = time.thread_time()
        fn()
        values.append((time.thread_time() - started) * 1000)
    return round(statistics.median(values), 3)


def main():
    for size, count in [(32, 5600), (32768, 500)]:
        payload = {"type": "assistant_text", "content": "中文🙂" * size}

        def before():
            for _ in range(count):
                encoded = json.dumps(payload, ensure_ascii=False) + "\n"
                assert not should_filter_stream_chunk(encoded, {"hidden"})

        def after():
            for _ in range(count):
                assert not should_filter_stream_payload(payload, {"hidden"})
                encoded = json.dumps(payload, ensure_ascii=False) + "\n"

        print(
            "ENCODE_FILTER",
            json.dumps(
                {
                    "characters": len(payload["content"]),
                    "events": count,
                    "before_cpu_ms": median_cpu(before),
                    "after_cpu_ms": median_cpu(after),
                }
            ),
            flush=True,
        )
    data = {
        "id": "mock",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "mock",
        "choices": [{"index": 0, "delta": {"content": "你好"}, "finish_reason": None}],
    }
    samples = []
    gc_durations = []
    gc_start = []

    def callback(phase, info):
        if phase == "start":
            gc_start.append(time.perf_counter())
        elif gc_start:
            gc_durations.append((time.perf_counter() - gc_start.pop()) * 1000)

    gc.callbacks.append(callback)
    try:
        for _ in range(5600):
            start = time.perf_counter()
            result = ChatCompletionChunk.construct(**data)
            samples.append((time.perf_counter() - start) * 1000)
            assert result.choices[0].delta.content == "你好"
    finally:
        gc.callbacks.remove(callback)
    print(
        "SDK_CONSTRUCT",
        json.dumps(
            {
                "events": len(samples),
                "median_wall_ms": round(statistics.median(samples), 4),
                "max_wall_ms": round(max(samples), 3),
                "gc_count": len(gc_durations),
                "gc_max_ms": round(max(gc_durations, default=0), 3),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
