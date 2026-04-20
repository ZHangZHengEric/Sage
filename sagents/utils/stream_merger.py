"""
将 OpenAI ChatCompletionChunk 流合并为完整的 ChatCompletion 对象。

从 AgentBase 抽取，便于复用与单测。
"""

from __future__ import annotations

from typing import Iterable

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import (
    CompletionTokensDetails,
    CompletionUsage,
    PromptTokensDetails,
)


def merge_chat_completion_chunks(chunks: Iterable) -> ChatCompletion:
    """将流式的 ChatCompletionChunk 序列合并为一个非流式 ChatCompletion。

    - 串接所有 ``delta.content`` 为最终 message 内容；
    - 按 ``tool_call.index`` 聚合 tool_calls 名称与参数；
    - 取最后一个携带 ``usage`` 的 chunk 作为 usage（含 prompt/completion 详情）；
    - 缺失字段以稳健默认值兜底，保证产出可被下游消费。
    """
    id_ = model_ = created_ = None
    content = ""
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage = None

    for chk in chunks:
        if id_ is None:
            id_, model_, created_ = chk.id, chk.model, chk.created

        if chk.usage:
            prompt_tokens_details = None
            if chk.usage.prompt_tokens_details:
                prompt_tokens_details = PromptTokensDetails(
                    cached_tokens=chk.usage.prompt_tokens_details.cached_tokens,
                    audio_tokens=chk.usage.prompt_tokens_details.audio_tokens,
                )

            completion_tokens_details = None
            if chk.usage.completion_tokens_details:
                completion_tokens_details = CompletionTokensDetails(
                    reasoning_tokens=chk.usage.completion_tokens_details.reasoning_tokens,
                    audio_tokens=chk.usage.completion_tokens_details.audio_tokens,
                    accepted_prediction_tokens=chk.usage.completion_tokens_details.accepted_prediction_tokens,
                    rejected_prediction_tokens=chk.usage.completion_tokens_details.rejected_prediction_tokens,
                )

            usage = CompletionUsage(
                prompt_tokens=chk.usage.prompt_tokens,
                completion_tokens=chk.usage.completion_tokens,
                total_tokens=chk.usage.total_tokens,
                prompt_tokens_details=prompt_tokens_details,
                completion_tokens_details=completion_tokens_details,
            )

        if not chk.choices:
            continue

        delta = chk.choices[0].delta
        finish_reason = chk.choices[0].finish_reason

        if delta.content:
            content += delta.content

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
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )
