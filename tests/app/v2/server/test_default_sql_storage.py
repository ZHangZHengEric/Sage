"""Run against a disposable SQL database when SAGE_V2_TEST_SERVER_SQL_URL is set."""

import asyncio
import os
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.database.import_sqlite import import_diagnostics, import_self_configuration
from app.v2.server.database.schema import create_host_schema
from app.v2.server.observability.diagnostics import DatabaseDiagnostics
from app.v2.server.observability.orm import events, timings
from app.v2.server.self_configuration.repository import DatabaseSelfConfigurationStore
from sagents.v2.agent.self_configuration.store import SqliteSelfConfigurationStore
from sagents.v2.contracts.common import utc_now
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

    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
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
        assert record["request"]["api_key"] == "secret"
        assert record["capture_mode"] == "raw"
        assert record["stream"] == stream
        token = utc_now()
        await sink.record_model_first_token(session_id=session, request=request, observed_at=token)
        updated, = (await sink.export_evidence(session, {run}))["models"]
        assert updated["first_token_at"] == token.isoformat()
        assert updated["stream"] == stream
        assert (await sink.export_evidence("other-session", {run}))["models"] == []
        sink.max_logs_per_run = 2
        sink.write(LogRecord(level=LogLevel.INFO, event="third", message="latest", component="test",
                             session_id=session, run_id=run))
        trimmed = await sink.export_evidence(session, {run})
        assert [row["message"] for row in trimmed["logs"]] == ["new", "latest"]
        assert trimmed["dropped_logs"] == 1 and isinstance(trimmed["dropped_logs"], int)
        assert sink.capture_failures == 0
    finally:
        await sink.close()


async def test_sql_timings_survive_a_saturated_evidence_queue(database, tmp_path):
    from app.v2.server.observability.performance import DatabasePerformance
    from sagents.v2.runtime.observability.performance.recording import ModelTiming, RunTimingStage

    session, run = uuid4().hex, uuid4().hex
    evidence = DatabaseDiagnostics(database, tmp_path / "evidence")
    performance = DatabasePerformance(database)
    evidence.max_pending_writes = 1
    now = utc_now()
    try:
        for _ in range(2):
            evidence.write(LogRecord(level=LogLevel.INFO, event="agent.run.started",
                                     message="log only", component="test", session_id=session, run_id=run))
        performance.record_stage(RunTimingStage(session, run, "agent.run.started", "1", now))
        model = ModelTiming(session, run, "model", "agent", None, now)
        performance.record_model(model)
        for _ in range(2):
            performance.record_model(ModelTiming(
                session, run, "model", "agent", None, now,
                first_token_at=now + timedelta(seconds=1),
                first_text_at=now + timedelta(seconds=2),
                ended_at=now + timedelta(seconds=3),
            ))
        report = await performance.report(start=now.timestamp() - 60, end=now.timestamp() + 60)
        assert run in {row["run_id"] for row in report["runs"]}
        async with database.session() as db:
            timing = (await db.execute(select(timings).where(timings.c.run_id == run))).mappings().one()
            rows = (await db.execute(select(events.c.event).where(events.c.run_id == run))).scalars().all()
        assert sorted(rows) == ["agent.run.started", "model.first_text", "model.request.started"]
        assert timing["first_token_at"] == now.timestamp() + 1
        assert timing["ended_at"] == now.timestamp() + 3
        assert evidence.capture_failures > 0
        assert performance.capture_failures == 0
    finally:
        await performance.close()
        await evidence.close()


