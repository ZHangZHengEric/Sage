from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def stable_json(raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        try:
            return json.dumps(
                raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except Exception:
            return normalize_text(str(raw))
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        return json.dumps(
            parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except Exception:
        return normalize_text(raw)


def short_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def _tool_call_attr(tool_call: Any, name: str, default: Any = None) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(name, default)
    return getattr(tool_call, name, default)


def _tool_call_function(tool_call: Any) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get("function") or {}
    return getattr(tool_call, "function", None)


def _function_attr(function: Any, name: str, default: Any = "") -> Any:
    if isinstance(function, dict):
        return function.get(name, default)
    return getattr(function, name, default)


def _append_tool_call_signature(tool_call_parts: List[str], fn: Any, args: Any) -> None:
    fn_norm = normalize_text(str(fn or ""))
    tool_call_parts.append(f"{fn_norm}:{short_hash(stable_json(args))}")


def _build_tool_call_parts(chunks: List[MessageChunk]) -> List[str]:
    """Normalize streamed tool-call deltas into complete name+argument entries."""
    tool_call_parts: List[str] = []
    pending_by_key: Dict[str, Dict[str, Any]] = {}
    key_by_index: Dict[int, str] = {}
    pending_order: List[str] = []
    last_key: Optional[str] = None

    for chunk in chunks:
        for tool_call in chunk.tool_calls or []:
            tc_id = _tool_call_attr(tool_call, "id", "") or ""
            tc_index = _tool_call_attr(tool_call, "index", None)
            fn_obj = _tool_call_function(tool_call)
            fn = _function_attr(fn_obj, "name", "") or ""
            args = _function_attr(fn_obj, "arguments", "") or ""

            # Dict tool calls from non-streaming responses normally have no index and
            # already contain complete arguments, so they can be signed directly.
            if tc_index is None and isinstance(tool_call, dict):
                _append_tool_call_signature(tool_call_parts, fn, args)
                continue

            key: Optional[str] = None
            if tc_id:
                key = tc_id
                if tc_index is not None:
                    key_by_index[tc_index] = key
            elif tc_index is not None and tc_index in key_by_index:
                key = key_by_index[tc_index]
            elif tc_index is not None:
                key = f"index:{tc_index}"
                key_by_index[tc_index] = key
            elif last_key:
                key = last_key

            if key is None:
                _append_tool_call_signature(tool_call_parts, fn, args)
                continue

            entry = pending_by_key.get(key)
            if entry is None:
                entry = {"name": "", "arguments": ""}
                pending_by_key[key] = entry
                pending_order.append(key)
            if fn:
                entry["name"] = fn
            if args:
                entry["arguments"] += args
            last_key = key

    for key in pending_order:
        entry = pending_by_key[key]
        _append_tool_call_signature(
            tool_call_parts, entry.get("name", ""), entry.get("arguments", "")
        )

    return tool_call_parts


def _signature_has_tool_calls(signature: str) -> bool:
    try:
        parsed = json.loads(signature)
    except Exception:
        return False
    tool_calls = parsed.get("tool_calls") if isinstance(parsed, dict) else None
    return bool(tool_calls)


def build_loop_signature(chunks: List[MessageChunk]) -> str:
    """
    构建单轮执行签名（文本 + 工具调用 + 工具结果）。
    """
    text_parts: List[str] = []
    tool_call_parts = _build_tool_call_parts(chunks)
    tool_result_parts: List[str] = []

    for chunk in chunks:
        if chunk.role == MessageRole.ASSISTANT.value and (chunk.content or "").strip():  # pyright: ignore[reportAttributeAccessIssue]
            if chunk.message_type != MessageType.REASONING_CONTENT.value:
                text_parts.append(normalize_text(chunk.content))  # pyright: ignore[reportArgumentType]

        if chunk.role == MessageRole.TOOL.value:
            tool_name = (chunk.metadata or {}).get("tool_name", "")
            tool_content_norm = normalize_text(chunk.content or "")  # pyright: ignore[reportArgumentType]
            tool_result_parts.append(f"{tool_name}:{short_hash(tool_content_norm)}")

    signature_obj = {
        "assistant_text": short_hash(" ".join(text_parts)),
        "tool_calls": tool_call_parts,
        "tool_results": tool_result_parts,
    }
    return json.dumps(signature_obj, ensure_ascii=False, sort_keys=True)


def detect_repeat_pattern(
    signatures: List[str],
    max_period: int = 8,
) -> Optional[Dict[str, int]]:
    """
    在尾部检测循环模式，支持:
    - AAAAAAA (period=1)
    - ABABAB / ABBABB (period=2/3)
    - AABBAABB (period=4)
    """
    n = len(signatures)
    if n < 2:
        return None

    upper_period = min(max_period, n // 2 if n >= 4 else 1)
    for period in range(1, upper_period + 1):
        max_cycles = n // period
        # period=1（完全相同的连续轮次）：降至2次即触发，提升灵敏度；
        # 更长周期（ABAB/ABABAB等）仍保持2次作为最低要求。
        min_cycles = 2
        if max_cycles < min_cycles:
            continue

        pattern = signatures[n - period : n]
        cycles = 1
        idx = n - period
        while idx - period >= 0 and signatures[idx - period : idx] == pattern:
            cycles += 1
            idx -= period

        if cycles >= min_cycles:
            if (
                period == 1
                and cycles == 2
                and idx > 0
                and not _signature_has_tool_calls(pattern[0])
            ):
                continue
            return {
                "period": period,
                "cycles": cycles,
                "span": period * cycles,
            }
    return None


def build_self_correction_message(pattern: Dict[str, int]) -> str:
    return (
        f"自检：检测到执行出现重复循环模式（周期={pattern['period']}，重复={pattern['cycles']}轮）。"
        "从下一步开始禁止复用同一路径；必须改变执行策略："
        "优先尝试不同工具或参数；若仍无法推进，先明确阻塞点并提出最小必要澄清问题。"
    )
