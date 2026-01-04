import sys
import os
import logging
from loguru import logger

from pathlib import Path
from .context import get_request_id


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

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).bind(
            logger_name=record.name
        ).log(level, record.getMessage())


def init_logging(log_name="app", log_level="DEBUG"):
    """
    Initializes the Loguru logger with custom settings.

    Args:
        log_name (str, optional): The base name for log files. Defaults to "app".
        log_level (str, optional): The minimum logging level. Defaults to "DEBUG".
    """

    _format = (
        "{time:YYYY-MM-DD HH:mm:ss,SSS} - {level} - [{extra[request_id]}] - [{file.name}:{line}] - "
        "{message}"
    )

    logger.remove()  # Remove default handler

    # Configure patcher to automatically inject request_id
    def patcher(record):
        record["extra"]["request_id"] = get_request_id()

    logger.configure(patcher=patcher)

    logger.add(sys.stdout, level="INFO", format=_format)

    params = {
        "rotation": "20MB",
        "retention": 20,
        "compression": "zip",
        "encoding": "utf8",
        "format": _format,
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
        access_format = "{time:YYYY-MM-DD HH:mm:ss,SSS} - {level} - [{extra[request_id]}] - [{file.name}:{line}] - {message}"
        access_params = {
            "rotation": "10MB",
            "retention": 10,
            "compression": "zip",
            "encoding": "utf8",
            "format": access_format,
        }
        logger.add(
            Path(LOG_PATH) / f"{log_name}_access.log",
            level="INFO",
            filter=lambda record: "REQUEST_START" in record["message"]
            or "REQUEST_END" in record["message"]
            or record["extra"].get("logger_name") == "uvicorn.access",
            **access_params,
        )

    # 拦截标准日志并转发到 Loguru
    # 使用 INFO 级别以减少内部库的调试日志
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    # 接管 FastAPI 相关 logger
    fastapi_loggers = [
        "fastapi",
        "fastapi.app",
        "fastapi.middleware",
        # 如果有其他模块也可以添加
    ]

    for logger_name in fastapi_loggers:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False
        
    # 显式接管 uvicorn 的日志记录器
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False
