import json

import httpx
import pytest

from app.v2.desktop.backend.rsi_presentation import compact_rsi_payload
from app.v2.desktop.backend.service import DesktopV2Service


def payload():
    observation = {'state': 'completed', 'output': 'Actual recorded response',
        'evidence': {'runtime_events': [{'native': 'x' * 40000}],
                     'training_trace': 'y' * 40000, 'final_items': ['z' * 40000],
                     'generated_tool_audit': {'clean': True}}}
    case = {'case': {'id': 'train', 'split': 'training', 'input': 'Actual user input'},
            'observation': observation, 'grade': {'score': .75, 'passed': False},
            'trials': [{'observation': observation, 'grade': {'score': .75}}]}
    return {'events': [{'sequence': 1, 'event': 'agent_call_started',
                       'data': {'role': 'evaluation', 'request': 'q' * 40000}}],
            'result': {'report': {'selected': {'cases': [case]},
                       'agent_calls': [{'role': 'evaluation', 'request': 'q' * 40000,
                                        'observation': observation}]}},
            'tool_schema': {'properties': {'request': {'type': 'string'}}}}


def test_compact_polling_preserves_conversations_grades_and_schema_without_mutating_evidence():
    raw = payload()
    raw['tool_definitions'] = {'rsi_literal': {'expression': {
        'state': 'completed', 'output': 'literal', 'evidence': {'runtime_events': ['user data']}}}}
    raw['custom_event'] = {'event': 'agent_call_started', 'data': 'literal'}
    original = json.dumps(raw)
    compact = compact_rsi_payload(raw)
    assert json.dumps(raw) == original
    assert len(json.dumps(compact)) < len(original) / 100
    before = raw['result']['report']['selected']['cases'][0]
    after = compact['result']['report']['selected']['cases'][0]
    assert after['case'] == before['case']
    assert after['grade'] == before['grade']
    assert after['trials'][0]['grade'] == before['trials'][0]['grade']
    assert after['observation']['output'] == before['observation']['output']
    assert after['observation']['evidence']['generated_tool_audit'] == {'clean': True}
    assert after['observation']['evidence']['execution_details_omitted'] is True
    assert compact['tool_schema'] == raw['tool_schema']
    assert compact['tool_definitions'] == raw['tool_definitions']
    assert compact['custom_event'] == raw['custom_event']
    assert 'request' not in compact['events'][0]['data']
    assert 'request' not in compact['result']['report']['agent_calls'][0]


@pytest.mark.asyncio
async def test_compact_http_view_preserves_full_owned_audit_and_full_api(tmp_path, monkeypatch):
    from app.v2.desktop.backend.app import create_app
    service = DesktopV2Service(tmp_path)
    async def owner(agent_id, user_id):
        assert (agent_id, user_id) == ('agent', 'alice')
    monkeypatch.setattr(service, '_agent', owner)
    monkeypatch.setattr('app.v2.desktop.backend.app.get_desktop_user_id', lambda request: 'alice')
    root = service.runtime_root / 'rsi/run'
    root.mkdir(parents=True)
    raw = payload()
    journal = root / 'audit.jsonl'
    journal.write_text(json.dumps(raw['events'][0]) + '\n')
    result = root / 'result.json'
    result.write_text(json.dumps(raw['result']))
    saved = (journal.read_bytes(), result.read_bytes())
    service.rsi_store.put({'id': 'run', 'status': 'completed', 'sequence': 1}, 'alice', 'agent', 'run')
    try:
        app = create_app(service=service, auth_token='local-test')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://desktop') as client:
            path = '/api/v2/agents/agent/rsi/runs/run'
            assert (await client.get(path + '?compact=true')).status_code == 401
            headers = {'Authorization': 'Bearer local-test'}
            full = await client.get(path, headers=headers)
            small = await client.get(path + '?compact=true', headers=headers)
        assert full.status_code == small.status_code == 200
        assert len(small.content) < len(full.content) / 100
        assert full.json()['data']['events'] == raw['events']
        assert small.json()['data']['result']['report']['selected']['cases'][0]['grade']['score'] == .75
        assert (journal.read_bytes(), result.read_bytes()) == saved
    finally:
        await service.close()
