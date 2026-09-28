from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sagents.v2.runtime.observability import FilesystemLogSink, StdoutLogSink, StructuredLogger
from sagents.v2.runtime.observability.contracts import LogRecord, LogSink
from sagents.v2.runtime.observability.logs import (
    StructuredLoggingHandler,
    get_logger as get_logger,
    set_process_log_sink,
)


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "info"
    format: str = "json"
    directory: str | None = None


class ServerLogSink:
    """Send each operational record to every configured process output."""

    format_version = "sage.log/v1"

    def __init__(self, settings: LoggingSettings, *, service_name: str) -> None:
        self.stdout = StdoutLogSink(min_level=settings.level, format=settings.format)
        self.file = (
            FilesystemLogSink(
                Path(settings.directory),
                filename=f"{service_name}.log",
                min_level=settings.level,
                format=settings.format,
            )
            if settings.directory and settings.directory.strip()
            else None
        )

    def write(self, record: LogRecord) -> None:
        self.stdout.write(record)
        if self.file is not None:
            self.file.write(record)

    def close(self) -> None:
        self.stdout.close()
        if self.file is not None:
            self.file.close()


class _SuccessfulHealthProbeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 5:
            return True
        method, raw_path, status_code = record.args[1], record.args[2], record.args[4]
        if not isinstance(raw_path, str) or not isinstance(status_code, int):
            return True
        path = raw_path.partition("?")[0]
        return not (method == "GET" and path in {"/livez", "/readyz"} and 200 <= status_code < 400)


def init_logging(settings: LoggingSettings, *, service_name: str) -> LogSink:
    sink = ServerLogSink(settings, service_name=service_name)
    set_process_log_sink(sink)
    level = getattr(logging, settings.level.upper())
    handler = StructuredLoggingHandler(StructuredLogger(sink, service_name))
    handler.setLevel(level)
    logging.basicConfig(handlers=[handler], level=level, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard = logging.getLogger(name)
        uvicorn_handler = StructuredLoggingHandler(StructuredLogger(sink, service_name))
        uvicorn_handler.setLevel(level)
        if name == "uvicorn.access":
            uvicorn_handler.addFilter(_SuccessfulHealthProbeFilter())
        standard.handlers = [uvicorn_handler]
        standard.setLevel(level)
        standard.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.INFO)
    return sink


def close_logging() -> None:
    logging.getLogger().handlers.clear()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
