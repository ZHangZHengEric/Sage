import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
import pytest
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState

def probe(roster, pages=(), compact=None):
    state = _MysqlSessionState('mysql://unused/test')
    reader, writer = AsyncMock(), AsyncMock()
    read_cursor, write_cursor = AsyncMock(), AsyncMock()
    for conn, cursor in [(reader, read_cursor), (writer, write_cursor)]:
        conn.cursor = MagicMock()
        conn.cursor.return_value.__aenter__.return_value = cursor
    read_cursor.fetchall.side_effect = [roster, *pages]
    read_cursor.fetchone.return_value = (json.dumps(compact),) if compact is not None else None
    @asynccontextmanager
    async def read(): yield reader
    @asynccontextmanager
    async def write(): yield writer
    state._reader_connection, state._writer_connection = read, write
    return state, read_cursor, write_cursor, writer

@pytest.mark.parametrize('revision', [8, 10])
async def test_stale_or_incomplete_idle_projection_does_not_hide_active_run(revision):
    state, _, writer, _ = probe([('s', 'r', 10, {'revision': revision, 'states': {}})],
        [[(10, '[{"run_id":"r","state":"running"}]', None)]])
    assert await state.has_nonterminal_sessions(['s'])
    writer.execute.assert_not_awaited()

async def test_terminal_patch_overrides_upsert_and_repairs_exact_revision():
    state, reader, writer, conn = probe([('s', 'r', 10, None)],
        [[(10, '[{"run_id":"r","state":"cancelled"}]', '[{"run_id":"r","state":"running"}]')]])
    assert not await state.has_nonterminal_sessions(['s'])
    sql, params = writer.execute.await_args.args
    assert 'revision = %s' in sql and params[-2:] == ('s', 10)
    assert json.loads(params[1]) == {'revision':10, 'states':{'r':'cancelled'}}
    conn.commit.assert_awaited_once()
    assert not any('compact_state' in c.args[0] for c in reader.execute.await_args_list)

async def test_partial_patch_pages_back_to_compact_snapshot():
    state, reader, writer, _ = probe([('s','r',10,None)],
        [[(10, '[{"run_id":"r","revision":10}]', None)], []], [{'run_id':'r','state':'completed'}])
    assert not await state.has_nonterminal_sessions(['s'])
    assert any(len(c.args) > 1 and c.args[1] == ('s',10) for c in reader.execute.await_args_list)
    assert json.loads(writer.execute.await_args.args[1][1])['states'] == {'r':'completed'}

async def test_all_surviving_runs_checked():
    state, _, _, _ = probe([('s','done',10,None),('s','active',10,None)],
        [[(10, '[{"run_id":"done","state":"completed"}]',None)],
         [(9,None,'[{"run_id":"active","state":"suspended"}]')]])
    assert await state.has_nonterminal_sessions(['s'])

async def test_deleted_run_absent_from_roster():
    state, reader, writer, _ = probe([])
    assert not await state.has_nonterminal_sessions(['s'])
    assert not any('session_mutations' in c.args[0] for c in reader.execute.await_args_list)
    writer.execute.assert_not_awaited()

async def test_missing_canonical_state_fails_closed():
    state, _, writer, _ = probe([('s','r',10,None)],[[]],[])
    with pytest.raises(SageV2Error, match='Workspace Run state is missing'):
        await state.has_nonterminal_sessions(['s'])
    writer.execute.assert_not_awaited()

async def test_projection_repair_failure_rolls_back():
    state, _, writer, conn = probe([('s','r',10,None)],[[]],[{'run_id':'r','state':'completed'}])
    writer.execute.side_effect = RuntimeError('write failed')
    with pytest.raises(RuntimeError, match='write failed'):
        await state.has_nonterminal_sessions(['s'])
    conn.rollback.assert_awaited_once()
    conn.commit.assert_not_awaited()
