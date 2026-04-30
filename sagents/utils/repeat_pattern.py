from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Optional

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def stable_json(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return normalize_text(raw)


def short_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def build_loop_signature(chunks: List[MessageChunk]) -> str:
    """
    构建单轮执行签名（文本 + 工具调用 + 工具结果）。
    """
    text_parts: List[str] = []
    tool_call_parts: List[str] = []
    tool_result_parts: List[str] = []

    for chunk in chunks:
        if chunk.tool_calls:
            for tool_call in chunk.tool_calls:
                fn = ""
                args = ""
                if isinstance(tool_call, dict):
                    fn = ((tool_call.get("function") or {}).get("name") or "")
                    args = ((tool_call.get("function") or {}).get("arguments") or "")
                else:
                    fn = (getattr(getattr(tool_call, "function", None), "name", "") or "")
                    args = (getattr(getattr(tool_call, "function", None), "arguments", "") or "")
                tool_call_parts.append(f"{fn}:{short_hash(stable_json(args))}")

        if chunk.role == MessageRole.ASSISTANT.value and (chunk.content or "").strip():
            if chunk.message_type != MessageType.REASONING_CONTENT.value:
                text_parts.append(normalize_text(chunk.content))

        if chunk.role == MessageRole.TOOL.value:
            tool_name = (chunk.metadata or {}).get("tool_name", "")
            tool_content_norm = normalize_text(chunk.content or "")
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

        pattern = signatures[n - period:n]
        cycles = 1
        idx = n - period
        while idx - period >= 0 and signatures[idx - period:idx] == pattern:
            cycles += 1
            idx -= period

        if cycles >= min_cycles:
            if period == 1 and cycles == 2 and idx > 0:
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
