import importlib
import logging


def _load_logger_module(monkeypatch):
    monkeypatch.setenv("SAGE_DISABLE_SAGENTS_FILE_LOGGING", "1")
    logger_module = importlib.import_module("sagents.utils.logger")
    _reset_sage_logger(logger_module)
    return logger_module


def _reset_sage_logger(logger_module):
    if getattr(logger_module, "logger", None) is not None:
        logger_module.logger.stop_periodic_cleanup()
    logger_module.Logger._close_handlers(logging.getLogger("sage"))
    logger_module.Logger._initialized = False
    logger_module.Logger._instance = None
    logger_module.Logger._cleanup_timer = None


def test_logger_skips_framework_file_handlers_when_disabled(monkeypatch, tmp_path):
    logger_module = _load_logger_module(monkeypatch)
    monkeypatch.setenv("SAGE_DISABLE_SAGENTS_FILE_LOGGING", "1")

    logger = logger_module.Logger(log_dir=str(tmp_path))

    assert logger.file_logging_enabled is False
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.logger.handlers)
    assert not (tmp_path / "sage_debug.log").exists()

    logger.stop_periodic_cleanup()
    logger_module.Logger._close_handlers(logger.logger)
    logger_module.Logger._initialized = False
    logger_module.Logger._instance = None


def test_logger_keeps_framework_file_handlers_by_default(monkeypatch, tmp_path):
    logger_module = _load_logger_module(monkeypatch)
    monkeypatch.delenv("SAGE_DISABLE_SAGENTS_FILE_LOGGING", raising=False)

    logger = logger_module.Logger(log_dir=str(tmp_path))

    assert logger.file_logging_enabled is True
    file_names = {
        handler.baseFilename.rsplit("/", 1)[-1]
        for handler in logger.logger.handlers
        if isinstance(handler, logging.FileHandler)
    }
    assert "sage_debug.log" in file_names

    logger.stop_periodic_cleanup()
    logger_module.Logger._close_handlers(logger.logger)
    logger_module.Logger._initialized = False
    logger_module.Logger._instance = None
