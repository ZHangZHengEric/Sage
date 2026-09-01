"""Structured operational logging facade. Sink implementations live in plugins/."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.observability.contracts import (
    LogError,
    LogLevel,
    LogRecord,
    LogSink,
)


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


def encode_log_record(record: LogRecord) -> str:
    """Return one redacted JSONL line for a structured record."""

    safe = record.model_copy(
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
    return (
        json.dumps(
            safe.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


class StructuredLogger:
    """Small context-binding facade that keeps records uniform across layers."""

    def __init__(
        self,
        sink: LogSink,
        component: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.sink = sink
        self.component = component
        self.context = dict(context or {})

    def bind(self, **context: Any) -> "StructuredLogger":
        return StructuredLogger(
            self.sink,
            self.component,
            context={**self.context, **context},
        )

    def log(
        self,
        level: LogLevel | str,
        event: str,
        message: str,
        *,
        error: BaseException | None = None,
        attributes: Mapping[str, Any] | None = None,
        **context: Any,
    ) -> None:
        values = {**self.context, **context}
        known = {
            key: values.pop(key, None)
            for key in (
                "session_id",
                "run_id",
                "turn_id",
                "step_id",
                "tool_call_id",
                "request_id",
                "correlation_id",
            )
        }
        try:
            self.sink.write(
                LogRecord(
                    level=LogLevel(level),
                    event=event,
                    message=message,
                    component=self.component,
                    process_id=os.getpid(),
                    error=_log_error(error),
                    attributes={**values, **dict(attributes or {})},
                    **known,
                )
            )
        except Exception:
            # Observability is a projection and must never break the operation
            # it is observing.
            return

    def debug(self, event: str, message: str, **kwargs: Any) -> None:
        self.log(LogLevel.DEBUG, event, message, **kwargs)

    def info(self, event: str, message: str, **kwargs: Any) -> None:
        self.log(LogLevel.INFO, event, message, **kwargs)

    def warning(self, event: str, message: str, **kwargs: Any) -> None:
        self.log(LogLevel.WARNING, event, message, **kwargs)

    def error(self, event: str, message: str, **kwargs: Any) -> None:
        self.log(LogLevel.ERROR, event, message, **kwargs)

    def exception(
        self, event: str, message: str, error: BaseException, **kwargs: Any
    ) -> None:
        self.log(LogLevel.ERROR, event, message, error=error, **kwargs)


def _log_error(error: BaseException | None) -> LogError | None:
    if error is None:
        return None
    if isinstance(error, SageV2Error):
        return LogError(
            type=type(error).__name__,
            message=error.info.message,
            code=error.info.code,
            category=error.info.category.value,
            stack_trace="".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )[-16_000:],
        )
    return LogError(
        type=type(error).__name__,
        message=str(error),
        stack_trace="".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[-16_000:],
    )


class StructuredLoggingHandler(logging.Handler):
    def __init__(self, logger: StructuredLogger) -> None:
        super().__init__()
        self.structured_logger = logger

    def emit(self, record: logging.LogRecord) -> None:
        level = (
            LogLevel.CRITICAL
            if record.levelno >= logging.CRITICAL
            else LogLevel.ERROR
            if record.levelno >= logging.ERROR
            else LogLevel.WARNING
            if record.levelno >= logging.WARNING
            else LogLevel.INFO
            if record.levelno >= logging.INFO
            else LogLevel.DEBUG
        )
        error = record.exc_info[1] if record.exc_info else None
        self.structured_logger.log(
            level,
            "python.log",
            record.getMessage(),
            error=error,
            attributes={
                "python_logger": record.name,
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            },
        )


def install_standard_logging(sink: LogSink, *, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, StructuredLoggingHandler):
            handler.structured_logger = StructuredLogger(sink, "python")
            return
    handler = StructuredLoggingHandler(StructuredLogger(sink, "python"))
    handler.setLevel(level)
    root.addHandler(handler)
    if root.level > level:
        root.setLevel(level)
