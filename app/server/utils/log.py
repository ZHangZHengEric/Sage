import json
from collections import OrderedDict
import logging
import os
import re
import sys
from pathlib import Path

from loguru import logger

from ..core.context import get_request_id


class InterceptHandler(logging.Handler):
    """
    Default handler from examples in loguru documentation.
    See https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging
    """

    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        record_name = record.name or ""
        record_path = getattr(record, "pathname", "") or ""
        record_filename = getattr(record, "filename", "") or ""
        normalized_path = record_path.replace(os.sep, "/")
 
        # 降级 apscheduler 的 INFO 日志到 DEBUG
        if record_name.startswith("apscheduler") and level == "INFO":
            level = "DEBUG"

        # 降级 httpx 的 INFO 日志到 DEBUG
        if record_name.startswith("httpx") and level == "INFO":
            level = "DEBUG"

        # 降级 httptools_impl 的 INFO 日志到 DEBUG
        if (
            ("httptools_impl" in normalized_path or "httptools_impl" in record_filename)
            and level == "INFO"
        ):
            level = "DEBUG"
        # 降级 client/streamable_http 的 INFO 日志到 DEBUG
        if (
            ("streamable_http" in normalized_path or "streamable_http" in record_filename)
            and level == "INFO"
        ):
            level = "DEBUG"
        
        # Find caller from where originated the logged message
        frame = logging.currentframe()
        depth = 1

        # Skip the InterceptHandler.emit frame itself
        if frame:
            frame = frame.f_back

        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        payload = {"logger_name": record.name}
        if hasattr(record, "session_id") and record.session_id != "NO_SESSION":
            payload["session_id"] = record.session_id
        if hasattr(record, "caller_filename"):
            payload["file"] = record.caller_filename
        if hasattr(record, "caller_lineno"):
            payload["line"] = record.caller_lineno
        logger.opt(depth=depth, exception=record.exc_info).bind(**payload).log(level, record.getMessage())


def init_logging(log_name="app", log_level="DEBUG"):
    """
    Initializes the Loguru logger with custom settings.

    Args:
        log_name (str, optional): The base name for log files. Defaults to "app".
        log_level (str, optional): The minimum logging level. Defaults to "DEBUG".
    """

    logger.remove()  # Remove default handler

    def formatting_payload(record):
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

    # Configure patcher to automatically inject request_id, path and JSON message
    def patcher(record):
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

    logger.add(sys.stdout, level=log_level, format="{message}")

    params = {
        "rotation": "100MB",
        "retention": 20,
        "compression": "zip",
        "encoding": "utf8",
        "format": "{message}",
    }
    LOG_PATH = "./logs"
    if not os.path.exists(LOG_PATH):
        os.mkdir(LOG_PATH)

    logger.add(Path(LOG_PATH) / f"{log_name}_debug.log", level="DEBUG", **params)
    logger.add(Path(LOG_PATH) / f"{log_name}_info.log", level="INFO", **params)
    logger.add(Path(LOG_PATH) / f"{log_name}_error.log", level="ERROR", **params)

    # 添加专门的访问日志文件
    access_params = {
        "rotation": "10MB",
        "retention": 10,
        "compression": "zip",
        "encoding": "utf8",
        "format": "{message}",
    }
    logger.add(
        Path(LOG_PATH) / f"{log_name}_access.log",
        level="INFO",
        filter=lambda record: "REQUEST_START" in record["message"]
        or "REQUEST_END" in record["message"]
        or record["extra"].get("logger_name") == "uvicorn.access",
        **access_params,
    )
    # 拦截标准日志
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)


    # 接管 FastAPI 和 sagents 日志
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
