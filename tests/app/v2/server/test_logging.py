import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sagents.v2.runtime.observability.provider import create_observability_provider
from sagents.v2.runtime.observability.contracts import LogRecord


def test_debug_keeps_application_logs_and_dependency_warnings():
    # Isolate process-wide logger setup from pytest's own logging handlers.
    result = subprocess.run(
        [sys.executable, "-c", """
import logging
from app.v2.server.observability.logging import LoggingSettings, init_logging

init_logging(LoggingSettings(level='debug'), service_name='sage-server')
for name in ('httpx', 'httpcore', 'httpx2', 'httpcore2.http11', 'openai._base_client',
             'mcp.client.streamable_http', 'a2a.utils.telemetry', 'aiomysql',
             'redis.asyncio.connection'):
    logger = logging.getLogger(name)
    logger.debug('dependency debug')
    logger.warning('dependency warning')
logging.getLogger('sage.test').debug('application debug')
"""],
        capture_output=True,
        text=True,
        check=True,
    )
    messages = [json.loads(line)["message"] for line in result.stdout.splitlines()]
    assert messages == ["dependency warning"] * 9 + ["application debug"]


@pytest.mark.parametrize("event", [
    "agent.state.commit", "session.redis.commit", "agent.preparation.completed",
    "server.admission.phase", "session.mysql.archived",
])
def test_routine_debug_keeps_slow_and_failed_operations(event, tmp_path, capsys):
    captured = []
    provider = create_observability_provider("sage.observability.local", {
        "log_level": "debug", "log_root": str(tmp_path), "log_filename": "sage-server.log",
    })
    sink = provider.logs
    sink.evidence = SimpleNamespace(write=captured.append)
    samples = [
        ("fast", "debug", {"duration_ms": 99.999, "outcome": "completed"}),
        ("fast storage", "debug", {"duration_ms": 3}),
        ("slow", "debug", {"duration_ms": 100, "outcome": "completed"}),
        ("failed", "debug", {"duration_ms": 1, "outcome": "failed"}),
        ("warning", "warning", {"duration_ms": 1}),
        ("unknown duration", "debug", {}),
    ]
    try:
        for message, level, attributes in samples:
            sink.write(LogRecord(
                event=event, message=message, level=level, component="sage.test",
                run_id="run", session_id="session", correlation_id="request",
                attributes=attributes,
            ))
    finally:
        sink.close()
    stdout = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    on_disk = [json.loads(line) for line in (tmp_path / "sage-server.log").read_text().splitlines()]
    expected = ["slow", "failed", "warning", "unknown duration"]
    assert [row["message"] for row in stdout] == expected
    assert on_disk == stdout
    assert [row.message for row in captured] == expected
    assert all(row["correlation_id"] == "request" for row in stdout)


def test_fast_performance_events_are_preserved(capsys):
    from sagents.v2.runtime.observability.performance import EVENTS

    sink = create_observability_provider("sage.observability.local", {"log_level": "debug"}).logs
    for event in sorted(EVENTS):
        sink.write(LogRecord(
            event=event, message=event, level="debug", component="sage.test",
            attributes={"duration_ms": 1, "outcome": "completed"},
        ))
    sink.close()
    assert {json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()} == EVENTS
