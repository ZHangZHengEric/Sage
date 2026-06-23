"""
LLM 请求前的消息清洗工具，纯函数无状态。

- ``remove_orphan_tool_calls``：去掉 tool_call_id 没有匹配 tool 消息回复的 assistant tool_calls 消息；
- ``drop_orphan_tool_messages``：去掉没有匹配 assistant tool_calls 的孤儿 tool 消息；
- ``repair_interleaved_tool_messages``：把被 user/system/assistant 插队的 tool 结果移回对应
  assistant tool_calls 后面；
- ``strip_content_when_tool_calls``：当 assistant 消息带有 tool_calls 时，去掉 content 字段。
"""

from __future__ import annotations

from typing import Any, Dict, List

from sagents.context.messages.message import MessageRole


def _get_tool_call_id(tool_call: Any) -> Any:
    """兼容 ChoiceDeltaToolCall 对象与字典两种形式取出 id。"""
    if hasattr(tool_call, "id"):
        return tool_call.id
    if isinstance(tool_call, dict):
        return tool_call.get("id")
    return None


def remove_orphan_tool_calls(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """移除 assistant 消息中的 tool_calls，但其后续没有对应 tool_call_id 的 tool 消息时丢弃整条。

    保持原顺序与对象引用。
    """
    matched_tool_call_ids = [
        msg["tool_call_id"]
        for msg in messages
        if msg.get("role") == MessageRole.TOOL.value and "tool_call_id" in msg
    ]

    new_messages: List[Dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == MessageRole.ASSISTANT.value and "tool_calls" in msg:
            tool_calls = msg["tool_calls"] or []
            if any(
                _get_tool_call_id(tc) not in matched_tool_call_ids for tc in tool_calls
            ):
                continue
        new_messages.append(msg)
    return new_messages


def drop_orphan_tool_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """移除 ``role='tool'`` 但其 ``tool_call_id`` 在前序 assistant ``tool_calls`` 中
    找不到归属的孤儿 tool 消息。

    OpenAI 约束：每条 ``role='tool'`` 消息都必须是某条带 ``tool_calls`` 的 assistant
    消息的回复，否则返回
    ``messages with role 'tool' must be a response to a preceeding message with 'tool_calls'``。

    压缩覆盖隐藏、规则 offload、turn_status 剔除或 ``remove_orphan_tool_calls`` 丢弃
    多调用 assistant 后，都可能让对应的 tool 结果失去归属。此函数作为发往 LLM 前的
    最后一道保证，应在 ``remove_orphan_tool_calls`` 之后调用（届时 assistant 侧已稳定）。

    保持原顺序与对象引用。
    """
    valid_tool_call_ids = set()
    for msg in messages:
        if msg.get("role") == MessageRole.ASSISTANT.value and msg.get("tool_calls"):
            for tool_call in msg["tool_calls"] or []:
                tid = _get_tool_call_id(tool_call)
                if tid is not None:
                    valid_tool_call_ids.add(tid)

    new_messages: List[Dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == MessageRole.TOOL.value:
            if msg.get("tool_call_id") not in valid_tool_call_ids:
                continue
        new_messages.append(msg)
    return new_messages


def repair_interleaved_tool_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """修复 tool_call pair 被其它消息插队的请求视图。

    OpenAI 要求 assistant.tool_calls 后必须紧跟响应这些 ``tool_call_id`` 的
    ``role='tool'`` 消息。运行中 guidance/user 消息或 shell reminder 可能插入到
    assistant tool call 与稍后落盘的 tool result 之间。这里不修改原始 ledger，
    只在发往 LLM 的视图中把可找到的 tool result 搬回对应 assistant 后面。

    保持对象引用；未被搬动的消息维持原相对顺序。
    """
    if not messages:
        return messages

    remaining = list(messages)
    repaired: List[Dict[str, Any]] = []
    i = 0
    while i < len(remaining):
        msg = remaining[i]
        repaired.append(msg)
        i += 1

        if msg.get("role") != MessageRole.ASSISTANT.value or not msg.get("tool_calls"):
            continue

        expected_ids = [
            tid
            for tid in (_get_tool_call_id(tc) for tc in (msg.get("tool_calls") or []))
            if tid is not None
        ]
        if not expected_ids:
            continue

        expected_set = set(expected_ids)
        already_adjacent = {
            remaining[j].get("tool_call_id")
            for j in range(i, len(remaining))
            if remaining[j].get("role") == MessageRole.TOOL.value
        }
        if not expected_set.intersection(already_adjacent):
            # Fast path avoids scanning/removing when no response exists in the tail.
            continue

        moved_by_id: Dict[Any, Dict[str, Any]] = {}
        j = i
        while j < len(remaining):
            candidate = remaining[j]
            if (
                candidate.get("role") == MessageRole.TOOL.value
                and candidate.get("tool_call_id") in expected_set
            ):
                moved_by_id[candidate.get("tool_call_id")] = candidate
                del remaining[j]
                if expected_set.issubset(moved_by_id.keys()):
                    break
                continue
            j += 1

        for tid in expected_ids:
            moved = moved_by_id.get(tid)
            if moved is not None:
                repaired.append(moved)

    return repaired


def strip_content_when_tool_calls(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """如果 assistant 消息包含 tool_calls，则就地移除 content 字段。返回同一个列表。"""
    for msg in messages:
        if msg.get("role") == MessageRole.ASSISTANT.value and msg.get("tool_calls"):
            msg.pop("content", None)
    return messages
