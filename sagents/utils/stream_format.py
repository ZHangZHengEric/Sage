import traceback
from pydantic import BaseModel
from openai.types.chat import ChatCompletion, ChatCompletionMessage, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage
def merge_stream_response_to_non_stream_response(chunks):
    """
    将流式的chunk，进行合并成非流式的response
    """
    id_ = model_ = created_ = None
    content = ""
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage = None

    for chk in chunks:
        if id_ is None:
            id_, model_, created_ = chk.id, chk.model, chk.created

        if chk.usage:                       # 最后的 usage chunk
            usage = CompletionUsage(
                prompt_tokens=chk.usage.prompt_tokens,
                completion_tokens=chk.usage.completion_tokens,
                total_tokens=chk.usage.total_tokens,
            )

        if not chk.choices:
            continue

        delta = chk.choices[0].delta
        finish_reason = chk.choices[0].finish_reason

        if delta.content:
            content += delta.content

        for tc in delta.tool_calls or []:
            idx = tc.index
            if idx not in tool_calls:
                tool_calls[idx] = {
                    "id": tc.id or "",
                    "type": tc.type or "function",
                    "function": {"name": "", "arguments": ""},
                }
            func = tool_calls[idx]["function"]
            func["name"] += tc.function.name or ""
            func["arguments"] += tc.function.arguments or ""

    return ChatCompletion(
        id=id_,
        object="chat.completion",          # ← 关键修复
        created=created_,
        model=model_,
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=content or None,
                    tool_calls=[
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
                    else None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )
