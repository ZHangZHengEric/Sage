"""Bounded, redacted content shared by all trace backends."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from itertools import islice
from urllib.parse import urlsplit, urlunsplit

from sagents.v2.runtime.observability.log_format import redact_log_value

_URL = re.compile(r"https?://[^\s\"'<>]+")
_DATA = re.compile(r"data:[^\s\"'<>]+")


def _safe_url(match: re.Match) -> str:
    try:
        parts = urlsplit(match.group())
        return urlunsplit(
            (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")
        )
    except ValueError:
        return "[URL]"


def safe_trace_value(value: Any, *, limit: int = 16384, depth: int = 0) -> Any:
    """Redact known secret fields/tokens and omit inline media and URL queries."""
    if depth > 12:
        return "[DEPTH LIMIT]"
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        safe = {}
        for key, item in islice(value.items(), 128):
            key = str(key)
            if redact_log_value({key: None})[key] == "[REDACTED]":
                safe[key] = "[REDACTED]"
            elif key.lower() in {"data", "base64", "b64_json"}:
                safe[key] = "[MEDIA OMITTED]"
            else:
                safe[key] = safe_trace_value(item, limit=limit, depth=depth + 1)
        return safe
    if isinstance(value, (tuple, list)):
        return [
            safe_trace_value(item, limit=limit, depth=depth + 1) for item in value[:128]
        ]
    if isinstance(value, str):
        safe = _URL.sub(
            _safe_url,
            _DATA.sub("[MEDIA OMITTED]", redact_log_value(value[: limit + 1])),
        )
        return safe[:limit] + ("…" if len(value) > limit else "")
    return redact_log_value(value)


def trace_content(sink: Any, value: Any) -> Any:
    """Content policy applies at collection time, before exporter buffering."""
    if sink is None or getattr(sink, "content_mode", "redacted") == "metadata":
        return None
    limit = getattr(sink, "max_content_chars", 16384)
    safe = safe_trace_value(value, limit=limit)
    encoded = json.dumps(safe, ensure_ascii=False, default=str)
    if len(encoded) > limit:
        return {"truncated": True, "preview": encoded[: max(0, limit - 64)]}
    return safe
