"""Structured operational logging facade. Sink implementations live in plugins/."""

from __future__ import annotations

import logging
import os
import traceback
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.observability.contracts import (
    LogError,
    LogLevel,
    LogRecord,
    LogSink,
)
from sagents.v2.runtime.observability.log_format import (
    encode_log_record as encode_log_record,
    format_log_record as format_log_record,
    record_reaches_min_level as record_reaches_min_level,
    redact_log_value as redact_log_value,
)


_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "sage_v2_structured_log_context",
    default=None,
)


@contextmanager
def structured_log_context(**context: Any) -> Iterator[None]:
    """Bind correlation fields across async Runtime and Agent boundaries."""

    current = _LOG_CONTEXT.get() or {}
    token = _LOG_CONTEXT.set({**current, **context})
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


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
        values = {**(_LOG_CONTEXT.get() or {}), **self.context, **context}
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


class _ProcessLogSink:
    """Resolve module-level runtime loggers to the host's current sink."""

    format_version = "sage.log/v1"

    def __init__(self) -> None:
        self.target: LogSink | None = None

    def write(self, record: LogRecord) -> None:
        if self.target is None:
            from sagents.v2.runtime.observability.plugins.logging_stdout import (
                StdoutLogSink,
            )

            self.target = StdoutLogSink()
        self.target.write(record)

    def close(self) -> None:
        return None


_PROCESS_LOG_SINK = _ProcessLogSink()


def get_logger(component: str) -> StructuredLogger:
    return StructuredLogger(_PROCESS_LOG_SINK, component)


def set_process_log_sink(sink: LogSink) -> None:
    _PROCESS_LOG_SINK.target = sink


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
