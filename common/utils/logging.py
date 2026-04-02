"""Shared logging configuration using loguru.

Both server and desktop use this module by providing:
- log_name / log_level / log_path
- a get_request_id() callable (or None)
- whether to use SafeStdout for stdout sink
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger


class InterceptHandler(logging.Handler):
    """Bridge standard logging to loguru.

    Used to intercept FastAPI / uvicorn / sagents logs.
    """

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        # Map logging level to loguru level
        try:
            level: Any = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        record_name = record.name or ""
        record_path = getattr(record, "pathname", "") or ""
        record_filename = getattr(record, "filename", "") or ""
        normalized_path = record_path.replace(os.sep, "/")

        # Downgrade noisy libs to DEBUG
        if record_name.startswith("apscheduler") and level == "INFO":
            level = "DEBUG"
        if record_name.startswith("httpx") and level == "INFO":
            level = "DEBUG"
        if ("httptools_impl" in normalized_path or "httptools_impl" in record_filename) and level == "INFO":
            level = "DEBUG"
        if ("streamable_http" in normalized_path or "streamable_http" in record_filename) and level == "INFO":
            level = "DEBUG"

        # Find caller
        frame = logging.currentframe()
        depth = 1
        if frame:
            frame = frame.f_back
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        payload = {"logger_name": record.name}
        if hasattr(record, "session_id") and getattr(record, "session_id") != "NO_SESSION":
            payload["session_id"] = record.session_id
        if hasattr(record, "caller_filename"):
            payload["file.name"] = record.caller_filename
        if hasattr(record, "caller_lineno"):
            payload["line"] = record.caller_lineno

        logger.opt(depth=depth, exception=record.exc_info).bind(**payload).log(
            level, record.getMessage()
        )


class SafeStdout:
    """Wrapper for stdout that suppresses BrokenPipeError.

    Prevents "BrokenPipeError: [Errno 32] Broken pipe" when parent closes the pipe.
    """

    def write(self, message: str) -> None:  # type: ignore[override]
        try:
            sys.stdout.write(message)
            sys.stdout.flush()
        except (BrokenPipeError, ValueError, OSError):
            # Pipe is broken or file closed; ignore
            pass
        except Exception:
            pass

    def flush(self) -> None:  # type: ignore[override]
        try:
            sys.stdout.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass
        except Exception:
            pass


def init_logging_base(
    *,
    log_name: str = "app",
    log_level: str = "DEBUG",
    log_path: str = "./logs",
    get_request_id: Optional[Callable[[], Optional[str]]] = None,
    use_safe_stdout: bool = False,
) -> None:
    """Initialize loguru logging shared by server and desktop.

    - log_name: base name for log files
    - log_level: minimum level for stdout
    - log_path: directory for log files (created if missing)
    - get_request_id: callable to fetch current request id, or None
    - use_safe_stdout: use SafeStdout wrapper for stdout sink
    """

    logger.remove()  # Remove default handler

    def formatting_payload(record: Dict[str, Any]) -> str:
        extra = record["extra"]
        file_path = extra.get("rel_path") or record["file"].path
        file_value = f"{file_path}:{record['line']}"
        payload = OrderedDict()
        payload["level"] = record["level"].name
        payload["time"] = record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        payload["file"] = file_value
        payload["msg"] = record["message"]
        request_id = extra.get("request_id")
        if request_id:
            payload["requestId"] = request_id
        session_id = extra.get("session_id")
        if session_id:
            payload["seesion_id"] = session_id
        if record.get("exception"):
            payload["exception"] = str(record["exception"])
        return json.dumps(payload, ensure_ascii=False)

    # Patcher: inject request_id, path, JSON message
    def patcher(record: Dict[str, Any]) -> None:
        if get_request_id is not None:
            record["extra"]["request_id"] = get_request_id()
        if "message" in record and isinstance(record["message"], str):
            record["message"] = re.sub(r"\s+", " ", record["message"]).strip()

        file_path = record["extra"].get("file.name")
        if not file_path:
            file_path = record["file"].path
        try:
            rel_path = os.path.relpath(file_path, os.getcwd())
            parts = rel_path.split(os.sep)
            if len(parts) > 2:
                rel_path = os.path.join(*parts[-2:])
        except Exception:
            rel_path = os.path.basename(file_path)
        record["extra"]["rel_path"] = rel_path
        if "file.name" in record["extra"]:
            record["file"].name = record["extra"]["file.name"]
        if "line" in record["extra"]:
            record["line"] = record["extra"]["line"]

        record["message"] = formatting_payload(record)

    logger.configure(patcher=patcher)

    # stdout sink
    stdout_sink: Any = SafeStdout() if use_safe_stdout else sys.stdout
    logger.add(stdout_sink, level=log_level, format="{message}")

    # Ensure log directory exists
    log_dir = Path(log_path)
    log_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "rotation": "100MB",
        "retention": 20,
        "compression": "zip",
        "encoding": "utf8",
        "format": "{message}",
    }

    logger.add(log_dir / f"{log_name}_debug.log", level="DEBUG", **params)
    logger.add(log_dir / f"{log_name}_info.log", level="INFO", **params)
    logger.add(log_dir / f"{log_name}_error.log", level="ERROR", **params)

    # Access log file
    access_params = {
        "rotation": "10MB",
        "retention": 10,
        "compression": "zip",
        "encoding": "utf8",
        "format": "{message}",
    }
    logger.add(
        log_dir / f"{log_name}_access.log",
        level="INFO",
        filter=lambda record: "REQUEST_START" in record["message"]
        or "REQUEST_END" in record["message"]
        or record["extra"].get("logger_name") == "uvicorn.access",
        **access_params,
    )

    # Intercept std logging
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)

    # Capture FastAPI / uvicorn / sagents logs
    fastapi_loggers = [
        "fastapi",
        "fastapi.app",
        "fastapi.middleware",
        "uvicorn.access",
        "sage",
    ]
    for logger_name in fastapi_loggers:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False


__all__ = [
    "InterceptHandler",
    "SafeStdout",
    "init_logging_base",
]
