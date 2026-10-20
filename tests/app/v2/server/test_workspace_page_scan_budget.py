"""Workspace teardown scans each indexed candidate once, including claimed history.

Existing authority tests protect a single mixed page. These real SQLite adapter
cases additionally protect total traversal work, index use and cross-page scope.
"""
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.v2.server.conversations.bindings import SessionBinding
from app.v2.server.conversations.orm import ThreadRow, SessionBindingRow
from app.v2.server.conversations.records import ThreadRecord
from app.v2.server.conversations.repository import DatabaseThreadIndex
from tests.app.v2.server.fakes import MemoryThreadIndex


@asynccontextmanager
async def database_index():
    engine = create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as connection:
        await connection.run_sync(ThreadRow.__table__.create)
        await connection.run_sync(SessionBindingRow.__table__.create)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    class DB:
        @asynccontextmanager
        async def session(self):
            async with maker() as session:
                yield session
    try:
        yield DatabaseThreadIndex(DB()), engine, maker
    finally:
        await engine.dispose()


async def all_pages(index, *, limit=20):
    cursor, claimed, legacy = None, [], []
    for _ in range(1000):
        page = await index.workspace_session_page('tenant', 'agent', owner_id='owner', cursor=cursor, limit=limit)
        assert len(page.session_ids) + len(page.legacy_session_ids) <= limit
        claimed.extend(page.session_ids)
        legacy.extend(page.legacy_session_ids)
        if page.next_cursor is None:
            return claimed, legacy
        assert cursor != page.next_cursor
        cursor = page.next_cursor
    pytest.fail('workspace traversal did not terminate')


@pytest.mark.asyncio
async def test_fully_claimed_history_does_not_rescan_empty_legacy_branch():
    async with database_index() as (index, engine, maker):
        async with maker.begin() as session:
            session.add_all(ThreadRow(thread_id=f's{i:04}', user_id='owner', agent_id='agent', title='', updated_at='same') for i in range(2000))
            session.add_all(SessionBindingRow(session_id=f's{i:04}', owner_id='owner', tenant_id='tenant', agent_id='agent') for i in range(2000))
        steps = 0
        def progress():
            nonlocal steps
            steps += 100
        async with engine.connect() as connection:
            raw = await connection.get_raw_connection()
            await raw.driver_connection.set_progress_handler(progress, 100)
        claimed, legacy = await all_pages(index)
        assert claimed == [f's{i:04}' for i in range(2000)] and legacy == []
        assert steps < 200_000, f'empty legacy lookup repeated {steps:,} SQLite VM steps'


@pytest.mark.asyncio
async def test_legacy_cursor_uses_owner_agent_id_index_without_sorting_history():
    async with database_index() as (index, engine, maker):
        async with maker.begin() as session:
            session.add_all(ThreadRow(thread_id=f's{i:04}', user_id='owner', agent_id='agent', title='', updated_at='same') for i in range(200))
        queries = []
        event.listen(engine.sync_engine, 'before_cursor_execute', lambda c, cur, sql, params, ctx, many: queries.append((sql, params)))
        assert (await all_pages(index))[1] == [f's{i:04}' for i in range(200)]
        plans = []
        async with engine.connect() as connection:
            for sql, params in list(queries):
                rows = await connection.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params)
                plans.extend(row[-1] for row in rows)
        assert any('ix_threads_user_agent_thread_id' in plan for plan in plans), plans
        assert not any('TEMP B-TREE' in plan for plan in plans), plans


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['database', 'fake'])
async def test_workspace_cursor_preserves_owner_tenant_claim_only_and_legacy_scope(backend):
    bindings = [SessionBinding('claim-only', 'owner', 'tenant', 'agent'),
                SessionBinding('own-claimed', 'owner', 'tenant', 'agent'),
                SessionBinding('foreign-owner', 'someone', 'tenant', 'agent'),
                SessionBinding('foreign-tenant', 'owner', 'elsewhere', 'agent')]
    threads = [ThreadRecord(thread_id=sid, user_id='owner', agent_id='agent') for sid in
               ['own-claimed', 'foreign-owner', 'foreign-tenant', 'legacy-a', 'legacy-z']]
    threads += [ThreadRecord(thread_id='other-user', user_id='someone', agent_id='agent'),
                ThreadRecord(thread_id='other-agent', user_id='owner', agent_id='different')]
    async with database_index() as (database, engine, maker):
        if backend == 'database':
            index = database
            async with maker.begin() as session:
                session.add_all(SessionBindingRow(**vars(binding)) for binding in bindings)
                session.add_all(ThreadRow(**thread.model_dump()) for thread in threads)
        else:
            index = MemoryThreadIndex()
            for binding in bindings:
                await index.bind(binding)
            index._threads.update({thread.thread_id:thread for thread in threads})
        claimed, legacy = await all_pages(index, limit=2)
        assert claimed == ['claim-only', 'own-claimed']
        assert legacy == ['legacy-a', 'legacy-z']