async def test_pending_model_updates_share_one_evidence_slot(database, tmp_path):
    session, run = uuid4().hex, uuid4().hex
    request = SimpleNamespace(run_id=run, request_id="model", metadata={})
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    sink.max_pending_writes = 1
    args = dict(session_id=session, request=request)
    try:
        await sink.begin_model_request(**args, provider={}, wire_request={"model": "test"})
        await sink.record_model_first_token(**args, observed_at=utc_now())
        await sink.complete_model_request(
            **args, response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}),
        )
        await sink.record_model_stream(**args, evidence={"wire_events": [{"delta": "done"}]})
        record, = (await sink.export_evidence(session, {run}))["models"]
        assert sink.capture_failures == 0
        assert record["request"] == {"model": "test"}
        assert record["first_token_at"]
        assert record["response"]["text"] == "done"
        assert record["stream"]["wire_events"] == [{"delta": "done"}]
    finally:
        await sink.close()


async def test_coalesced_evidence_respects_memory_budget(database, tmp_path, monkeypatch):
    monkeypatch.setattr(DatabaseDiagnostics, "max_pending_evidence_bytes", 16 * 1024)
    session, run = uuid4().hex, uuid4().hex
    request = SimpleNamespace(run_id=run, request_id="model", metadata={})
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    args = dict(session_id=session, request=request)
    try:
        await sink.begin_model_request(**args, provider={}, wire_request={"model": "test"})
        await sink.record_model_stream(**args, evidence={"wire_events": [{"delta": "x" * (32 * 1024)}]})
        await sink.complete_model_request(
            **args, response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}),
        )
        record, = (await sink.export_evidence(session, {run}))["models"]
        assert sink.capture_failures == 1
        assert record["response"]["text"] == "done"
        assert "stream" not in record
    finally:
        await sink.close()


async def test_concurrent_model_patches_preserve_observed_times_and_terminal(database, tmp_path, monkeypatch):
    session, run = uuid4().hex, uuid4().hex
    args = dict(session_id=session, request=SimpleNamespace(run_id=run, request_id="model", metadata={}))
    first, second = DatabaseDiagnostics(database, tmp_path / "evidence"), DatabaseDiagnostics(database, tmp_path / "evidence")
    start = utc_now() - timedelta(seconds=4)
    token = start + timedelta(seconds=1)
    end = start + timedelta(seconds=3)
    try:
        await first.complete_model_request(
            **args, response=SimpleNamespace(model_dump=lambda **_: {"text": "ok"}), observed_at=end,
        )
        assert await first._flush()

        barrier = Barrier(2)
        def synchronize(merge):
            waited = False

            def interleave(changes, previous, *, digest):
                nonlocal waited
                if not waited:
                    waited = True
                    barrier.wait(timeout=2)
                return merge(changes, previous, digest=digest)

            return interleave

        for writer in (first, second):
            monkeypatch.setattr(writer, "_merge_model_payloads", synchronize(writer._merge_model_payloads))

        await first.begin_model_request(**args, provider={}, wire_request={"model": "first"}, observed_at=start)
        await second.record_model_first_token(**args, observed_at=token)
        assert all(await asyncio.gather(first._flush(), second._flush()))

        await first.begin_model_request(**args, provider={}, wire_request={"model": "late"})
        await first.fail_model_request(**args, error=RuntimeError("late"))
        record, = (await first.export_evidence(session, {run}))["models"]
        assert record["request"]["model"] == "first"
        assert record["status"] == "completed"
        assert record["started_at"] == start.isoformat()
        assert record["first_token_at"] == token.isoformat()
        assert record["completed_at"] == end.isoformat()
        assert first.capture_failures == second.capture_failures == 0
    finally:
        await asyncio.gather(first.close(), second.close())


