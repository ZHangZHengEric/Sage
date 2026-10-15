from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.v2.server.observability.context import get_request_id
from sagents.v2.runtime.observability import (
    FilesystemLogSink,
    StdoutLogSink,
    StructuredLogger,
)
from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord, LogSink
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


class _HealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 5:
            return True
        method, raw_path, status_code = record.args[1], record.args[2], record.args[4]
        if not isinstance(raw_path, str) or not isinstance(status_code, int):
            return True
        path = raw_path.partition("?")[0]
        if path == "/health":
            return False
        return not (
            method == "GET"
            and path in {"/livez", "/readyz"}
            and 200 <= status_code < 400
        )


class _AccessLoggingHandler(StructuredLoggingHandler):
    """Keep HTTP access records focused on the request and its outcome."""

    def __init__(self, sink: LogSink, *, service_name: str) -> None:
        super().__init__(StructuredLogger(sink, service_name))
        self.sink = sink
        self.service_name = service_name

    def emit(self, record: logging.LogRecord) -> None:
        if not isinstance(record.args, tuple) or len(record.args) < 5:
            super().emit(record)
            return
        method, raw_path, status_code = record.args[1], record.args[2], record.args[4]
        if (
            not isinstance(method, str)
            or not isinstance(raw_path, str)
            or not isinstance(status_code, int)
        ):
            super().emit(record)
            return
        request_id = get_request_id()
        try:
            self.sink.write(
                LogRecord(
                    level=LogLevel.INFO,
                    event="http.access",
                    message=f"{method} {raw_path.partition('?')[0]} {status_code}",
                    component=self.service_name,
                    request_id=request_id if request_id != "background" else None,
                )
            )
        except Exception:
            self.handleError(record)


def init_logging(settings: LoggingSettings, *, service_name: str) -> LogSink:
    sink = ServerLogSink(settings, service_name=service_name)
    set_process_log_sink(sink)
    level = getattr(logging, settings.level.upper())
    handler = StructuredLoggingHandler(StructuredLogger(sink, service_name))
    handler.setLevel(level)
    logging.basicConfig(handlers=[handler], level=level, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard = logging.getLogger(name)
        uvicorn_handler = (
            _AccessLoggingHandler(sink, service_name=service_name)
            if name == "uvicorn.access"
            else StructuredLoggingHandler(StructuredLogger(sink, service_name))
        )
        uvicorn_handler.setLevel(level)
        if name == "uvicorn.access":
            uvicorn_handler.addFilter(_HealthAccessFilter())
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
