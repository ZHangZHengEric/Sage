"""
将 OpenAI ChatCompletionChunk 流合并为完整的 ChatCompletion 对象。

从 AgentBase 抽取，便于复用与单测。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function


def merge_chat_completion_chunks(chunks: Iterable) -> ChatCompletion:
    """将流式的 ChatCompletionChunk 序列合并为一个非流式 ChatCompletion。

    - 串接所有 ``delta.content`` 为最终 message 内容；
    - 按 ``tool_call.index`` 聚合 tool_calls 名称与参数；
    - 串接供应商扩展的 ``delta.reasoning_content``；
    - 取最后一个携带 ``usage`` 的 chunk 作为完整 usage；
    - 缺失字段以稳健默认值兜底，保证产出可被下游消费。
    """
    id_ = model_ = created_ = None
    content = ""
    reasoning_content = ""
    refusal = ""
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage = None
    message_extras: dict[str, Any] = {}
    choice_extras: dict[str, Any] = {}
    response_extras: dict[str, Any] = {}

    def merge_stream_value(existing: Any, new_value: Any) -> Any:
        if existing is None:
            return deepcopy(new_value)
        if isinstance(existing, str) and isinstance(new_value, str):
            return existing + new_value
        if isinstance(existing, list) and isinstance(new_value, list):
            return [*existing, *deepcopy(new_value)]
        if isinstance(existing, dict) and isinstance(new_value, dict):
            merged = deepcopy(existing)
            merged.update(deepcopy(new_value))
            return merged
        return deepcopy(new_value)

    for chk in chunks:
        if id_ is None:
            id_, model_, created_ = chk.id, chk.model, chk.created

        if chk.usage:
            usage = deepcopy(chk.usage)

        chunk_dump = chk.model_dump(exclude_none=True)
        for key, value in chunk_dump.items():
            if key not in {"id", "object", "created", "model", "choices", "usage"}:
                response_extras[key] = deepcopy(value)

        if not chk.choices:
            continue

        choice = chk.choices[0]
        delta = choice.delta
        if choice.finish_reason is not None:
            finish_reason = choice.finish_reason
        choice_dump = choice.model_dump(exclude_none=True)
        for key, value in choice_dump.items():
            if key not in {"index", "delta", "finish_reason"}:
                choice_extras[key] = deepcopy(value)

        if delta.content:
            content += delta.content
        delta_reasoning = getattr(delta, "reasoning_content", None)
        if isinstance(delta_reasoning, str):
            reasoning_content += delta_reasoning
        if delta.refusal:
            refusal += delta.refusal

        delta_dump = delta.model_dump(exclude_none=True)
        for key, value in delta_dump.items():
            if key not in {
                "content",
                "reasoning_content",
                "refusal",
                "role",
                "tool_calls",
            }:
                if key == "reasoning_details":
                    # MiniMax emits cumulative structured snapshots; retain the
                    # latest complete value instead of concatenating snapshots.
                    message_extras[key] = deepcopy(value)
                else:
                    message_extras[key] = merge_stream_value(
                        message_extras.get(key), value
                    )

        for tc in delta.tool_calls or []:
            idx = tc.index
            if idx is None:
                continue
            if idx not in tool_calls:
                tool_calls[idx] = {
                    "id": tc.id or "",
                    "type": tc.type or "function",
                    "function": {"name": "", "arguments": ""},
                }
            entry = tool_calls[idx]
            if tc.id and not entry["id"]:
                entry["id"] = tc.id
            if tc.function.name and not entry["function"]["name"]:
                entry["function"]["name"] = tc.function.name
            if tc.function.arguments:
                entry["function"]["arguments"] += tc.function.arguments

    if finish_reason is None:
        finish_reason = "stop"
    if id_ is None:
        id_ = "stream-merge-empty"
    if created_ is None:
        created_ = 0
    if model_ is None:
        model_ = "unknown"

    return ChatCompletion(
        id=id_,
        object="chat.completion",
        created=created_,
        model=model_,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=content or None,
                    reasoning_content=reasoning_content or None,
                    refusal=refusal or None,
                    tool_calls=(
                        [
                            ChatCompletionMessageToolCall(
                                id=tc["id"],
                                type="function",
                                function=Function(
                                    name=tc["function"]["name"],
                                    arguments=tc["function"]["arguments"],
                                ),
                            )
                            for tc in tool_calls.values()
                        ]
                        if tool_calls
                        else None
                    ),
                    **message_extras,
                ),
                finish_reason=finish_reason,
                **choice_extras,
            )
        ],
        usage=usage,
        **response_extras,
    )
