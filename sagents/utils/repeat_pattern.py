from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType

_VOLATILE_ARG_KEYS = {
    "cache_buster",
    "current_time",
    "invocation_id",
    "nonce",
    "request_id",
    "run_id",
    "span_id",
    "started_at",
    "timestamp",
    "trace_id",
}

_STREAM_TEXT_REPEAT_THRESHOLD = 5
_RECENT_REPEAT_UNIT_WINDOW = 30
_ROLLING_HASH_BASE = 1_000_003
_ROLLING_HASH_MASK = (1 << 64) - 1


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalize_arg_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")


def _strip_volatile_args(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            if _normalize_arg_key(key) in _VOLATILE_ARG_KEYS:
                sanitized[str(key)] = "<volatile>"
            else:
                sanitized[str(key)] = _strip_volatile_args(item)
        return sanitized
    if isinstance(value, list):
        return [_strip_volatile_args(item) for item in value]
    return value


def stable_json(raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        try:
            raw = _strip_volatile_args(raw)
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
        parsed = _strip_volatile_args(parsed)
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


def _build_tool_call_signature(
    fn: Any,
    args: Any,
) -> str:
    fn_norm = normalize_text(str(fn or ""))
    return f"{fn_norm}:{short_hash(stable_json(args))}"


def _build_tool_call_parts_and_events(
    chunks: List[MessageChunk],
) -> Tuple[List[str], List[Tuple[int, str]]]:
    """Normalize streamed tool-call deltas and keep first-observed event order."""
    tool_call_parts: List[str] = []
    pending_by_key: Dict[str, Dict[str, Any]] = {}
    key_by_index: Dict[int, str] = {}
    pending_order: List[str] = []
    event_positions_by_key: Dict[str, List[int]] = {}
    direct_event_parts: List[Tuple[int, str]] = []
    last_key: Optional[str] = None

    for chunk_index, chunk in enumerate(chunks):
        for tool_call in chunk.tool_calls or []:
            tc_id = _tool_call_attr(tool_call, "id", "") or ""
            tc_index = _tool_call_attr(tool_call, "index", None)
            fn_obj = _tool_call_function(tool_call)
            fn = _function_attr(fn_obj, "name", "") or ""
            args = _function_attr(fn_obj, "arguments", "") or ""

            # Dict tool calls from non-streaming responses normally have no index and
            # already contain complete arguments, so they can be signed directly.
            if tc_index is None and isinstance(tool_call, dict):
                signature = _build_tool_call_signature(fn, args)
                tool_call_parts.append(signature)
                direct_event_parts.append((chunk_index, f"tool_call:{signature}"))
                continue

            key: Optional[str] = None
            if tc_id:
                key = tc_id
                existing_key = (
                    key_by_index.get(tc_index) if tc_index is not None else None
                )
                if (
                    existing_key
                    and existing_key != key
                    and existing_key in pending_by_key
                    and key not in pending_by_key
                ):
                    pending_by_key[key] = pending_by_key.pop(existing_key)
                    event_positions_by_key[key] = event_positions_by_key.pop(
                        existing_key
                    )
                    pending_order = [
                        key if item == existing_key else item for item in pending_order
                    ]
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
                signature = _build_tool_call_signature(fn, args)
                tool_call_parts.append(signature)
                direct_event_parts.append((chunk_index, f"tool_call:{signature}"))
                continue

            entry = pending_by_key.get(key)
            if entry is None:
                entry = {"name": "", "arguments": ""}
                pending_by_key[key] = entry
                pending_order.append(key)
                event_positions_by_key[key] = [chunk_index]
            if fn:
                entry["name"] = fn
            if args:
                entry["arguments"] += args
            last_key = key

    event_parts: List[Tuple[int, str]] = list(direct_event_parts)
    for key in pending_order:
        entry = pending_by_key[key]
        signature = _build_tool_call_signature(
            entry.get("name", ""), entry.get("arguments", "")
        )
        tool_call_parts.append(signature)
        event_parts.append((event_positions_by_key[key][0], f"tool_call:{signature}"))

    return tool_call_parts, event_parts


def _build_tool_call_parts(chunks: List[MessageChunk]) -> List[str]:
    tool_call_parts, _ = _build_tool_call_parts_and_events(chunks)
    return tool_call_parts


def _loop_signature_events(signature: str) -> List[str]:
    try:
        parsed = json.loads(signature)
    except Exception:
        return [f"turn:{short_hash(signature)}"]
    if not isinstance(parsed, dict):
        return [f"turn:{short_hash(signature)}"]
    events = parsed.get("events")
    if isinstance(events, list) and all(isinstance(item, str) for item in events):
        return [item for item in events if not item.startswith("tool_result:")]

    fallback_events: List[str] = []
    assistant_text = parsed.get("assistant_text")
    if isinstance(assistant_text, str) and assistant_text:
        fallback_events.append(f"assistant_text:{assistant_text}")
    for item in parsed.get("tool_calls") or []:
        fallback_events.append(f"tool_call:{item}")
    return fallback_events or [f"turn:{short_hash(signature)}"]


def build_loop_signature(chunks: List[MessageChunk]) -> str:
    """
    构建单轮执行签名（文本 + 工具调用 + 工具结果）。
    """
    text_parts: List[str] = []
    tool_call_parts, tool_call_events = _build_tool_call_parts_and_events(chunks)
    tool_result_parts: List[str] = []
    event_parts_with_position: List[Tuple[int, str]] = list(tool_call_events)
    text_events_by_key: Dict[str, Tuple[int, List[str]]] = {}
    stream_repeat_state: Dict[str, Tuple[str, int, int]] = {}
    stream_repeat_events: List[Tuple[int, str]] = []

    def flush_stream_repeat(text_key: str) -> None:
        state = stream_repeat_state.get(text_key)
        if not state:
            return
        text, count, first_index = state
        if count >= _STREAM_TEXT_REPEAT_THRESHOLD:
            event = f"assistant_text_delta:{short_hash(text)}"
            stream_repeat_events.extend((first_index, event) for _ in range(count))

    for chunk_index, chunk in enumerate(chunks):
        if chunk.role == MessageRole.ASSISTANT.value and (chunk.content or "").strip():  # pyright: ignore[reportAttributeAccessIssue]
            if chunk.message_type != MessageType.REASONING_CONTENT.value:
                normalized = normalize_text(chunk.content)  # pyright: ignore[reportArgumentType]
                text_parts.append(normalized)
                text_key = chunk.message_id or f"chunk:{chunk_index}"
                existing = text_events_by_key.get(text_key)
                if existing is None:
                    text_events_by_key[text_key] = (chunk_index, [normalized])
                else:
                    existing[1].append(normalized)
                repeat_state = stream_repeat_state.get(text_key)
                if repeat_state and repeat_state[0] == normalized:
                    stream_repeat_state[text_key] = (
                        normalized,
                        repeat_state[1] + 1,
                        repeat_state[2],
                    )
                else:
                    flush_stream_repeat(text_key)
                    stream_repeat_state[text_key] = (normalized, 1, chunk_index)

        if chunk.role == MessageRole.TOOL.value:
            tool_name = (chunk.metadata or {}).get("tool_name", "")
            tool_content_norm = normalize_text(chunk.content or "")  # pyright: ignore[reportArgumentType]
            tool_result = f"{tool_name}:{short_hash(tool_content_norm)}"
            tool_result_parts.append(tool_result)

    for text_key in list(stream_repeat_state):
        flush_stream_repeat(text_key)

    for first_index, parts in text_events_by_key.values():
        text = normalize_text(" ".join(parts))
        if text:
            event_parts_with_position.append(
                (first_index, f"assistant_text:{short_hash(text)}")
            )
    event_parts_with_position.extend(stream_repeat_events)

    event_parts = [
        event
        for _, event in sorted(
            event_parts_with_position,
            key=lambda item: item[0],
        )
    ]

    signature_obj = {
        "assistant_text": short_hash(" ".join(text_parts)),
        "tool_calls": tool_call_parts,
        "tool_results": tool_result_parts,
        "events": event_parts,
    }
    return json.dumps(signature_obj, ensure_ascii=False, sort_keys=True)


def _detect_sequence_repeat_pattern(
    sequence: Sequence[str],
    max_period: int,
    *,
    mode: str,
    allow_partial: bool,
) -> Optional[Dict[str, int]]:
    n = len(sequence)
    if n < 2:
        return None

    upper_period = min(max_period, n // 2 if n >= 4 else 1)
    candidates: List[Tuple[int, int, int, Dict[str, int]]] = []
    for period in range(1, upper_period + 1):
        max_cycles = n // period
        min_cycles = 2
        if max_cycles < min_cycles:
            continue

        pattern = list(sequence[n - period : n])
        cycles = 1
        idx = n - period
        while idx - period >= 0 and list(sequence[idx - period : idx]) == pattern:
            cycles += 1
            idx -= period

        if cycles >= min_cycles:
            pattern_info: Dict[str, Any] = {
                "period": period,
                "cycles": cycles,
                "span": period * cycles,
            }
            if mode != "turn":
                pattern_info["mode"] = mode
            candidates.append((1, pattern_info["span"], -period, pattern_info))

    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]

    if not allow_partial or n < 4:
        return None

    upper_partial_period = min(max_period, n - 1)
    for period in range(2, upper_partial_period + 1):
        min_prefix = max(3, int(period * 0.4))
        max_prefix = min(period - 1, n - period)
        for prefix_len in range(min_prefix, max_prefix + 1):
            full_start = n - prefix_len - period
            if full_start < 0:
                continue
            pattern = list(sequence[full_start : full_start + period])
            partial = list(sequence[n - prefix_len : n])
            if partial != pattern[:prefix_len]:
                continue

            cycles = 1
            prev_start = full_start - period
            while (
                prev_start >= 0
                and list(sequence[prev_start : prev_start + period]) == pattern
            ):
                cycles += 1
                prev_start -= period

            span = period * cycles + prefix_len
            pattern_info = {
                "period": period,
                "cycles": cycles,
                "span": span,
                "mode": mode,
                "partial": True,
                "partial_prefix": prefix_len,
            }
            candidates.append((0, span, -period, pattern_info))

    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]
    return None


def _detect_suffix_duplicate_substring(
    sequence: Sequence[str],
    max_len: int,
    *,
    mode: str,
    min_len: int = 2,
) -> Optional[Dict[str, int]]:
    """Detect whether the newly appended tail repeats an earlier substring.

    Only suffixes are considered, so stale duplicate substrings elsewhere in the
    window do not trigger a new loop finding.
    """
    n = len(sequence)
    if n < min_len * 2:
        return None

    upper_len = min(max_len, n // 2 if n >= min_len * 2 else 0)
    unit_hashes = [
        int(hashlib.blake2b(str(item).encode("utf-8"), digest_size=8).hexdigest(), 16)
        for item in sequence
    ]
    prefix_hashes = [0] * (n + 1)
    powers = [1] * (upper_len + 1)
    for idx, value in enumerate(unit_hashes):
        prefix_hashes[idx + 1] = (
            prefix_hashes[idx] * _ROLLING_HASH_BASE + value
        ) & _ROLLING_HASH_MASK
    for idx in range(1, upper_len + 1):
        powers[idx] = (powers[idx - 1] * _ROLLING_HASH_BASE) & _ROLLING_HASH_MASK

    def window_hash(start: int, length: int) -> int:
        return (
            prefix_hashes[start + length] - (prefix_hashes[start] * powers[length])
        ) & _ROLLING_HASH_MASK

    def windows_equal(left: int, right: int, length: int) -> bool:
        for offset in range(length):
            if sequence[left + offset] != sequence[right + offset]:
                return False
        return True

    candidates: List[Tuple[int, int, int, Dict[str, int]]] = []
    for length in range(min_len, upper_len + 1):
        suffix_start = n - length
        suffix_hash = window_hash(suffix_start, length)
        occurrences = 0
        last_start = -1
        for start in range(0, suffix_start - length + 1):
            if window_hash(start, length) == suffix_hash and windows_equal(
                start, suffix_start, length
            ):
                occurrences += 1
                last_start = start

        if occurrences <= 0:
            continue

        adjacent = last_start + length == suffix_start
        pattern_info: Dict[str, Any] = {
            "period": length,
            "cycles": occurrences + 1,
            "span": length * (occurrences + 1) if adjacent else length,
            "mode": mode,
            "suffix_duplicate": True,
            "substring_length": length,
            "previous_occurrences": occurrences,
            "adjacent": adjacent,
        }
        candidates.append((length, int(adjacent), occurrences, pattern_info))

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _tool_call_events(sequence: Sequence[str]) -> List[str]:
    return [event for event in sequence if str(event).startswith("tool_call:")]


def _recent_units(sequence: Sequence[str]) -> List[str]:
    return list(sequence[-_RECENT_REPEAT_UNIT_WINDOW:])


def _recent_loop_events(signatures: Sequence[str]) -> List[str]:
    events_reversed: List[str] = []
    for signature in reversed(signatures):
        signature_events = _loop_signature_events(signature)
        for event in reversed(signature_events):
            events_reversed.append(event)
            if len(events_reversed) >= _RECENT_REPEAT_UNIT_WINDOW:
                return list(reversed(events_reversed))
    return list(reversed(events_reversed))


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
    if n < 1:
        return None

    turn_sequence = _recent_units(signatures)
    event_sequence = _recent_loop_events(signatures)
    tool_call_sequence = _recent_units(_tool_call_events(event_sequence))
    event_suffix_pattern = _detect_suffix_duplicate_substring(
        event_sequence,
        max_len=max(max_period * 2, 16),
        mode="event",
    )
    tool_call_suffix_pattern = _detect_suffix_duplicate_substring(
        tool_call_sequence,
        max_len=max(max_period * 2, 16),
        mode="tool_call",
    )
    event_pattern = _detect_sequence_repeat_pattern(
        event_sequence,
        max_period=max(max_period * 2, 16),
        mode="event",
        allow_partial=False,
    )
    tool_call_pattern = _detect_sequence_repeat_pattern(
        tool_call_sequence,
        max_period=max(max_period * 2, 16),
        mode="tool_call",
        allow_partial=False,
    )

    if n < 2:
        if event_pattern:
            return event_pattern
        if tool_call_pattern:
            return tool_call_pattern
        if event_suffix_pattern:
            return event_suffix_pattern
        if tool_call_suffix_pattern:
            return tool_call_suffix_pattern
        tool_call_partial = _detect_sequence_repeat_pattern(
            tool_call_sequence,
            max_period=max(max_period * 2, 16),
            mode="tool_call",
            allow_partial=True,
        )
        if tool_call_partial:
            return tool_call_partial
        return _detect_sequence_repeat_pattern(
            event_sequence,
            max_period=max(max_period * 2, 16),
            mode="event",
            allow_partial=True,
        )

    turn_suffix_pattern = _detect_suffix_duplicate_substring(
        turn_sequence,
        max_len=max_period,
        mode="turn",
    )
    turn_pattern = _detect_sequence_repeat_pattern(
        turn_sequence,
        max_period=max_period,
        mode="turn",
        allow_partial=False,
    )
    if turn_pattern:
        return turn_pattern
    if event_pattern:
        return event_pattern
    if tool_call_pattern:
        return tool_call_pattern
    if event_suffix_pattern:
        return event_suffix_pattern
    if tool_call_suffix_pattern:
        return tool_call_suffix_pattern
    if turn_suffix_pattern:
        return turn_suffix_pattern

    turn_partial = _detect_sequence_repeat_pattern(
        turn_sequence,
        max_period=max_period,
        mode="turn",
        allow_partial=True,
    )
    if turn_partial:
        return turn_partial
    tool_call_partial = _detect_sequence_repeat_pattern(
        tool_call_sequence,
        max_period=max(max_period * 2, 16),
        mode="tool_call",
        allow_partial=True,
    )
    if tool_call_partial:
        return tool_call_partial
    event_pattern = _detect_sequence_repeat_pattern(
        event_sequence,
        max_period=max(max_period * 2, 16),
        mode="event",
        allow_partial=True,
    )
    return event_pattern


def _format_pattern_kind(pattern: Dict[str, int]) -> str:
    mode = pattern.get("mode", "turn")
    if pattern.get("suffix_duplicate"):
        return f"{mode} suffix-duplicate len={pattern.get('substring_length', pattern.get('period', 0))}"
    if pattern.get("partial"):
        return f"{mode} partial-loop prefix={pattern.get('partial_prefix', 0)}"
    return str(mode)


def build_self_correction_message(pattern: Dict[str, int]) -> str:
    return (
        f"自检：检测到执行出现重复循环模式（类型={_format_pattern_kind(pattern)}，周期={pattern['period']}，重复={pattern['cycles']}轮）。"
        "从下一步开始禁止复用同一路径；必须改变执行策略："
        "优先尝试不同工具或参数；若仍无法推进，先明确阻塞点并提出最小必要澄清问题。"
    )