async def test_tool_payload_is_available_in_sql_evidence_without_trace(database, tmp_path):
    from sagents.v2.runtime.observability.logs import ObservationLogs
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, READ_TOOL, completed, setup_loop, tool_call

    evidence = DatabaseDiagnostics(database, tmp_path / "evidence")
    output = []

    class LogOutput:
        def write(self, record):
            output.append(record)

    logs = ObservationLogs((LogOutput(),), evidence)
    tool_definition = READ_TOOL.model_copy(update={"input_schema": {
        **READ_TOOL.input_schema,
        "properties": {**READ_TOOL.input_schema["properties"], "api_key": {"type": "string"}},
    }})
    call = tool_call(arguments={"key": "answer", "api_key": "sk-private-tool-key"})
    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("", calls=(call,)),)),
        ScriptedModelStep(events=(completed("done"),)),
    ))
    try:
        _, handle, loop, _ = await setup_loop(model, tools=(tool_definition,), log_sink=logs)
        assert (await loop.execute(handle.run_id, CONTEXT)).state.value == "completed"
        exported = await evidence.export_evidence(handle.session_id, {handle.run_id})
        tool, = exported["tools"]
        assert tool["result_available"]
        assert tool["result"]["tool_call_id"] == tool["tool_call_id"]
        assert tool["arguments"]["api_key"] != "sk-private-tool-key"
        assert tool["operation_id"]
        log = next(record for record in output if record.event == "tool.call.completed")
        assert "arguments" not in log.attributes
        assert "execution_result" not in log.attributes
    finally:
        await evidence.close()


async def test_compressed_evidence_keeps_sql_small_and_preserves_all_parts(database, tmp_path):
    import json
    from app.v2.server.observability.orm import models

    session, run = uuid4().hex, uuid4().hex
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    request = SimpleNamespace(run_id=run, request_id="big", metadata={})
    args = dict(session_id=session, request=request)
    wire = {"messages": [{"role": "user", "content": "你好🌟" * 100000}]}
    stream = {"wire_events": [{"delta": "stream" * 100000}], "normalized_events": [{"delta": "out"}]}
    try:
        await sink.begin_model_request(**args, provider={}, wire_request=wire)
        assert await sink._flush()
        original_files = {p: p.stat().st_mtime_ns for p in sink.storage.root.glob("*/*/*.gz")}
        await sink.record_model_first_token(**args, observed_at=utc_now())
        assert await sink._flush()
        assert original_files == {p: p.stat().st_mtime_ns for p in original_files}
        await sink.complete_model_request(**args, response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}))
        assert await sink._flush()
        await sink.record_model_stream(**args, evidence=stream)
        evidence = await sink.export_evidence(session, {run})
        record, = evidence["models"]
        assert record["request"] == wire
        assert record["stream"] == stream
        assert record["response"] == {"text": "done"}
        async with database.session() as db:
            payload = await db.scalar(select(models.c.payload).where(models.c.session_id == session))
        assert len(payload.encode()) < 2048
        assert "messages" not in json.loads(payload)
        assert sum(p.stat().st_size for p in sink.storage.root.glob("*/*/*.gz")) < 20000
    finally:
        await sink.close()


async def test_legacy_migration_is_verified_idempotent_and_keeps_export(database, tmp_path):
    import json
    from app.v2.server.observability.maintenance import migrate_legacy
    from app.v2.server.observability.orm import models

    session, run = uuid4().hex, uuid4().hex
    original = {"session_id": session, "run_id": run, "request_id": "old", "status": "completed",
                "started_at": utc_now().isoformat(), "request": {"messages": ["original" * 10000]},
                "response": {"text": "done"}, "stream": {"wire_events": [{"delta": "hello"}]}}
    async with database.transaction() as db:
        await db.execute(models.insert().values(session_id=session, run_id=run, request_id="old", payload=json.dumps(original)))
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    try:
        before, = (await sink.export_evidence(session, {run}))["models"]
        assert await migrate_legacy(database, sink) == 1
        assert await migrate_legacy(database, sink) == 0
        after, = (await sink.export_evidence(session, {run}))["models"]
        assert before == after
    finally:
        await sink.close()


