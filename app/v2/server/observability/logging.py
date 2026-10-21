from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.v2.server.observability.context import get_request_id
from sagents.v2.runtime.observability import StructuredLogger
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


def init_logging(settings: LoggingSettings, *, service_name: str, sink: LogSink | None = None) -> LogSink:
    if sink is None:
        from sagents.v2.runtime.observability.provider import create_observability_provider
        sink = create_observability_provider("sage.observability.local", {
            "log_level": settings.level, "log_format": settings.format,
            "log_root": settings.directory, "log_filename": f"{service_name}.log",
        }).logs
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
    for name in (
        "httpx", "httpcore", "httpx2", "httpcore2", "openai", "mcp.client",
        "a2a.utils.telemetry",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("aiomysql", "redis"):
        logging.getLogger(name).setLevel(logging.INFO)
    logging.getLogger("websockets").setLevel(logging.INFO)
    return sink


def close_logging() -> None:
    logging.getLogger().handlers.clear()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
