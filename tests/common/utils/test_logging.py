import logging

from common.utils.logging import _should_suppress_log_record


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
