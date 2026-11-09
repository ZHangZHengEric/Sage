"""History scans use sequence cursors and preserve session authorization."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.v2.server.routers.conversations import missing_history_images
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.events import ItemEventData
from sagents.v2.contracts.items import ImageBlock, ItemSnapshot, MessageItemData


def event(sequence, media='m_example'):
    now = utc_now()
    return SimpleNamespace(session_sequence=sequence, data=ItemEventData(
        operation='completed', item=ItemSnapshot(item_id=f'i{sequence}', run_id='r',
            status='completed', created_at=now, updated_at=now,
            data=MessageItemData(role='user', content=(ImageBlock(mime_type='image/png',
                uri=f'https://storage.withling.top/wishseen/media/123/{media}?X-Amz-Signature=expired'),)))))


def fixtures(tmp_path, pages):
    caller = SimpleNamespace(tenant_id='123', agent_id='agent')
    host = SimpleNamespace(paths=SimpleNamespace(workspace_path=lambda *args: tmp_path.resolve()))
    service = SimpleNamespace(_scope=AsyncMock(return_value=('owner', 'internal')),
        context_for=lambda owner: owner,
        session_access=SimpleNamespace(read_session_event_page=AsyncMock(side_effect=pages)))
    return caller, host, service


async def test_sparse_sequences_scan_once_and_deduplicate(tmp_path):
    args = fixtures(tmp_path, [SimpleNamespace(events=(event(999), event(1000)), total=1000)])
    result = await missing_history_images('wishseen_w_' + 'a' * 32, *args)
    assert result['data'] == ['m_example']
    args[2].session_access.read_session_event_page.assert_awaited_once()
    args[2]._scope.assert_awaited_once_with('123', 'agent', 'wishseen_w_' + 'a' * 32)


async def test_scan_stops_at_initial_head_while_new_events_arrive(tmp_path):
    args = fixtures(tmp_path, [SimpleNamespace(events=(event(500),), total=1000),
        SimpleNamespace(events=(event(1000), event(1001, 'm_new')), total=1001)])
    result = await missing_history_images('wishseen_w_' + 'a' * 32, *args)
    assert result['data'] == ['m_example']
    calls = args[2].session_access.read_session_event_page.await_args_list
    assert [call.kwargs['after_sequence'] for call in calls] == [0, 500]


async def test_non_wishseen_session_still_requires_access(tmp_path):
    args = fixtures(tmp_path, [])
    args[2]._scope.side_effect = PermissionError('not authorized')
    with pytest.raises(PermissionError):
        await missing_history_images('other-session', *args)
    args[2].session_access.read_session_event_page.assert_not_awaited()


async def test_broken_page_cannot_loop_forever(tmp_path):
    args = fixtures(tmp_path, [SimpleNamespace(events=(event(10),), total=100),
                              SimpleNamespace(events=(event(10),), total=100)])
    with pytest.raises(RuntimeError, match='did not advance'):
        await missing_history_images('wishseen_w_' + 'a' * 32, *args)
