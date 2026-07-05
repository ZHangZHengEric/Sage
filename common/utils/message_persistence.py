"""Helpers for storing clean conversation history."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List


_CURRENT_TIME_RE = re.compile(
    r"<current_time\b[^>]*>.*?</current_time>",
    re.IGNORECASE | re.DOTALL,
)
_RUNTIME_CONTEXT_RE = re.compile(
    r"<runtime_context\b[^>]*>.*?</runtime_context>",
    re.IGNORECASE | re.DOTALL,
)
_USER_REQUEST_RE = re.compile(
    r"<user_request\b[^>]*>\s*(.*?)\s*</user_request>",
    re.IGNORECASE | re.DOTALL,
)
_RUNTIME_METADATA_KEYS = {
    "frozen_user_inference",
    "runtime_context_injected",
    "inference_view_only",
    "frozen_user_inference_version",
}
_CURRENT_TIME_METADATA_KEY = "current_time_context"


def sanitize_messages_for_persistence(messages: List[Any]) -> List[Dict[str, Any]]:
    """Return a persistence-safe copy of messages.

    Runtime context belongs to the per-request inference view. Persisted history
    keeps user-visible content clean while preserving the current-time tag as
    metadata for audit/debug use.
    """
    return [_sanitize_message_for_persistence(message) for message in messages or []]


def extract_current_time_context_tag(content: Any) -> str | None:
    """Extract the original ``<current_time>...</current_time>`` tag."""
    return _extract_current_time_tag(content)


def _sanitize_message_for_persistence(message: Any) -> Dict[str, Any]:
    if hasattr(message, "to_dict") and callable(message.to_dict):
        data = copy.deepcopy(message.to_dict())
    elif isinstance(message, dict):
        data = copy.deepcopy(message)
    else:
        data = copy.deepcopy(getattr(message, "__dict__", {}))

    current_time_tag = _extract_current_time_tag(data.get("content"))
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        frozen = metadata.get("frozen_user_inference")
        if isinstance(frozen, dict):
            current_time_tag = current_time_tag or _extract_current_time_tag(
                frozen.get("content")
            )

    if "content" in data:
        data["content"] = _sanitize_content(data.get("content"))
    _sanitize_metadata(data, current_time_tag)
    return data


def _sanitize_metadata(
    message: Dict[str, Any],
    current_time_tag: str | None,
) -> None:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        if current_time_tag:
            message["metadata"] = {_CURRENT_TIME_METADATA_KEY: current_time_tag}
        return

    clean_metadata = copy.deepcopy(metadata)
    for key in _RUNTIME_METADATA_KEYS:
        clean_metadata.pop(key, None)
    if current_time_tag:
        clean_metadata[_CURRENT_TIME_METADATA_KEY] = current_time_tag

    if clean_metadata:
        message["metadata"] = clean_metadata
    else:
        message.pop("metadata", None)


def _extract_current_time_tag(content: Any) -> str | None:
    if isinstance(content, str):
        if "<runtime_context" not in content and "<current_time" not in content:
            return None
        match = _CURRENT_TIME_RE.search(content)
        return match.group(0).strip() if match else None
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            match = _extract_current_time_tag(part.get("text") or part.get("content"))
            if match:
                return match
    return None


def _sanitize_content(content: Any) -> Any:
    if isinstance(content, str):
        return _sanitize_text_content(content)
    if isinstance(content, list):
        return _sanitize_multimodal_content(content)
    return content


def _sanitize_text_content(text: str) -> str:
    if "<runtime_context" not in text:
        return text

    user_request = _USER_REQUEST_RE.search(text)
    if user_request:
        return user_request.group(1).strip()

    cleaned = _RUNTIME_CONTEXT_RE.sub("", text)
    cleaned = re.sub(r"</?user_request\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _sanitize_multimodal_content(content: List[Any]) -> List[Any]:
    sanitized: List[Any] = []
    for part in content:
        if not isinstance(part, dict):
            sanitized.append(copy.deepcopy(part))
            continue

        clean_part = copy.deepcopy(part)
        text_value = clean_part.get("text")
        content_value = clean_part.get("content")
        if isinstance(text_value, str):
            clean_text = _sanitize_multimodal_text_part(text_value)
            if clean_text is None:
                continue
            clean_part["text"] = clean_text
        elif isinstance(content_value, str):
            clean_text = _sanitize_multimodal_text_part(content_value)
            if clean_text is None:
                continue
            clean_part["content"] = clean_text
        sanitized.append(clean_part)
    return sanitized


def _sanitize_multimodal_text_part(text: str) -> str | None:
    if "<runtime_context" in text:
        cleaned = _RUNTIME_CONTEXT_RE.sub("", text)
    else:
        cleaned = text
    cleaned = re.sub(r"</?user_request\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    return cleaned if cleaned else None
