import json

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.v2.cli.rsi_mcp import DesktopBridge, create_server
from app.v2.desktop.backend.runtime_protocol import SIDECAR_PROTOCOL, SIDECAR_REVISION


def registry(root, host="127.0.0.1"):
    folder = root / "runtime"
    folder.mkdir()
    (folder / "desktop-v2-sidecar.json").write_text(
        json.dumps(
            {
                "host": host,
                "port": 43210,
                "auth_token": "test-only",
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": "test",
            }
        )
    )


@pytest.mark.asyncio
async def test_mcp_real_stdio_lists_tools_and_reports_missing_desktop(tmp_path):
    import sys

    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "app.v2.cli.rsi_mcp",
            "--data-root",
            str(tmp_path),
        ],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {t.name for t in result.tools}
            assert names == {
                "rsi_agents",
                "rsi_start",
                "rsi_history",
                "rsi_status",
                "rsi_questions",
                "rsi_cancel",
                "rsi_resume",
                "rsi_version",
                "rsi_apply",
            }
            response = await session.call_tool("rsi_agents", {})
            assert response.isError
            assert "Start Sage Desktop" in response.content[0].text


@pytest.mark.asyncio
async def test_bridge_tools_route_to_one_authenticated_runtime(tmp_path):
    registry(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-only"
        path = request.url.path
        if path == "/health":
            data = {"protocol": SIDECAR_PROTOCOL, "revision": SIDECAR_REVISION, "build_id": "test"}
        elif "/runtime/clients/" in path:
            data = {"lease_ttl_seconds": 30}
        elif path == "/api/v2/agents":
            data = [{"id": "a", "name": "Default", "config": {"api_key": "secret"}}]
        elif path.endswith("/runs/r"):
            data = {"status": "running", "events": [
                {"sequence": 1, "event": "suite_fixed", "data": {"suite": {"cases": [
                    {"id": "t1", "split": "training"}, {"id": "v1", "split": "validation"}]}}},
                {"sequence": 2, "event": "training_cases_added", "data": {"cases": [{"id": "t2", "split": "training"}]}}
            ]}
        else:
            data = {"id": "r"}
        return httpx.Response(200, json={"code": 0, "data": data})
    bridge = DesktopBridge(tmp_path, transport=httpx.MockTransport(handler))
    server = create_server(tmp_path, bridge=bridge)
    try:
        agents = await server.call_tool("rsi_agents", {})
        assert "secret" not in str(agents)
        await server.call_tool("rsi_start", {"agent_id": "a", "goal": "Become support", "request_id": "intent-1",
            "optimization_scope": ["instructions", "tools"], "target_score": .98, "patience": 4, "stability_passes": 3})
        body = json.loads(next(r for r in requests if r.method == "POST").content)
        assert body["max_concurrency"] == 3 and body["validation_case_count"] == 24
        assert body["optimization_scope"] == ["instructions", "tools"]
        assert body["rounds"] == 8 and body["suite"] is None and body["human_test_count"] == 12
        assert "final_suite" not in body
        assert body["stopping_policy"] == {"target_score": .98, "patience": 4, "stability_passes": 3}
        questions = await server.call_tool("rsi_questions", {"agent_id": "a", "run_id": "r"})
        assert '"validation"' in str(questions)
        before = len(requests)
        with pytest.raises(Exception):
            await server.call_tool("rsi_apply", {"agent_id": "a", "version_id": "v", "expected_fingerprint": "x" * 64, "confirmed": False})
        assert len(requests) == before
    finally:
        await bridge.close()
    assert requests[-1].method == "DELETE"


@pytest.mark.asyncio
async def test_registry_cannot_forward_capability_to_remote_host(tmp_path):
    registry(tmp_path, host="8.8.8.8")
    bridge = DesktopBridge(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="loopback"):
            await bridge.connect()
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_unknown_mutation_outcome_is_never_retried(tmp_path):
    registry(tmp_path)
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request)
            raise httpx.ReadError("lost response")
        if request.url.path == "/health":
            data = {
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": "test",
            }
        else:
            data = {"lease_ttl_seconds": 30}
        return httpx.Response(200, json={"code": 0, "data": data})

    bridge = DesktopBridge(tmp_path, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="Do not repeat"):
            await bridge.request("POST", "/api/v2/agents/a/rsi", json={})
        assert len(posts) == 1
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_status_pagination_never_skips_events_and_omits_repeated_evidence(
    tmp_path,
):
    registry(tmp_path)

    def handler(request):
        if request.url.path == "/health":
            data = {
                "protocol": SIDECAR_PROTOCOL,
                "revision": SIDECAR_REVISION,
                "build_id": "test",
            }
        elif "/runtime/clients/" in request.url.path:
            data = {"lease_ttl_seconds": 30}
        else:
            after = int(request.url.params.get("after_sequence", 0))
            data = {
                "status": "completed",
                "sequence": 10,
                "iterations": [{"large": "snapshot"}],
                "events": [
                    {
                        "sequence": i,
                        "event": "target_call_completed",
                        "data": {
                            "observation": {
                                "output": "real reply",
                                "evidence": {"raw": "large transcript"},
                            }
                        },
                    }
                    for i in range(after + 1, 11)
                ],
            }
        return httpx.Response(200, json={"code": 0, "data": data})

    bridge = DesktopBridge(tmp_path, transport=httpx.MockTransport(handler))
    server = create_server(tmp_path, bridge=bridge)
    try:
        response = await server.call_tool(
            "rsi_status", {"agent_id": "a", "run_id": "r", "limit": 2}
        )
        # Direct FastMCP calls return text blocks; the stdio test covers protocol framing.
        value = json.loads(response[0].text)
        assert value["next_sequence"] == 2 and value["sequence"] == 10
        assert len(value["events"]) == 2
        assert "iterations" not in value
        assert "observation" not in value["events"][0]["data"]
        response = await server.call_tool(
            "rsi_status",
            {"agent_id": "a", "run_id": "r", "after_sequence": 2, "limit": 2},
        )
        assert [
            event["sequence"] for event in json.loads(response[0].text)["events"]
        ] == [3, 4]
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_old_runtime_is_rejected_before_any_api_mutation(tmp_path):
    registry(tmp_path)
    path = tmp_path / "runtime/desktop-v2-sidecar.json"
    value = json.loads(path.read_text())
    value["revision"] = SIDECAR_REVISION - 1
    path.write_text(json.dumps(value))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    bridge = DesktopBridge(tmp_path, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="matching Sage Desktop build"):
            await bridge.request("POST", "/api/v2/agents/a/rsi", json={})
        assert calls == []
    finally:
        await bridge.close()


