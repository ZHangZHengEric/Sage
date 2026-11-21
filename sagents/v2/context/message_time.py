"""Render message-local time anchors without consulting the current clock."""
from collections.abc import Mapping
from datetime import datetime
from html import escape
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FROZEN_TIME_KEY = "frozen_current_time_context"
_TIME_TAG = re.compile(
    r"<(current_time|current_timezone)\b[^>]*>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)


def frozen_time_context(metadata: Mapping, *, accepted_at: datetime | None = None) -> str | None:
    configured = metadata.get("system_context")
    context = configured if isinstance(configured, Mapping) else {}
    value = context.get("current_time") or metadata.get("current_time")
    timezone = context.get("current_timezone")
    timezone = timezone if isinstance(timezone, str) and timezone.strip() else None
    if not isinstance(value, str) or not value.strip():
        if accepted_at is None:
            return None
        if timezone:
            try:
                accepted_at = accepted_at.astimezone(ZoneInfo(timezone))
            except (ValueError, ZoneInfoNotFoundError):
                pass
        value = accepted_at.isoformat()
    result = f"<current_time>{escape(value)}</current_time>"
    if timezone:
        result += f"\n<current_timezone>{escape(timezone)}</current_timezone>"
    return result


def historical_time_context(message) -> str | None:
    frozen = message.metadata.get(FROZEN_TIME_KEY)
    if isinstance(frozen, str):
        matches = [match.group(0) for match in _TIME_TAG.finditer(frozen)]
        if any(re.match(r"<current_time\b", tag, flags=re.IGNORECASE) for tag in matches):
            return "\n".join(matches)
    for block in message.content:
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        runtime = re.search(r"<runtime_context\b[^>]*>(.*?)</runtime_context>", text,
                            flags=re.IGNORECASE | re.DOTALL)
        if runtime is None:
            continue
        system = re.search(r"<system_context\b[^>]*>(.*?)</system_context>", runtime.group(1),
                           flags=re.IGNORECASE | re.DOTALL)
        matches = [match.group(0) for match in _TIME_TAG.finditer(system.group(1) if system else runtime.group(1))]
        if any(re.match(r"<current_time\b", tag, flags=re.IGNORECASE) for tag in matches):
            return "\n".join(matches)
    return None
