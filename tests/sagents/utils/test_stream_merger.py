from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
)

from sagents.utils.serialization import make_serializable
from sagents.utils.stream_merger import merge_chat_completion_chunks


def _chunk(delta: ChoiceDelta, *, finish_reason=None, **extra):
    return ChatCompletionChunk(
        id="chunk-1",
        object="chat.completion.chunk",
        created=1,
        model="deepseek-v4-flash",
        choices=[
            Choice(
                index=0,
                delta=delta,
                finish_reason=finish_reason,
            )
        ],
        **extra,
    )


def test_stream_merger_preserves_reasoning_and_provider_fields() -> None:
    chunks = [
        _chunk(
            ChoiceDelta(reasoning_content="first "),
            system_fingerprint="fp-1",
            provider_trace={"trace_id": "trace-1"},
        ),
        _chunk(ChoiceDelta(reasoning_content="second")),
        ChatCompletionChunk.model_validate(
            {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"query":',
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": "answer",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '"value"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        ),
        ChatCompletionChunk.model_validate(
            {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 6,
                    "total_tokens": 16,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                    "prompt_cache_hit_tokens": 8,
                },
            }
        ),
    ]

    merged = merge_chat_completion_chunks(chunks)
    serialized = make_serializable(merged)

    message = serialized["choices"][0]["message"]
    assert message["reasoning_content"] == "first second"
    assert message["content"] == "answer"
    assert message["tool_calls"][0] == {
        "id": "call-1",
        "type": "function",
        "function": {"name": "lookup", "arguments": '{"query":"value"}'},
    }
    assert serialized["choices"][0]["finish_reason"] == "tool_calls"
    assert serialized["usage"]["completion_tokens_details"]["reasoning_tokens"] == 4
    assert serialized["usage"]["prompt_cache_hit_tokens"] == 8
    assert serialized["system_fingerprint"] == "fp-1"
    assert serialized["provider_trace"] == {"trace_id": "trace-1"}