def private_run():
    train = {'id': 'train', 'split': 'training', 'input': 'TRAIN_VISIBLE', 'rubric': 'TRAIN_RUBRIC',
             'reference_answer': 'EVALUATOR_REFERENCE_SECRET'}
    dev = {'id': 'DEV_ID_SECRET', 'split': 'validation', 'input': 'DEV_QUESTION_SECRET', 'rubric': 'DEV_RUBRIC_SECRET',
           'reference_answer': 'DEV_REFERENCE_SECRET'}
    test = {'id': 'TEST_ID_SECRET', 'split': 'test', 'input': 'TEST_QUESTION_SECRET', 'rubric': 'TEST_RUBRIC_SECRET'}
    evaluation = {'package_hash': 'hash', 'cases': [
        {'case': train, 'grade': {'score': .4, 'passed': False, 'rationale': 'TRAIN_FEEDBACK'}, 'observation': {'output': 'TRAIN_PROCESS'}},
        {'case': dev, 'grade': {'score': .8, 'passed': False, 'rationale': 'DEV_FEEDBACK_SECRET',
            'diagnosis': {'summary': 'DEV_DIAGNOSIS_VISIBLE'}}, 'observation': {'output': 'DEV_PROCESS_SECRET'}},
    ]}
    report = {'suite': {'cases': [train, dev]}, 'baseline': evaluation, 'selected': evaluation,
        'agent_calls': [{'request': 'DEV_PROCESS_SECRET TEST_QUESTION_SECRET'}],
        'validation_history': [{'score': .8237}],
        'overall_before': .6237, 'objective_after': .7237,
        'suite_review': {'approved': True, 'issues': [], 'rationale': 'DEV_QUESTION_SECRET'}}
    result = {'report': report}
    return {'id': 'run', 'status': 'completed', 'result': result,
        'human_test_suite': {'cases': [test]}, 'test_observations': [{'score': .137}],
        'human_test_error': 'TEST_ERROR_SECRET',
        'iterations': [{'evaluation': evaluation, 'reason': 'DEV_ID_SECRET regressed',
            'overall_after': .6237, 'objective_before': .7237,
            'training_growth': {'allowed': False, 'reason': 'regression', 'regressed_validation': 1, 'training_total': 1},
            'regressions': [{'split': 'validation', 'case_id': 'DEV_ID_SECRET', 'previous_score': .9}]}],
        'events': [
            {'sequence': 1, 'event': 'suite_fixed', 'data': {'suite': {'cases': [train, dev, test]}}},
            {'sequence': 2, 'event': 'target_call_started', 'data': {'input': 'DEV_QUESTION_SECRET', 'case_id': 'DEV_ID_SECRET'}},
            {'sequence': 3, 'event': 'target_call_completed', 'data': {'observation': {'output': 'DEV_PROCESS_SECRET'}}},
            {'sequence': 4, 'event': 'case_completed', 'data': {'result': evaluation['cases'][0]}},
            {'sequence': 5, 'event': 'evaluation_completed', 'data': {'evaluation': evaluation}},
            {'sequence': 6, 'event': 'future_test_event', 'data': {'output': 'TEST_QUESTION_SECRET'}},
            {'sequence': 7, 'event': 'result_completed', 'data': {'result': result}},
        ]}


