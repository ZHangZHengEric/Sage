import logging
import sys

from loguru import logger

from common.utils.logging import _should_suppress_log_record, init_logging_base


def _uvicorn_access_record(path: str, status: int = 200) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="httptools_impl.py",
        lineno=484,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("172.21.0.10:53028", "GET", path, "1.1", status),
        exc_info=None,
    )


def test_suppresses_prometheus_metrics_uvicorn_access_log():
    assert _should_suppress_log_record(
        _uvicorn_access_record("/api/observability/metrics")
    )


def test_suppresses_health_uvicorn_access_log():
    assert _should_suppress_log_record(_uvicorn_access_record("/api/health"))


def test_suppresses_jaeger_auth_uvicorn_access_log():
    assert _should_suppress_log_record(
        _uvicorn_access_record("/api/observability/jaeger/auth")
    )


def test_suppresses_internal_task_uvicorn_access_log():
    assert _should_suppress_log_record(
        _uvicorn_access_record("/tasks/internal/due?limit=200")
    )
    assert _should_suppress_log_record(
        _uvicorn_access_record("/tasks/internal/spawn-due")
    )


def test_suppresses_active_sessions_stream_uvicorn_access_log():
    assert _should_suppress_log_record(
        _uvicorn_access_record("/api/stream/active_sessions")
    )


def test_keeps_internal_task_error_uvicorn_access_log():
    assert not _should_suppress_log_record(
        _uvicorn_access_record("/tasks/internal/due?limit=200", status=500)
    )


def test_keeps_regular_uvicorn_access_log():
    assert not _should_suppress_log_record(_uvicorn_access_record("/api/chat"))


def test_info_level_filters_debug_from_file_sink(tmp_path):
    init_logging_base(
        log_name="test-app",
        log_level="INFO",
        log_path=str(tmp_path),
    )
    try:
        logger.debug("debug-must-not-be-written")
        logger.info("info-must-be-written")

        contents = (tmp_path / "test-app_debug.log").read_text(encoding="utf-8")
        assert "debug-must-not-be-written" not in contents
        assert "info-must-be-written" in contents
    finally:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")


def test_enqueued_file_writes_do_not_run_on_caller_and_flush_in_order(tmp_path, monkeypatch):
    import json
    import threading
    from loguru._file_sink import FileSink
    caller = threading.get_ident()
    release = threading.Event()
    writes = []
    original = FileSink.write
    def slow_write(sink, message):
        writes.append(threading.get_ident())
        assert release.wait(1), 'log write blocked caller before release'
        return original(sink, message)
    monkeypatch.setattr(FileSink, 'write', slow_write)
    init_logging_base(log_name='queued', log_path=str(tmp_path), enqueue=True)
    try:
        logger.bind(session_id='session', request_id='request').info('first')
        logger.bind(session_id='session', request_id='request').info('second')
        release.set()
        logger.complete()
        records = [json.loads(s) for s in (tmp_path/'queued_info.log').read_text().splitlines()]
        assert [r['msg'] for r in records] == ['first', 'second']
        assert all(r['session_id']=='session' and r['requestId']=='request' for r in records)
        assert writes and all(t != caller for t in writes)
    finally:
        release.set()
        logger.remove()
        logger.add(sys.stderr, level='DEBUG')