async def test_evidence_retention_preserves_failure_and_timing_until_30_days(database, tmp_path):
    from app.v2.server.observability.orm import models, expiry

    session, run = uuid4().hex, uuid4().hex
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    now = utc_now()
    try:
        for request_id, failed in (("success", False), ("failure", True)):
            args = dict(session_id=session, request=SimpleNamespace(run_id=run, request_id=request_id, metadata={}))
            await sink.begin_model_request(**args, provider={}, wire_request={"message": "keep me"}, observed_at=now)
            if failed:
                await sink.fail_model_request(**args, error=RuntimeError("failed"), observed_at=now)
            else:
                await sink.complete_model_request(**args, response=SimpleNamespace(model_dump=lambda **_: {"text": "ok"}), observed_at=now)
        await sink._flush()
        assert await sink.prune(now=now.timestamp() + 4 * 86400) == 1
        records = {r["request_id"]: r for r in (await sink.export_evidence(session, {run}))["models"]}
        assert records["success"]["evidence_expired"]
        assert "request" not in records["success"]
        assert records["failure"]["request"]["message"] == "keep me"
        assert await sink.prune(now=now.timestamp() + 8 * 86400) == 1
        records = (await sink.export_evidence(session, {run}))["models"]
        assert all(r["evidence_expired"] for r in records)
        assert await sink.prune(now=now.timestamp() + 31 * 86400) == 2
        async with database.session() as db:
            assert not list(await db.scalars(select(models.c.payload).where(models.c.session_id == session)))
            assert not list(await db.scalars(select(expiry.c.request_id).where(expiry.c.session_id == session)))
    finally:
        await sink.close()


async def test_budget_eviction_and_missing_blob_are_explicit(database, tmp_path):
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    session, run = uuid4().hex, uuid4().hex
    args = dict(session_id=session, request=SimpleNamespace(run_id=run, request_id="one", metadata={}))
    try:
        await sink.begin_model_request(**args, provider={}, wire_request={"message": "full"})
        await sink.complete_model_request(**args, response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}))
        assert (await sink.export_evidence(session, {run}))["models"][0]["response"]["text"] == "done"
        for path in sink.storage.root.glob("*/*/*.gz"):
            path.unlink()
        assert (await sink.export_evidence(session, {run}))["models"][0]["evidence_unavailable"]
        await sink.begin_model_request(**args, provider={}, wire_request={"message": "retry"}, observed_at=utc_now() - timedelta(seconds=60))
        await sink._flush()
        sink.max_storage_bytes = 0
        assert await sink.prune() == 1
        record, = (await sink.export_evidence(session, {run}))["models"]
        assert record["evidence_expired_reason"] == "storage_budget"
    finally:
        await sink.close()


async def test_compressed_evidence_survives_restart_and_gc_protects_current_parts(database, tmp_path):
    import os
    from app.v2.server.observability.evidence_storage import EvidenceStorage

    session, run = uuid4().hex, uuid4().hex
    root = tmp_path / "evidence"
    args = dict(session_id=session, request=SimpleNamespace(run_id=run, request_id="durable", metadata={}))
    first = DatabaseDiagnostics(database, root)
    await first.begin_model_request(**args, provider={}, wire_request={"messages": ["complete"]})
    await first.record_model_stream(**args, evidence={"wire_events": [{"delta": "partial before crash"}]})
    before = await first.export_evidence(session, {run})
    await first.close()
    storage = EvidenceStorage(root)
    orphan = storage.path((session, run, "unpublished"), storage.put((session, run, "unpublished"), {"old": True}))
    recent = storage.path((session, run, "staging"), storage.put((session, run, "staging"), {"new": True}))
    old = (utc_now() - timedelta(hours=2)).timestamp()
    os.utime(orphan, (old, old))
    for path in root.glob("*/*/*.gz"):
        if path != recent:
            os.utime(path, (old, old))
    second = DatabaseDiagnostics(database, root)
    try:
        assert await second.export_evidence(session, {run}) == before
        await second.prune()
        assert not orphan.exists()
        assert recent.exists()
        assert await second.export_evidence(session, {run}) == before
    finally:
        await second.close()


