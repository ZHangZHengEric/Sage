"""
LLM 请求前的消息清洗工具，纯函数无状态。

- ``remove_orphan_tool_calls``：去掉 tool_call_id 没有匹配 tool 消息回复的 assistant tool_calls 消息；
- ``strip_content_when_tool_calls``：当 assistant 消息带有 tool_calls 时，去掉 content 字段。
"""

from __future__ import annotations

from typing import Any, Dict, List

from sagents.context.messages.message import MessageRole


def _get_tool_call_id(tool_call: Any) -> Any:
    """兼容 ChoiceDeltaToolCall 对象与字典两种形式取出 id。"""
    if hasattr(tool_call, 'id'):
        return tool_call.id
    if isinstance(tool_call, dict):
        return tool_call.get('id')
    return None


def remove_orphan_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """移除 assistant 消息中的 tool_calls，但其后续没有对应 tool_call_id 的 tool 消息时丢弃整条。

    保持原顺序与对象引用。
    """
    matched_tool_call_ids = [
        msg['tool_call_id']
        for msg in messages
        if msg.get('role') == MessageRole.TOOL.value and 'tool_call_id' in msg
    ]

    new_messages: List[Dict[str, Any]] = []
    for msg in messages:
        if msg.get('role') == MessageRole.ASSISTANT.value and 'tool_calls' in msg:
            tool_calls = msg['tool_calls'] or []
            if any(_get_tool_call_id(tc) not in matched_tool_call_ids for tc in tool_calls):
                continue
        new_messages.append(msg)
    return new_messages


def strip_content_when_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """如果 assistant 消息包含 tool_calls，则就地移除 content 字段。返回同一个列表。"""
    for msg in messages:
        if msg.get('role') == MessageRole.ASSISTANT.value and msg.get('tool_calls'):
            msg.pop('content', None)
    return messages
