"""Shared log encoding and redaction, independent of facades and sinks."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord


_LEVEL_ORDER = {
    LogLevel.DEBUG: 10,
    LogLevel.INFO: 20,
    LogLevel.WARNING: 30,
    LogLevel.ERROR: 40,
    LogLevel.CRITICAL: 50,
}


def record_reaches_min_level(level: LogLevel, min_level: LogLevel) -> bool:
    """Return whether a record should be written for the configured floor."""

    return _LEVEL_ORDER[level] >= _LEVEL_ORDER[min_level]


_SENSITIVE_KEY = re.compile(
    r"authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|secret|credential|cookie",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_SECRET_TOKEN = re.compile(r"\bsk-[a-zA-Z0-9_-]{6,}\b")


def redact_log_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else redact_log_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_log_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TOKEN.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Enum):
        return redact_log_value(value.value)
    if isinstance(value, BaseModel):
        return redact_log_value(value.model_dump(mode="json"))
    if isinstance(value, (Path, date, datetime)):
        return str(value)
    # Logging must remain best effort even when framework exceptions contain
    # arbitrary objects (for example validation contexts with ValueError).
    return redact_log_value(str(value))


def _redacted_record(record: LogRecord) -> LogRecord:
    return record.model_copy(
        update={
            "message": redact_log_value(record.message),
            "attributes": redact_log_value(record.attributes),
            "error": (
                record.error.model_copy(
                    update={
                        "message": redact_log_value(record.error.message),
                        "stack_trace": redact_log_value(record.error.stack_trace),
                    }
                )
                if record.error is not None
                else None
            ),
        }
    )


def encode_log_record(record: LogRecord) -> str:
    """Return one redacted JSONL line for a structured record."""

    safe = _redacted_record(record)
    return (
        json.dumps(
            safe.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def format_log_record(record: LogRecord) -> str:
    """Return one redacted console line for a structured record."""

    safe = _redacted_record(record)
    stamp = safe.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def console_value(value: Any) -> str:
        return str(value).replace("\r", "\\r").replace("\n", "\\n")

    fields: list[str] = []
    for key in (
        "session_id",
        "run_id",
        "turn_id",
        "step_id",
        "tool_call_id",
        "request_id",
        "correlation_id",
    ):
        value = getattr(safe, key)
        if value:
            fields.append(f"{key}={value}")
    for key, value in (safe.attributes or {}).items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list, tuple)):
            fields.append(
                f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
            )
            continue
        fields.append(f"{key}={console_value(value)}")
    if safe.error is not None:
        detail = safe.error.code or safe.error.type
        fields.append(f"error={detail}:{console_value(safe.error.message)}")
        if safe.error.stack_trace:
            fields.append(f"stack_trace={console_value(safe.error.stack_trace)}")
    suffix = f" | {' '.join(fields)}" if fields else ""
    return (
        f"{stamp} | {safe.level.value.upper():<8} | {safe.component} | "
        f"{safe.event} | {console_value(safe.message)}{suffix}\n"
    )
