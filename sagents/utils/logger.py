import atexit
import glob
import inspect
import logging
import os
import queue
import sys
import threading
import traceback
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, Optional


class Logger:
    _instance = None
    _initialized = False
    _cleanup_timer = None
    _cleanup_interval = 24 * 60 * 60  # 24h

    LOG_LEVELS = [
        ('debug', logging.DEBUG),
        ('info', logging.INFO),
        ('warning', logging.WARNING),
        ('error', logging.ERROR),
    ]

    CLEANUP_PATTERNS = [
        "sage_debug_*.log",
        "sage_info_*.log",
        "sage_warning_*.log",
        "sage_error_*.log",
        "sage_debug.log.*",
        "sage_info.log.*",
        "sage_warning.log.*",
        "sage_error.log.*",
        "sage_*.log.*",
        "sage_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].log",
    ]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self, log_dir: str = "logs"):
        if Logger._initialized:
            return

        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        # Async logging setup
        self._log_queue = queue.Queue()
        self._worker_thread = threading.Thread(target=self._log_worker, daemon=True)
        self._worker_thread.start()

        self.logger = self._create_main_logger()
        self.session_loggers: Dict[str, logging.Logger] = {}

        self._cleanup_old_logs()
        self._start_periodic_cleanup()

        atexit.register(self.shutdown)

        Logger._initialized = True

    def _log_worker(self):
        while True:
            try:
                record = self._log_queue.get()
                if record is None:
                    break
                self._handle_record(record)
                self._log_queue.task_done()
            except Exception:
                sys.stderr.write("Error in log worker:\n")
                traceback.print_exc(file=sys.stderr)

    def _handle_record(self, record):
        level = record["level"]
        message = record["message"]
        session_id = record["session_id"]
        filename = record["filename"]
        lineno = record["lineno"]

        extra = dict(
            caller_filename=filename,
            caller_lineno=lineno,
            session_id=session_id,
        )

        # Main logger
        getattr(self.logger, level)(message, extra=extra)

        # Session logger
        if session_id != "SYSTEM_LOG":
            try:
                getattr(self._get_session_logger(session_id), level)(
                    message,
                    extra={"caller_filename": filename, "caller_lineno": lineno}
                )
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # Initialization Helpers
    # ---------------------------------------------------------------------

    def _create_main_logger(self) -> logging.Logger:
        logger = logging.getLogger("sage")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.handlers.clear()

        # console handler
        logger.addHandler(self._create_console_handler())

        # file handlers
        for level_name, level_value in self.LOG_LEVELS:
            logger.addHandler(self._create_rotating_handler(level_name, level_value))

        return logger

    def _create_console_handler(self):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(self._create_formatter())
        return handler

    def _create_rotating_handler(self, level_name: str, level_value: int):
        log_file = os.path.join(self.log_dir, f"sage_{level_name}.log")

        handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8"
        )
        handler.setLevel(level_value)
        handler.setFormatter(self._create_formatter())
        handler.suffix = "_%Y%m%d"
        handler.namer = self._rotate_filename_namer
        return handler

    @staticmethod
    def _create_formatter():
        return logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(session_id)s] - '
            '[%(caller_filename)s:%(caller_lineno)d] - %(message)s'
        )

    @staticmethod
    def _rotate_filename_namer(default_name: str) -> str:
        # default:  sage_info.log._20241024
        if "._" in default_name:
            base, date = default_name.split("._")
            base_no_ext = base.replace(".log", "")
            return f"{base_no_ext}_{date}.log"
        return default_name

    # ---------------------------------------------------------------------
    # Cleanup Logic
    # ---------------------------------------------------------------------

    def _cleanup_old_logs(self):
        print("[LOG CLEANUP] Running initial cleanup...")
        one_month_ago = datetime.now() - timedelta(days=30)

        total_size = 0
        deleted = 0

        for pattern in self.CLEANUP_PATTERNS:
            for file in glob.glob(os.path.join(self.log_dir, pattern)):
                try:
                    stat = os.stat(file)
                    if datetime.fromtimestamp(stat.st_mtime) < one_month_ago:
                        total_size += stat.st_size
                        deleted += 1
                        os.remove(file)
                        print(f"[LOG CLEANUP] Deleted: {file}")
                except Exception as e:
                    print(f"[LOG CLEANUP] Failed to delete {file}: {e}")

        print(f"[LOG CLEANUP] Completed: {deleted} files deleted, {total_size} bytes freed")

    def _start_periodic_cleanup(self):
        if self._cleanup_timer:
            self._cleanup_timer.cancel()

        self._cleanup_timer = threading.Timer(
            self._cleanup_interval,
            self._periodic_cleanup_task
        )
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

        print("[LOG CLEANUP] Next periodic cleanup scheduled.")

    def _periodic_cleanup_task(self):
        print("[LOG CLEANUP] Periodic cleanup started...")
        self._cleanup_old_logs()
        self._start_periodic_cleanup()

    # ---------------------------------------------------------------------
    # Session Logic
    # ---------------------------------------------------------------------

    def _get_current_session_id(self) -> Optional[str]:
        try:
            from sagents.utils.session_local import session_manager
            session_id = session_manager.get_session_id()
            if session_id:
                return session_id

            import sagents.context.session_context as sc
            tid = threading.get_ident()

            for sid, ctx in sc._active_sessions.items():
                if getattr(ctx, "thread_id", None) == tid:
                    return sid
        except Exception:
            pass

        return None

    def _get_session_logger(self, session_id: str) -> logging.Logger:
        if session_id in self.session_loggers:
            return self.session_loggers[session_id]

        logger = logging.getLogger(f"sage_session_{session_id}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.handlers.clear()

        try:
            from sagents.context.session_context import get_session_context
            ctx = get_session_context(session_id)
            log_path = os.path.join(ctx.session_workspace, f"session_{session_id}.log")

            fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s - %(levelname)s - [%(caller_filename)s:%(caller_lineno)d] - %(message)s"
            ))
            logger.addHandler(fh)
        except Exception as e:
            print(f"[WARNING] Failed to create session logger for {session_id}: {e}")

        self.session_loggers[session_id] = logger
        return logger

    # ---------------------------------------------------------------------
    # Main Logging Entry
    # ---------------------------------------------------------------------

    def _log(self, level: str, message: str, explicit_session_id: Optional[str]):
        # get caller frame (faster than inspect.stack())
        frame = inspect.currentframe().f_back.f_back
        filename = os.path.basename(frame.f_code.co_filename)
        lineno = frame.f_lineno

        session_id = explicit_session_id or self._get_current_session_id() or "SYSTEM_LOG"

        # Put in queue
        self._log_queue.put({
            "level": level,
            "message": message,
            "filename": filename,
            "lineno": lineno,
            "session_id": session_id
        })

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def debug(self, msg, session_id=None): self._log("debug", msg, session_id)
    def info(self, msg, session_id=None): self._log("info", msg, session_id)
    def warning(self, msg, session_id=None): self._log("warning", msg, session_id)

    def error(self, msg, session_id=None):
        exc = sys.exc_info()
        if exc[0]:
            msg += "\nTraceback:\n" + "".join(traceback.format_exception(*exc))
        self._log("error", msg, session_id)

    def critical(self, msg, session_id=None):
        exc = sys.exc_info()
        if exc[0]:
            msg += "\nTraceback:\n" + "".join(traceback.format_exception(*exc))
        self._log("critical", msg, session_id)

    def shutdown(self):
        self._log_queue.put(None)
        self._worker_thread.join()

    def cleanup_session_logger(self, session_id: str):
        logger = self.session_loggers.get(session_id)
        if not logger:
            return
        for h in logger.handlers:
            h.close()
        logger.handlers.clear()
        del self.session_loggers[session_id]


# Global singleton
logger = Logger()
