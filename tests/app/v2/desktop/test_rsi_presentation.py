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


def test_compact_execution_keeps_order_tools_errors_and_excludes_private_data():
    def item(identity, data, visibility='public'):
        return {'run_id': 'run', 'item_id': identity, 'visibility': visibility, 'data': data}
    items = [
        item('1', {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'Checking.'}], 'provider_state': {'secret': 'hidden'}}),
        item('2', {'kind': 'tool_call', 'tool_call_id': 'call', 'tool_name': 'file_read', 'arguments': {'path': 'index.html'}}),
        item('3', {'kind': 'reasoning', 'content': [{'kind': 'text', 'text': 'hidden reasoning'}]}),
        item('4', {'kind': 'tool_result', 'tool_call_id': 'call', 'content': [{'kind': 'text', 'text': 'x' * 9000}], 'error': {'code': 'failed', 'message': 'Missing file'}}),
        item('5', {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'hidden audit'}]}, 'audit'),
        item('6', {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'Finished.'}]}),
    ]
    raw = {'state': 'completed', 'output': 'Checking.\nFinished.', 'evidence': {'final_items': items}}
    compact = compact_rsi_payload(raw)
    transcript = compact['evidence']['execution_transcript']
    assert [entry['kind'] for entry in transcript] == ['message', 'tool_call', 'tool_result', 'message']
    assert transcript[1]['call_id'] == transcript[2]['call_id'] == 'run:call'
    assert transcript[1]['tool_name'] == 'file_read'
    assert transcript[2]['state'] == 'failed'
    assert transcript[2]['error'] == 'Missing file'
    assert len(transcript[2]['text']) < 6100
    assert 'hidden' not in json.dumps(compact)
    assert raw['evidence']['final_items'] == items


@pytest.mark.asyncio
async def test_indexed_overview_serves_grades_and_loads_owned_case_on_demand(tmp_path, monkeypatch):
    from app.v2.desktop.backend.app import create_app

    service = DesktopV2Service(tmp_path)

    async def owner(agent_id, user_id):
        assert (agent_id, user_id) == ("agent", "alice")

    monkeypatch.setattr(service, "_agent", owner)
    monkeypatch.setattr("app.v2.desktop.backend.app.get_desktop_user_id", lambda request: "alice")
    root = service.runtime_root / "rsi/run"
    root.mkdir(parents=True)
    expected = payload()["result"]
    expected["report"]["suite"] = {"literal": {"$rsi_result_part": 1}}
    call = expected["report"]["agent_calls"][0]
    expected["report"]["agent_calls"].append({
        **call, "observation": {**call["observation"], "output": "Different response"},
    })
    original = json.dumps(expected).encode()
    source = root / "result.json"
    source.write_bytes(original)
    (root / "audit.jsonl").write_text(
        json.dumps({"event": "agent_call_started", "data": {"request": call["request"]}}) + "\n" +
        json.dumps({"event": "agent_call_completed", "data": {"observation": call["observation"]}}) + "\n",
        encoding="utf-8",
    )
    service.rsi_store.put({"id": "run", "status": "completed", "sequence": 1}, "alice", "agent", "run")
    try:
        app = create_app(service=service, auth_token="local-test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://desktop",
            headers={"Authorization": "Bearer local-test"},
        ) as client:
            path = "/api/v2/agents/agent/rsi/runs/run"
            first = (await client.get(path + "?overview=true")).json()["data"]
            assert first["overview_pending"]
            if job := service._rsi_overview_jobs.get(("alice", "agent", "run")):
                await job
            overview = (await client.get(path + "?overview=true")).json()["data"]
            assert not overview["overview_pending"]
            case = overview["result"]["report"]["selected"]["cases"][0]
            assert case["grade"]["score"] == .75
            assert "observation" not in case
            assert "agent_calls" not in overview["result"]["report"]
            assert (await client.get(f"{path}/result/cases/{case['result_part']}")).json()["data"][
                "observation"]["output"] == "Actual recorded response"
            assert (await client.get(f"{path}/result/export")).content == original
            assert source.read_bytes() == original
            from app.v2.desktop.backend.rsi_result_store import read_part, read_result

            result_dir = root / "result-index-v1"
            records = result_dir / "records"
            index = json.loads((result_dir / "index.json").read_text())
            assert not list(result_dir.glob("*.json.gz"))
            case_dir = records / "selected/training/case-train"
            assert (case_dir / "summary.json").is_file()
            assert (case_dir / "evidence.json.gz").is_file()
            assert (records / "agent-calls/evaluation/round-000/call-001/record.json.gz").is_file()
            call_part = index["report"]["agent_calls"][0]["$rsi_result_part"]
            stored = read_part(root, call_part)
            assert set(stored["$rsi_call_evidence"]) == {"request", "observation"}
            assert stored["call"] == {"role": "evaluation"}
            partial = read_part(root, index["report"]["agent_calls"][1]["$rsi_result_part"])
            assert set(partial["$rsi_call_evidence"]) == {"request"}
            assert partial["call"]["observation"]["output"] == "Different response"
            source.unlink()
            assert read_result(root) == expected
            assert (await client.get(f"{path}/result/export")).json() == expected
    finally:
        await service.close()



def test_reorganize_existing_flat_result_preserves_part_ids(tmp_path):
    import gzip

    from app.v2.desktop.backend.rsi_result_store import organize_result, read_part, read_result

    directory = tmp_path / "result-index-v1"
    directory.mkdir()
    ref = {"$rsi_result_part": 7}
    case = payload()["result"]["report"]["selected"]["cases"][0]
    round_record = {"round": 1, "evaluation": {"cases": [ref]}}
    index = {"report": {"rounds": [{"$rsi_result_part": 8}], "selected": {"cases": [ref]}}}
    (directory / "index.json").write_text(json.dumps(index))
    for part, item in [(7, case), (8, round_record)]:
        (directory / f"{part}.json.gz").write_bytes(gzip.compress(json.dumps(item).encode()))
    organize_result(tmp_path)
    organize_result(tmp_path)
    assert read_part(tmp_path, 7, case_only=True) == case
    assert read_result(tmp_path)["report"]["rounds"][0]["evaluation"]["cases"] == [case]
    records = directory / "records"
    folder = records / "rounds/round-001/evaluation/training/case-train"
    assert (folder / "summary.json").is_file()
    assert (folder / "evidence.json.gz").is_file()
    alias = records / "selected/training/case-train/reference.json"
    assert (alias.parent / json.loads(alias.read_text())["path"]).resolve() == (folder / "evidence.json.gz")
    assert not list(directory.glob("*.json.gz"))
