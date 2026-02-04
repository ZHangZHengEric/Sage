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

        # 降级 apscheduler 的 INFO 日志到 DEBUG
        if record.name.startswith("apscheduler") and level == "INFO":
            level = "DEBUG"

        # 降级 httpx 的 INFO 日志到 DEBUG
        if record.name.startswith("httpx") and level == "INFO":
            level = "DEBUG"

        # 降级 httptools_impl 的 INFO 日志到 DEBUG
        if record.name.startswith("http/httptools_impl") and level == "INFO":
            level = "DEBUG"
        # 降级 client/streamable_http 的 INFO 日志到 DEBUG
        if record.name.startswith("client/streamable_http") and level == "INFO":
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
        if hasattr(record, "session_id"):
            payload["session_id"] = record.session_id
        if hasattr(record, "caller_filename"):
            payload["file.name"] = record.caller_filename
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

    # Configure patcher to automatically inject request_id and process path
    def patcher(record):
        # Request ID
        record["extra"]["request_id"] = get_request_id()
        # Message normalization
        if "message" in record and isinstance(record["message"], str):
            record["message"] = re.sub(r"\s+", " ", record["message"]).strip()
        
        # Relative Path Handling
        # 1. Try to get path from InterceptHandler (file.name) or original record path
        file_path = record["extra"].get("file.name")
        if not file_path:
            file_path = record["file"].path

        # 2. Convert to relative path
        try:
            rel_path = os.path.relpath(file_path, os.getcwd())
            parts = rel_path.split(os.sep)
            if len(parts) > 2:
                rel_path = os.path.join(*parts[-2:])
        except Exception:
            rel_path = os.path.basename(file_path) # Fallback to basename

        record["extra"]["rel_path"] = rel_path

        # Override file.name and line if provided in extra (for InterceptHandler compatibility)
        if "file.name" in record["extra"]:
            record["file"].name = record["extra"]["file.name"]
        if "line" in record["extra"]:
            record["line"] = record["extra"]["line"]

    logger.configure(patcher=patcher)

    def formatting_func(record):
        fmt = "{time:YYYY-MM-DD HH:mm:ss,SSS} - {level} - "

        # Relative Path
        fmt += "[{extra[rel_path]}:{line}] "

        # Conditional Request ID
        if (
            record["extra"].get("request_id")
            and record["extra"].get("request_id") != "background"
        ):
            fmt += "[{extra[request_id]}] "
        fmt += "- {message} "
        fmt += "\n{exception}"
        return fmt

    logger.add(sys.stdout, level=log_level, format=formatting_func)

    params = {
        "rotation": "100MB",
        "retention": 20,
        "compression": "zip",
        "encoding": "utf8",
        "format": formatting_func,
    }
    LOG_PATH = "./logs"
    if not os.path.exists(LOG_PATH):
        os.mkdir(LOG_PATH)

    logger.add(Path(LOG_PATH) / f"{log_name}_debug.log", level="DEBUG", **params)
    logger.add(Path(LOG_PATH) / f"{log_name}_info.log", level="INFO", **params)
    logger.add(Path(LOG_PATH) / f"{log_name}_error.log", level="ERROR", **params)

    # 检查是否启用访问日志
    access_log_enabled = True
    if access_log_enabled:
        # 添加专门的访问日志文件
        access_params = {
            "rotation": "10MB",
            "retention": 10,
            "compression": "zip",
            "encoding": "utf8",
            "format": formatting_func,
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
