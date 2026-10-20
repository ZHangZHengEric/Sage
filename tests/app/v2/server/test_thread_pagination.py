from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import event

from app.v2.server.conversations.orm import ThreadRow
from app.v2.server.conversations.repository import DatabaseThreadIndex


@pytest.mark.asyncio
async def test_thread_pages_filter_in_database_with_stable_ties_and_scan_cursor():
    engine = create_async_engine('sqlite+aiosqlite://')
    async with engine.begin() as conn:
        await conn.run_sync(ThreadRow.__table__.create)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    class DB:
        @asynccontextmanager
        async def session(self):
            async with maker() as session:
                yield session
    async with maker.begin() as session:
        session.add_all(ThreadRow(thread_id=f't{i:03}', user_id='u' if i < 20 else 'other',
            title='needle' if i % 2 else 'other', agent_id='a' if i % 3 else 'b',
            updated_at='2026-10-20T00:00:00+00:00') for i in range(40))
    queries = []
    event.listen(engine.sync_engine, 'before_cursor_execute', lambda c, cur, stmt, p, ctx, many: queries.append(stmt))
    index = DatabaseThreadIndex(DB())
    try:
        cursor, seen = None, []
        while True:
            page = await index.page(user_id='u', limit=3, cursor=cursor, search='needle', agent_id='a')
            seen.extend(item.thread_id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert seen == [f't{i:03}' for i in reversed(range(20)) if i % 2 and i % 3]
        assert all('LIMIT' in query and 'ORDER BY' in query for query in queries)
        first = await index.scan(limit=7)
        second = await index.scan(limit=7, cursor=first.next_cursor)
        assert [row.thread_id for row in first.items + second.items] == [f't{i:03}' for i in range(14)]
    finally:
        await engine.dispose()


def test_thread_list_routes_keep_owner_scope_and_resolve_old_direct_links(client, service):
    from app.v2.server.conversations.records import ThreadRecord
    from tests.app.v2.server.conftest import register_and_login
    from tests.app.v2.server.test_session_diagnostics import admin_headers
    alice = {'Authorization': f'Bearer {register_and_login(client)}'}
    user_id = client.get('/api/auth/session', headers=alice).json()['data']['user_id']
    for i in range(6):
        service.threads._threads[f't{i}'] = ThreadRecord(thread_id=f't{i}', user_id=user_id,
            title=f'entry-{i}', agent_id='writer', updated_at='2026-10-20T00:00:00+00:00')
    service.threads._threads['foreign'] = ThreadRecord(thread_id='foreign', user_id='someone-else', title='foreign')
    first = client.get('/api/threads?limit=2', headers=alice).json()['data']
    assert [item['thread_id'] for item in first['items']] == ['t5', 't4']
    assert first['next_cursor']
    second = client.get('/api/threads', params={'limit': 2, 'cursor': first['next_cursor']}, headers=alice).json()['data']
    assert [item['thread_id'] for item in second['items']] == ['t3', 't2']
    assert client.get('/api/threads/t0', headers=alice).json()['data']['agent_id'] == 'writer'
    assert client.get('/api/threads/foreign', headers=alice).status_code == 404
    assert client.get('/api/threads?cursor=invalid', headers=alice).status_code == 422
    filtered = client.get('/api/threads?search=entry-0&agent_id=writer', headers=alice).json()['data']
    assert [item['thread_id'] for item in filtered['items']] == ['t0']
    assert client.get('/api/admin/threads/t0', headers=admin_headers(client)).json()['data']['user_id'] == user_id
    assert client.get('/api/admin/threads?limit=2', headers=admin_headers(client)).json()['data']['next_cursor']
    # Empty approvals still advance the thread candidate cursor.
    pending = client.get('/api/approvals?limit=2', headers=alice).json()['data']
    assert pending['items'] == [] and pending['next_cursor']
    pending2 = client.get('/api/approvals', params={'limit': 2, 'cursor': pending['next_cursor']}, headers=alice).json()['data']
    assert pending2['next_cursor'] and pending2['next_cursor'] != pending['next_cursor']
