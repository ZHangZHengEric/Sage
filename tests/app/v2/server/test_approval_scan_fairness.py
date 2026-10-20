"""An approval maintenance round must finish despite new thread arrivals."""
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.v2.server.bootstrap import ServerHost
from app.v2.server.conversations.runs import RunService
from app.v2.server.conversations.orm import ThreadRow
from app.v2.server.conversations.repository import DatabaseThreadIndex
from sagents.v2.contracts.run_state import RunState


class GrowingThreads:
    def __init__(self):
        self.rows = [SimpleNamespace(thread_id=f"t{i:06}", user_id="owner") for i in range(201)]
        self.bounds = []

    async def scan_snapshot(self):
        return max(row.thread_id for row in self.rows), len(self.rows)

    async def scan(self, *, limit, cursor, through=None):
        from app.v2.server.conversations.records import parse_thread_cursor, thread_cursor
        values = parse_thread_cursor(cursor, scan=True)
        rows = sorted((row for row in self.rows if (not values or row.thread_id > values[0])
                       and (through is None or row.thread_id <= through)), key=lambda row: row.thread_id)
        self.bounds.append(through)
        return SimpleNamespace(items=rows[:limit], next_cursor=thread_cursor(rows[limit - 1], scan=True)
                               if len(rows) > limit else None)

    def append(self, count):
        start = len(self.rows)
        self.rows.extend(SimpleNamespace(thread_id=f"t{i:06}", user_id="owner")
                         for i in range(start, start + count))


@pytest.mark.asyncio
@pytest.mark.parametrize("insert_within_bound", [False, True])
async def test_old_approval_is_revisited_while_new_larger_thread_ids_keep_arriving(insert_within_bound):
    threads = GrowingThreads()
    if insert_within_bound:
        threads.rows.append(SimpleNamespace(thread_id="z-last-existing", user_id="owner"))
    expired = set()

    async def suspended(ids):
        return expired.intersection(ids)

    async def read_session_views(contexts, **options):
        return {sid: (SimpleNamespace(
            run=SimpleNamespace(run_id="waiting", state=RunState.SUSPENDED, revision=3),
            suspension=SimpleNamespace(interaction_id="i"), interaction=SimpleNamespace(),
            command=object(),
        ),) for sid in contexts}
    access = SimpleNamespace(read_session_views=read_session_views)
    service = RunService(application=SimpleNamespace(runtime=SimpleNamespace(
        session_store=SimpleNamespace(filter_suspended_session_ids=suspended))),
        session_access=access, execution=None)
    service.approval_scan_seconds = 0  # Yield after a page without relying on wall-clock timing.
    service.approval_expired = AsyncMock(return_value=True)
    service.cancel_run = AsyncMock()
    await service.expire_approvals(threads, lambda _: "owner-context")
    expired.add("t000000")
    for _ in range(4):
        threads.append(200)
        await service.expire_approvals(threads, lambda _: "owner-context")
        if service.cancel_run.await_count:
            break
    service.cancel_run.assert_awaited_once_with("waiting", "owner-context", expected_revision=3,
                                              reason="approval_timeout")
    assert threads.bounds[0] == threads.bounds[1] == ("z-last-existing" if insert_within_bound else "t000200")


@pytest.mark.asyncio
async def test_default_slice_advances_multiple_historical_pages_before_sleeping():
    threads = GrowingThreads()
    threads.append(799)
    filter_waiting = AsyncMock(return_value=set())
    service = RunService(application=SimpleNamespace(runtime=SimpleNamespace(
        session_store=SimpleNamespace(filter_suspended_session_ids=filter_waiting))),
        session_access=None, execution=None)
    assert await service.expire_approvals(threads, lambda _: None) is False
    assert len(threads.bounds) == 5
    assert sum(len(call.args[0]) for call in filter_waiting.await_args_list) == 1000


@pytest.mark.asyncio
async def test_maintenance_continues_a_partial_round_without_a_minute_delay(monkeypatch):
    from app.v2.server import bootstrap
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(bootstrap, "asyncio", SimpleNamespace(sleep=sleep))
    host = SimpleNamespace(threads=object(), contexts=SimpleNamespace(for_user=lambda _: None))
    runs = SimpleNamespace(expire_approvals=AsyncMock(side_effect=[True, False]))
    with pytest.raises(asyncio.CancelledError):
        await ServerHost._expire_approvals(host, runs)
    assert sleeps == [0, 60]


@pytest.mark.asyncio
async def test_database_scan_fence_excludes_new_tail_and_preserves_cursor_order():
    engine = create_async_engine("sqlite+aiosqlite://")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    class DB:
        @asynccontextmanager
        async def session(self):
            async with maker() as session:
                yield session

    try:
        async with engine.begin() as conn:
            await conn.run_sync(ThreadRow.__table__.create)
        async with maker.begin() as session:
            session.add_all(ThreadRow(thread_id=f"t{i}", user_id="owner", title="", agent_id="a",
                                      updated_at="2026-10-20T00:00:00+00:00") for i in range(3))
        index = DatabaseThreadIndex(DB())
        fence, count = await index.scan_snapshot()
        assert count == 3
        first = await index.scan(limit=2, through=fence)
        async with maker.begin() as session:
            session.add(ThreadRow(thread_id="t9", user_id="owner", title="", agent_id="a",
                                  updated_at="2026-10-20T00:00:00+00:00"))
        last = await index.scan(limit=2, cursor=first.next_cursor, through=fence)
        assert [row.thread_id for row in first.items + last.items] == ["t0", "t1", "t2"]
        assert last.next_cursor is None
        assert await index.scan_snapshot() == ("t9", 4)
    finally:
        await engine.dispose()
