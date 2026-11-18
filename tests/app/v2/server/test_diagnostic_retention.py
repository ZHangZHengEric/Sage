"""Retention progress and independent SQL writers at the batch boundary."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.v2.server.database import Database
from app.v2.server.observability.diagnostics import DatabaseDiagnostics
from app.v2.server.observability.orm import expiry, models
from tests.app.v2.server.test_default_sql_storage import database as database


@pytest.fixture
async def retention_case(database, tmp_path):
    session, run = uuid4().hex, uuid4().hex
    now = datetime.now(timezone.utc).timestamp()
    sink = DatabaseDiagnostics(database, tmp_path / "evidence")
    sink._maintenance.cancel()
    await asyncio.gather(sink._maintenance, return_exceptions=True)
    sink.max_storage_bytes = 0

    async def seed(active=100, terminal=("completed", "failed"), *, tied=False):
        rows, deadlines = [], []
        statuses = [(f"active-{i:03}", "started") for i in range(active)]
        statuses += [(f"terminal-{i:03}", status) for i, status in enumerate(terminal)]
        for request_id, status in statuses:
            record = {
                "session_id": session, "run_id": run, "request_id": request_id,
                "status": status, "started_at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
                "request": {"message": request_id * 100},
            }
            compact = await asyncio.to_thread(sink.storage.pack, (session, run, request_id), record)
            rows.append({"session_id": session, "run_id": run, "request_id": request_id,
                         "payload": json.dumps(compact)})
            deadlines.append({"session_id": session, "run_id": run, "request_id": request_id,
                              "expires_at": now + (86400 if status == "started" or tied else 172800),
                              "summary_expires_at": now + 30 * 86400})
        async with database.transaction() as db:
            if rows:
                await db.execute(models.insert(), rows)
                await db.execute(expiry.insert(), deadlines)

    async def records():
        return {r["request_id"]: r for r in (await sink.export_evidence(session, {run}))["models"]}

    try:
        yield SimpleNamespace(sink=sink, seed=seed, records=records, now=now, session=session, run=run)
    finally:
        await sink.close()
        async with database.transaction() as db:
            await db.execute(delete(models).where(models.c.session_id == session))
            await db.execute(delete(expiry).where(expiry.c.session_id == session))


def assert_active_preserved(records, count):
    active = [r for name, r in records.items() if name.startswith("active-")]
    assert len(active) == count
    assert all(r["status"] == "started" and r.get("request") and not r.get("evidence_expired") for r in active)


@pytest.mark.parametrize("active_count", [0, 99, 100, 101, 250])
async def test_active_records_do_not_block_later_terminal_eviction(retention_case, active_count):
    case = retention_case
    await case.seed(active=active_count)
    assert await case.sink.prune(now=case.now) == 2
    assert await case.sink.prune(now=case.now) == 0
    records = await case.records()
    assert_active_preserved(records, active_count)
    for name in ("terminal-000", "terminal-001"):
        assert records[name]["evidence_expired_reason"] == "storage_budget"


@pytest.mark.parametrize("terminal_count", [100, 101, 205])
async def test_terminal_eviction_makes_progress_across_batches(retention_case, terminal_count):
    case = retention_case
    await case.seed(terminal=["completed", "failed"] * (terminal_count // 2) + ["completed"] * (terminal_count % 2), tied=True)
    remaining = terminal_count
    while remaining:
        expected = min(100, remaining)
        assert await case.sink.prune(now=case.now) == expected
        remaining -= expected
    assert await case.sink.prune(now=case.now) == 0
    records = await case.records()
    assert_active_preserved(records, 100)
    assert sum(bool(r.get("evidence_expired")) for r in records.values()) == terminal_count


@pytest.mark.parametrize("active_count", [0, 100])
async def test_only_active_records_can_remain_over_budget_without_expiring(retention_case, active_count):
    case = retention_case
    await case.seed(active=active_count, terminal=())
    assert await case.sink.prune(now=case.now) == 0
    assert await case.sink.prune(now=case.now) == 0
    assert_active_preserved(await case.records(), active_count)


async def test_active_prefix_does_not_cause_eviction_within_budget(retention_case):
    case = retention_case
    await case.seed()
    case.sink.max_storage_bytes = 1 << 30
    assert await case.sink.prune(now=case.now) == 0
    records = await case.records()
    assert_active_preserved(records, 100)
    assert all(r.get("request") and not r.get("evidence_expired") for r in records.values())


async def test_due_active_records_expire_at_exact_deadline_without_budget_pressure(database, retention_case):
    case = retention_case
    await case.seed(terminal=())
    case.sink.max_storage_bytes = 1 << 30
    async with database.transaction() as db:
        await db.execute(expiry.update().where(expiry.c.session_id == case.session,
                                               expiry.c.request_id == "active-000").values(expires_at=case.now))
    assert await case.sink.prune(now=case.now) == 1
    records = await case.records()
    assert records.pop("active-000")["evidence_expired_reason"] == "retention"
    assert_active_preserved(records, 99)


async def test_independent_maintainers_skip_active_prefix_and_share_budget(database, retention_case):
    case = retention_case
    await case.seed(tied=True)
    other_database = Database(database._settings)
    await other_database.start()
    other = DatabaseDiagnostics(other_database, case.sink.storage.root)
    other._maintenance.cancel()
    await asyncio.gather(other._maintenance, return_exceptions=True)
    try:
        async with database.session() as db:
            payloads = list(await db.scalars(select(models.c.payload).where(models.c.session_id == case.session)))
        usage = case.sink._file_usage(payloads)
        first_terminal = str(case.sink.storage.directory((case.session, case.run, "terminal-000")))
        budget = sum(usage.values()) - usage[first_terminal]
        case.sink.max_storage_bytes = other.max_storage_bytes = budget
        assert sum(await asyncio.gather(case.sink.prune(now=case.now), other.prune(now=case.now))) == 1
        assert sum(await asyncio.gather(case.sink.prune(now=case.now), other.prune(now=case.now))) == 0
        records = await case.records()
        assert_active_preserved(records, 100)
        assert records["terminal-000"]["evidence_expired_reason"] == "storage_budget"
        assert records["terminal-001"]["request"] and not records["terminal-001"].get("evidence_expired")
    finally:
        await other.close()
        await other_database.stop()


async def test_completion_writer_and_retention_both_make_progress(database, retention_case):
    case = retention_case
    await case.seed(terminal=("completed",))
    other_database = Database(database._settings)
    await other_database.start()
    other = DatabaseDiagnostics(other_database, case.sink.storage.root)
    other._maintenance.cancel()
    await asyncio.gather(other._maintenance, return_exceptions=True)
    try:
        async def complete():
            await other.complete_model_request(
                session_id=case.session,
                request=SimpleNamespace(run_id=case.run, request_id="active-000", metadata={}),
                response=SimpleNamespace(model_dump=lambda **_: {"text": "completed concurrently"}),
            )
            assert await other._flush()
        first, _ = await asyncio.gather(case.sink.prune(now=case.now), complete())
        assert first + await case.sink.prune(now=case.now) == 2
        records = await case.records()
        completed = records.pop("active-000")
        assert completed["status"] == "completed"
        assert completed["evidence_expired_reason"] == "storage_budget"
        assert_active_preserved(records, 99)
    finally:
        await other.close()
        await other_database.stop()


async def test_locked_active_prefix_does_not_block_terminal_eviction(database, retention_case):
    if database._engine.dialect.name not in {"mysql", "postgresql"}:
        pytest.skip("Requires SQL row locks; SQLite locks writes at the database level")
    case = retention_case
    await case.seed()
    other_database = Database(database._settings)
    await other_database.start()
    other = DatabaseDiagnostics(other_database, case.sink.storage.root)
    other._maintenance.cancel()
    await asyncio.gather(other._maintenance, return_exceptions=True)
    other.max_storage_bytes = 0
    try:
        # Model writers may hold these row locks. Maintenance must select and
        # reclaim the later terminal records while the locks are still held.
        async with database.transaction() as writer:
            await writer.execute(select(models.c.request_id).where(
                models.c.session_id == case.session,
                models.c.request_id.like("active-%"),
            ).with_for_update())
            assert await asyncio.wait_for(other.prune(now=case.now), 5) == 2
        assert_active_preserved(await case.records(), 100)
    finally:
        await other.close()
        await other_database.stop()
