from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from loguru import logger

from app.server_v2.core.observability.context import get_request_id

_HEALTH_PROBE_PATHS = frozenset({"/livez", "/readyz"})


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "info"
    format: str = "json"
    directory: str | None = None
    retention: str = "14 days"
    rotation: str = "00:00"


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


class _SuccessfulHealthProbeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 5:
            return True

        method, raw_path, status_code = record.args[1], record.args[2], record.args[4]
        if not isinstance(raw_path, str) or not isinstance(status_code, int):
            return True

        path = raw_path.partition("?")[0]
        is_successful_health_probe = (
            method == "GET" and path in _HEALTH_PROBE_PATHS and 200 <= status_code < 400
        )
        return not is_successful_health_probe


def init_logging(settings: LoggingSettings, *, service_name: str) -> None:
    logger.remove()

    def patcher(record: dict[str, Any]) -> None:
        record["extra"]["request_id"] = get_request_id()
        record["extra"]["service"] = service_name

    logger.configure(patcher=cast(Any, patcher))
    level = "WARNING" if settings.level.lower() == "warn" else settings.level.upper()
    if settings.format.lower() == "json":
        logger.add(sys.stdout, level=level, serialize=True)
    else:
        logger.add(
            sys.stdout,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> [{extra[request_id]}] | {level} | {message}"
            ),
        )
    if settings.directory and settings.directory.strip():
        directory = Path(settings.directory)
        directory.mkdir(parents=True, exist_ok=True)
        logger.add(
            directory / f"{service_name}.log",
            level=level,
            rotation=settings.rotation,
            retention=settings.retention,
            encoding="utf-8",
            serialize=settings.format.lower() == "json",
        )
    standard_level = getattr(logging, level)
    logging.basicConfig(handlers=[InterceptHandler()], level=standard_level, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        standard = logging.getLogger(name)
        handler = InterceptHandler()
        if name == "uvicorn.access":
            handler.addFilter(_SuccessfulHealthProbeFilter())
        standard.handlers = [handler]
        standard.setLevel(standard_level)
        standard.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.INFO)


def close_logging() -> None:
    logger.remove()
