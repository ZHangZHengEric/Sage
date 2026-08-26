from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


def serialize_reasoning_details(value: Any) -> Optional[List[Dict[str, Any]]]:
    """Convert MiniMax reasoning details to durable JSON-compatible dictionaries."""
    if not isinstance(value, (list, tuple)):
        return None

    details: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            details.append(deepcopy(item))
            continue
        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                details.append(dumped)
                continue
        text = getattr(item, "text", None)
        if isinstance(text, str):
            details.append({"text": text})
    return details or None


def reasoning_text_from_details(value: Any) -> Optional[str]:
    details = serialize_reasoning_details(value)
    if not details:
        return None
    texts = [detail.get("text") for detail in details]
    joined = "".join(text for text in texts if isinstance(text, str))
    return joined or None


class MiniMaxStreamNormalizer:
    """Turn MiniMax cumulative streaming snapshots into OpenAI-style deltas."""

    def __init__(self) -> None:
        self._content = ""
        self._reasoning = ""

    @staticmethod
    def _delta(previous: str, current: str) -> tuple[str, str]:
        if not previous:
            return current, current
        if current.startswith(previous):
            return current[len(previous) :], current
        if previous.startswith(current):
            return "", previous
        # Be permissive with gateways that already emit token deltas.
        return current, previous + current

    def normalize(self, chunk: Any) -> Any:
        choices = getattr(chunk, "choices", None)
        if not choices:
            return chunk
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return chunk

        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            content_delta, self._content = self._delta(self._content, content)
            delta.content = content_delta or None

        reasoning_snapshot = reasoning_text_from_details(
            getattr(delta, "reasoning_details", None)
        )
        if reasoning_snapshot is None:
            raw_reasoning = getattr(delta, "reasoning_content", None)
            if isinstance(raw_reasoning, str) and raw_reasoning:
                reasoning_snapshot = raw_reasoning
        if reasoning_snapshot is not None:
            reasoning_delta, self._reasoning = self._delta(
                self._reasoning, reasoning_snapshot
            )
            delta.reasoning_content = reasoning_delta or None
        return chunk
