"""Run against a disposable SQL database when SAGE_V2_TEST_SERVER_SQL_URL is set."""

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.import_sqlite import import_diagnostics, import_self_configuration
from app.v2.server.database.schema import create_host_schema
from app.v2.server.observability.diagnostics import DatabaseDiagnostics
from app.v2.server.self_configuration.repository import DatabaseSelfConfigurationStore
from sagents.v2.agent.self_configuration.store import SqliteSelfConfigurationStore
from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord
from sagents.v2.runtime.observability.plugins.sqlite import SessionDiagnostics


@pytest.fixture
async def database(tmp_path):
    url = os.environ.get("SAGE_V2_TEST_SERVER_SQL_URL", f"sqlite+aiosqlite:///{tmp_path}/server.db")
    database = Database(DatabaseSettings(url=url))
    await database.start()
    try:
        await create_host_schema(database)
        yield database
    finally:
        await database.stop()


async def test_self_configuration_import_preserves_receipts_and_serializes_concurrent_runs(database, tmp_path):
    owner = uuid4().hex
    path = tmp_path / "self-configuration.sqlite3"
    old = SqliteSelfConfigurationStore(path)
    await old.read(owner, "original")
    result = await old.commit(owner, "original", "old-operation", "fingerprint", 0, {}, {}, system_prompt="old")
    assert await import_self_configuration(database, path) == 3
    assert await import_self_configuration(database, path) == 3

    first = DatabaseSelfConfigurationStore(database)
    second = DatabaseSelfConfigurationStore(database)
    assert await first.read(owner, "original", create=False) == await old.read(owner, "original")
    assert await first.commit(owner, "original", "old-operation", "fingerprint", 0, {}, {}) == result

    await asyncio.gather(first.read(owner, "run-a"), second.read(owner, "run-b"))
    await asyncio.gather(
        first.commit(owner, "run-a", "op-a", "a", 1, {"a": {"content": "alpha"}}, {}),
        second.commit(owner, "run-b", "op-b", "b", 1, {"b": {"content": "beta"}}, {}),
    )
    latest = await first.read(owner, "latest")
    assert latest["skills"] == {"a": {"content": "alpha"}, "b": {"content": "beta"}}
    assert latest["revision"] == 3
    with pytest.raises(ValueError, match="conflicts"):
        await second.commit(owner, "run-a", "op-a", "changed", 1, {}, {})
    await first.commit(owner, "run-a", "prompt-a", "x", 2, {}, {}, system_prompt="new")
    with pytest.raises(ValueError, match="another Run"):
        await second.commit(owner, "run-b", "prompt-b", "y", 2, {}, {}, system_prompt="stale")
    assert await second.receipt(owner, "run-b", "prompt-b") is None


async def test_diagnostics_import_and_async_capture_keep_large_evidence_and_run_scope(database, tmp_path):
    session, run = uuid4().hex, uuid4().hex
    request = SimpleNamespace(run_id=run, request_id="request", metadata={})
    directory = tmp_path / "old-diagnostics"
    old = SessionDiagnostics(directory)
    old.write(LogRecord(level=LogLevel.INFO, event="legacy", message="old", component="test",
                        session_id=session, run_id=run))
    await old.close()
    assert await import_diagnostics(database, directory / "evidence.sqlite3") == 1
    assert await import_diagnostics(database, directory / "evidence.sqlite3") == 1

    sink = DatabaseDiagnostics(database)
    try:
        await sink.begin_model_request(
            session_id=session, request=request, provider={},
            wire_request={"messages": ["你好"], "api_key": "secret"},
        )
        delta = "x" * (4 * 1024 * 1024 + 1024)
        stream = {"wire_events": [{"delta": delta}], "normalized_events": [{"text": delta}]}
        await sink.record_model_stream(session_id=session, request=request, evidence=stream)
        await sink.complete_model_request(
            session_id=session, request=request,
            response=SimpleNamespace(model_dump=lambda **_: {"text": "complete"}),
        )
        sink.write(LogRecord(level=LogLevel.INFO, event="agent.run.started", message="new", component="test",
                             session_id=session, run_id=run))
        evidence = await sink.export_evidence(session, {run})
        assert [row["message"] for row in evidence["logs"]] == ["old", "new"]
        record = evidence["models"][0]
        assert record["status"] == "completed"
        assert record["request"]["messages"] == ["你好"]
        assert record["request"]["api_key"] != "secret"
        assert record["stream"] == stream
        assert (await sink.export_evidence("other-session", {run}))["models"] == []
        report = await sink.report(start=0, end=10**10)
        assert run in {row["run_id"] for row in report["runs"]}
        sink.max_logs_per_run = 2
        sink.write(LogRecord(level=LogLevel.INFO, event="third", message="latest", component="test",
                             session_id=session, run_id=run))
        trimmed = await sink.export_evidence(session, {run})
        assert [row["message"] for row in trimmed["logs"]] == ["new", "latest"]
        assert trimmed["dropped_logs"] == 1 and isinstance(trimmed["dropped_logs"], int)
        assert sink.capture_failures == 0
    finally:
        await sink.close()