async def test_expired_diagnostics_export_explains_retention(database, tmp_path):
    import json
    from zipfile import ZipFile
    from app.v2.server.storage.downloads import prepare_session_export

    session, run = uuid4().hex, uuid4().hex
    now = utc_now()
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    args = dict(session_id=session, request=SimpleNamespace(run_id=run, request_id="expired", metadata={}))
    try:
        await sink.begin_model_request(**args, provider={}, wire_request={"prompt": "hello"}, observed_at=now)
        await sink.complete_model_request(**args, response=SimpleNamespace(model_dump=lambda **_: {"text": "done"}), observed_at=now)
        await sink._flush()
        await sink.prune(now=now.timestamp() + 4 * 86400)
        evidence = await sink.export_evidence(session, {run})
        output, _ = prepare_session_export(session, {run}, evidence)
        with output, ZipFile(output) as archive:
            manifest = json.loads(archive.read(session + "/manifest.json"))
            index = json.loads(archive.read(session + "/requests/index.json"))
            assert manifest["expired_model_request_ids"] == ["expired"]
            assert "expired" in manifest["evidence_availability"]["models"]["reason"]
            assert index[0]["evidence_expired"]
    finally:
        await sink.close()


async def test_batch_migration_does_not_publish_before_every_record_is_verified(database, tmp_path, monkeypatch):
    import json
    from app.v2.server.observability.maintenance import migrate_legacy
    from app.v2.server.observability.orm import models, expiry

    session, run = uuid4().hex, uuid4().hex
    rows = []
    for index in range(3):
        record = {"session_id": session, "run_id": run, "request_id": str(index),
                  "status": "completed", "started_at": utc_now().isoformat(),
                  "request": {"messages": ["完整正文" * 1000]}}
        rows.append({key: record[key] for key in ("session_id", "run_id", "request_id")} | {"payload": json.dumps(record)})
    async with database.transaction() as db:
        await db.execute(models.insert(), rows)
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    unpack = sink.storage.unpack
    def fail_second(key, record):
        if key[2] == "1":
            raise ValueError("injected verification failure")
        return unpack(key, record)
    try:
        monkeypatch.setattr(sink.storage, "unpack", fail_second)
        with pytest.raises(ValueError, match="injected verification failure"):
            await migrate_legacy(database, sink)
        async with database.session() as db:
            assert not list(await db.scalars(select(expiry.c.request_id).where(expiry.c.session_id == session)))
            payloads = list(await db.scalars(select(models.c.payload).where(models.c.session_id == session)))
            assert set(payloads) == {row["payload"] for row in rows}
        monkeypatch.setattr(sink.storage, "unpack", unpack)
        assert await migrate_legacy(database, sink) == 3
        assert await migrate_legacy(database, sink) == 0
    finally:
        await sink.close()


async def test_gc_tolerates_another_process_collecting_the_same_file(database, tmp_path, monkeypatch):
    from pathlib import Path

    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    key = (uuid4().hex, "r", "m")
    digest = sink.storage.put(key, {"orphan": True})
    victim = sink.storage.path(key, digest)
    stat = Path.stat
    calls = 0
    def concurrent_stat(path, *args, **kwargs):
        nonlocal calls
        if path == victim:
            calls += 1
            if calls == 2:
                victim.unlink()
                raise FileNotFoundError(str(path))
        return stat(path, *args, **kwargs)
    try:
        monkeypatch.setattr(Path, "stat", concurrent_stat)
        assert not sink._file_usage()
        assert not victim.exists()
        monkeypatch.setattr(Path, "stat", stat)
        digest = sink.storage.put(key, {"second orphan": True})
        victim = sink.storage.path(key, digest)
        calls = 0
        monkeypatch.setattr(Path, "stat", concurrent_stat)
        sink._remove_expired_files([])
        assert not victim.exists()
    finally:
        monkeypatch.setattr(Path, "stat", stat)
        await sink.close()
