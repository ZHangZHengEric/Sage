import importlib
import logging
import types


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
    assert not any(
        isinstance(handler, logging.FileHandler) for handler in logger.logger.handlers
    )
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


def test_logger_error_can_suppress_traceback_for_handled_exception(
    monkeypatch, tmp_path
):
    logger_module = _load_logger_module(monkeypatch)
    logger = logger_module.Logger(log_dir=str(tmp_path))
    recorded = []
    monkeypatch.setattr(
        logger,
        "_log",
        lambda level, message, session_id=None, **kwargs: recorded.append(
            (level, message, session_id, kwargs)
        ),
    )

    try:
        raise ValueError("provider rejected request")
    except ValueError:
        logger.error("handled provider rejection", exc_info=False)

    assert recorded == [
        ("error", "handled provider rejection", None, {}),
    ]

    logger.stop_periodic_cleanup()
    logger_module.Logger._close_handlers(logger.logger)
    logger_module.Logger._initialized = False
    logger_module.Logger._instance = None


def test_session_logger_is_unregistered_and_cannot_be_recreated_after_close(
    monkeypatch, tmp_path
):
    logger_module = _load_logger_module(monkeypatch)
    monkeypatch.delenv("SAGE_DISABLE_SAGENTS_FILE_LOGGING", raising=False)

    class FakeStore:
        def append_session_log(self, _session_id, _text):
            return ""

    live_sessions = {
        "finished-session": types.SimpleNamespace(
            session_context=types.SimpleNamespace(storage=FakeStore()),
            status=types.SimpleNamespace(value="running"),
        )
    }
    fake_manager = types.SimpleNamespace(
        get_live_session=lambda session_id: live_sessions.get(session_id)
    )

    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    logger = logger_module.Logger(log_dir=str(tmp_path / "main-logs"))
    logger_name = "sage_session_finished-session"
    try:
        session_logger = logger._get_session_logger("finished-session")
        assert session_logger is not None
        assert logger_name in logging.Logger.manager.loggerDict

        live_sessions.clear()
        logger.cleanup_session_logger("finished-session")

        assert "finished-session" not in logger.session_loggers
        assert logger_name not in logging.Logger.manager.loggerDict
        assert logger._get_session_logger("finished-session") is None
        assert logger_name not in logging.Logger.manager.loggerDict
    finally:
        logger.cleanup_session_logger("finished-session")
        logger.stop_periodic_cleanup()
        logger_module.Logger._close_handlers(logger.logger)
        logger_module.Logger._initialized = False
        logger_module.Logger._instance = None


def test_terminal_session_cannot_create_file_logger(monkeypatch, tmp_path):
    logger_module = _load_logger_module(monkeypatch)
    monkeypatch.delenv("SAGE_DISABLE_SAGENTS_FILE_LOGGING", raising=False)

    terminal_session = types.SimpleNamespace(
        session_context=types.SimpleNamespace(session_workspace=str(tmp_path)),
        status=types.SimpleNamespace(value="completed"),
    )
    fake_manager = types.SimpleNamespace(
        get_live_session=lambda _session_id: terminal_session
    )
    import sagents.session_runtime

    monkeypatch.setattr(
        sagents.session_runtime,
        "get_global_session_manager",
        lambda: fake_manager,
    )

    logger = logger_module.Logger(log_dir=str(tmp_path / "main-logs"))
    try:
        assert logger._get_session_logger("terminal-session") is None
        assert "sage_session_terminal-session" not in logging.Logger.manager.loggerDict
    finally:
        logger.cleanup_session_logger("terminal-session")
        logger.stop_periodic_cleanup()
        logger_module.Logger._close_handlers(logger.logger)
        logger_module.Logger._initialized = False
        logger_module.Logger._instance = None