def test_review_view_keeps_training_priorities_but_hides_raw_evaluator_reference():
    from app.v2.cli.rsi_visibility import review_view
    event = {'event': 'training_diagnosis_completed', 'data': {
        'round': 2, 'summary': {'summary': 'TRAINING PRIORITY', 'priorities': []},
        'reference_answer': 'EVALUATOR_REFERENCE_SECRET'}}
    visible = review_view(event)
    assert visible['data']['summary']['summary'] == 'TRAINING PRIORITY'
    assert 'SECRET' not in json.dumps(visible)


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,arguments', [
    ('rsi_start', {'agent_id': 'a', 'goal': 'Improve', 'request_id': 'intent'}),
    ('rsi_history', {'agent_id': 'a'}),
    ('rsi_status', {'agent_id': 'a', 'run_id': 'r'}),
    ('rsi_status', {'agent_id': 'a', 'run_id': 'r', 'include_details': True}),
    ('rsi_questions', {'agent_id': 'a', 'run_id': 'r'}),
    ('rsi_version', {'agent_id': 'a', 'version_id': 'v'}),
    ('rsi_cancel', {'agent_id': 'a', 'run_id': 'r'}),
    ('rsi_resume', {'agent_id': 'a', 'run_id': 'r'}),
    ('rsi_apply', {'agent_id': 'a', 'version_id': 'v', 'expected_fingerprint': 'x' * 64, 'confirmed': True}),
])
async def test_every_mcp_read_mode_allows_user_dev_review_but_seals_test(tmp_path, tool, arguments):
    class Bridge:
        async def request(self, *args, **kwargs):
            return private_run()
        async def close(self):
            pass
    response = await create_server(tmp_path, bridge=Bridge()).call_tool(tool, arguments)
    text = response[0].text
    assert all(secret not in text for secret in (
        'TEST_ID_SECRET', 'TEST_QUESTION_SECRET', 'TEST_RUBRIC_SECRET',
        'TEST_ERROR_SECRET', 'EVALUATOR_REFERENCE_SECRET', 'DEV_REFERENCE_SECRET', '0.137'))
    assert 'test_observations' not in text and 'human_test_suite' not in text
    assert 'TRAIN_VISIBLE' in text and 'DEV_QUESTION_SECRET' in text
    if tool != 'rsi_questions':
        assert 'DEV_DIAGNOSIS_VISIBLE' in text and '0.8' in text
    if tool == 'rsi_status' and arguments.get('include_details'):
        value = json.loads(text)
        dev = value['result']['report']['selected']['cases'][1]
        assert dev['case']['id'] == 'DEV_ID_SECRET'
        assert dev['grade']['score'] == .8
        assert dev['grade']['rationale'] == 'DEV_FEEDBACK_SECRET'
        assert dev['grade']['diagnosis']['summary'] == 'DEV_DIAGNOSIS_VISIBLE'
        assert dev['observation']['output'] == 'DEV_PROCESS_SECRET'
        assert value['result']['report']['validation_history'] == [{'score': .8237}]
        assert value['iterations'][0]['overall_after'] == .6237
        assert value['iterations'][0]['objective_before'] == .7237
        assert value['iterations'][0]['regressions'][0]['case_id'] == 'DEV_ID_SECRET'
        assert value['iterations'][0]['training_growth'] == {
            'allowed': False, 'reason': 'regression', 'regressed_validation': 1, 'training_total': 1}
        assert value['events'][3]['data']['result']['observation']['output'] == 'TRAIN_PROCESS'
        assert value['next_sequence'] == 7
    if tool == 'rsi_status' and not arguments.get('include_details'):
        scores = json.loads(text)['scores']
        assert scores['baseline_training'] == .4 and scores['selected_training'] == .4
        assert scores['baseline_validation'] == .8 and scores['selected_validation'] == .8
    if tool == 'rsi_questions':
        validation = json.loads(text)['validation']
        assert validation['total'] == 1 and validation['questions_visible'] is True
        assert validation['cases'][0]['id'] == 'DEV_ID_SECRET'



@pytest.mark.asyncio
async def test_mcp_schema_does_not_accept_agent_authored_dev_or_test_suites(tmp_path):
    server = create_server(tmp_path)
    tools = await server.list_tools()
    start = next(t for t in tools if t.name == 'rsi_start')
    assert 'suite' not in start.inputSchema['properties']
    assert 'human_test_suite' not in start.inputSchema['properties']
    assert 'human_test_count' in start.inputSchema['properties']


def test_review_views_hide_dataset_exclusion_and_preflight_provenance_even_in_details():
    from app.v2.cli.rsi_visibility import review_view
    secret = 'HIDDEN_DEV_TEST_DIAGNOSIS'
    human = {
        'dataset_manifest': {'active_case_ids': [secret], 'exclusions': [{'case_id': secret, 'evidence': [secret]}]},
        'generated_dataset_manifest': {'active_case_ids': [secret]},
        'dataset_versions': [{'manifest': {'exclusions': [secret]}}],
        'dataset_diagnostics': [{'review': {'approved': False, 'rationale': secret, 'issues': []}}],
        'dataset_version': {'dataset': {'cases': [{'id': secret, 'split': 'test'}]}},
        'events': [
            {'event': 'generated_cases_quarantined', 'sequence': 1, 'data': {'cases': [{'id': secret}], 'review': secret}},
            {'event': 'generated_cases_repaired', 'sequence': 2, 'data': {'before': secret, 'after': secret}},
        ],
        'suite_review': {'approved': False, 'rationale': secret, 'issues': []},
    }
    visible = review_view(human)
    assert secret not in json.dumps(visible)
    assert visible['suite_review']['approved'] is False


def test_review_projection_preserves_dev_case_events_without_mutating_human_record():
    from copy import deepcopy
    from app.v2.cli.rsi_visibility import review_view

    raw = private_run()
    snapshot = deepcopy(raw)
    cases = raw['result']['report']['selected']['cases']
    for result in cases:
        event = {'sequence': 9, 'event': 'case_completed', 'data': {'result': result}}
        visible = review_view(event)
        assert visible['data']['result']['grade'] == result['grade']
        assert 'reference_answer' not in visible['data']['result']['case']
    test = {'case': {'id': 'TEST_ID_SECRET', 'split': 'test'},
            'grade': {'score': .137, 'rationale': 'TEST_DIAGNOSIS_SECRET'}}
    visible = review_view({'event': 'case_completed', 'data': {'result': test}})
    assert 'result' not in visible['data']
    assert raw == snapshot


@pytest.mark.asyncio
async def test_external_review_does_not_relax_actual_internal_tuning_inputs(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite

    runner = Runner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
        suite=suite(), rounds=2, validation_case_count=1, grow_training=False)
    internal = [json.loads(content)['data'] for name, content in runner.requests if name == 'test.tuner']
    assert all('validation' not in data and 'validation_history' not in data for data in internal)
    assert all('holdout-secret' not in json.dumps(data) and 'Convert 7 cm' not in json.dumps(data)
               for data in internal)
    assert all('overall_before' not in attempt and 'objective_before' not in attempt
               for data in internal for attempt in data['previous_attempts'])

    class Bridge:
        async def request(self, *args, **kwargs):
            return {'result': result.model_dump(mode='json'), 'events': []}
        async def close(self):
            pass

    response = await create_server(tmp_path, bridge=Bridge()).call_tool('rsi_status', {
        'agent_id': 'a', 'run_id': 'r', 'include_details': True})
    report = json.loads(response[0].text)['result']['report']
    dev, = [c for c in report['selected']['cases'] if c['case']['split'] == 'validation']
    assert dev['case']['id'] == 'holdout-secret' and dev['case']['input'] == 'Convert 7 cm'
    assert dev['grade']['score'] == .6 and dev['grade']['rationale'] == 'Checked result'
    assert report['rounds'][0]['overall_before'] == .4
    assert 'agent_calls' not in report  # Mixed-split raw internal calls stay excluded.
