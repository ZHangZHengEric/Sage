"""Real official simulators, native scoring and grouped, reproducible datasets."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import os
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('name,counts', [('alfworld', (120, 24, 24)), ('scienceworld', (75, 27, 23)), ('agentbench_db', (234, 32, 34))])
def test_committed_exports_and_official_sources(name, counts):
    from evaluation_datasets import _support
    exporter = importlib.import_module(f'evaluation_datasets.{name}.export_dataset')
    dataset = exporter.build_dataset()
    root = ROOT / 'evaluation_datasets' / name
    assert dataset.model_dump(mode='json') == json.loads((root / 'rsi.dataset.json').read_text())
    assert tuple(sum(c.split == split for c in dataset.cases) for split in ('training', 'validation', 'test')) == counts
    _support.activate(root, 'vendor')
    assert all(set(c.environment_context) == {'task_id'} for c in dataset.cases)
    assert all('gold_actions' not in c.input and 'walkthrough' not in c.input for c in dataset.cases)


def test_db_table_families_do_not_cross_splits():
    from evaluation_datasets.agentbench_db.export_dataset import family, build_dataset
    from evaluation_datasets.agentbench_db.runtime import tasks
    groups = {}
    for case in build_dataset().cases:
        key = family(tasks()[case.id])
        assert groups.setdefault(key, case.split) == case.split


def require_runtime(name):
    if name == 'alfworld':
        pytest.importorskip('textworld')
    if name == 'scienceworld':
        pytest.importorskip('py4j')
        from evaluation_datasets.scienceworld.runtime import activate
        try:
            activate()
        except RuntimeError as e:
            pytest.skip(str(e))


@pytest.mark.parametrize('name', ['alfworld', 'scienceworld', 'agentbench_db'])
def test_actual_official_scorer_positive_negative_and_rejected_tools(name):
    require_runtime(name)
    scorer = importlib.import_module(f'evaluation_datasets.{name}.scorer')
    for fixture in scorer.SCORER_TEST_CASES:
        result = scorer.score(fixture['request'])
        assert result['grade']['score'] == fixture['expected_score']
        assert result['grade']['passed'] is fixture['expected_passed']
    broken = deepcopy(scorer.SCORER_TEST_CASES[1]['request'])
    result = next(e['data'] for e in broken['observation']['evidence']['final_items'] if e['data']['kind'] == 'tool_result')
    result['error'] = {'code': 'denied', 'message': 'Permission denied'}
    with pytest.raises(ValueError, match='Rejected'):
        scorer.score(broken)


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['alfworld', 'scienceworld', 'agentbench_db'])
async def test_import_selftests_in_real_isolated_worker(name):
    require_runtime(name)
    from sagents.v2.optimization.python_scorer import PythonExecutionScorer
    scorer = importlib.import_module(f'evaluation_datasets.{name}.scorer')
    path = ROOT / 'evaluation_datasets' / name / 'scorer.py'
    wrapper = PythonExecutionScorer(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        descriptor=scorer.DESCRIPTOR.model_dump(), timeout=120)
    assert (await wrapper.validate())['status'] == 'passed'


@pytest.mark.parametrize('name', ['alfworld', 'scienceworld'])
def test_native_observation_tampering_is_invalid_measurement(name):
    require_runtime(name)
    scorer = importlib.import_module(f'evaluation_datasets.{name}.scorer')
    request = deepcopy(scorer.SCORER_TEST_CASES[1]['request'])
    result = next(e['data'] for e in request['observation']['evidence']['final_items'] if e['data']['kind'] == 'tool_result')
    result['content'][0]['text'] = '{}'
    with pytest.raises(ValueError, match='outcome differs'):
        scorer.score(request)


def test_db_official_cleaner_cannot_eval_model_answers(tmp_path):
    from evaluation_datasets.agentbench_db import runtime
    marker = tmp_path / 'executed'
    payload = "[__import__('pathlib').Path(" + repr(str(marker)) + ").touch()]"
    assert runtime.compare([payload], ['correct'], 'SELECT') is False
    assert not marker.exists()
    assert runtime.compare(['1,000'], ['1000'], 'SELECT') is True
    assert runtime.compare(['1.005'], ['1'], 'SELECT') is True


def test_missing_db_service_fails_explicitly(tmp_path, monkeypatch):
    from evaluation_datasets.agentbench_db import runtime
    monkeypatch.setattr(runtime, 'CONNECTION', tmp_path / 'absent.json')
    with pytest.raises(RuntimeError, match='Managed MySQL'):
        runtime.replay({'task_id': 'agentbench-db-0'}, ['SHOW TABLES'])


@pytest.mark.skipif(os.environ.get('SAGE_TEST_DB_MYSQL') != '1', reason='Requires managed Docker MySQL; set SAGE_TEST_DB_MYSQL=1 after manage start')
def test_mysql_official_queries_writes_and_isolation():
    from evaluation_datasets.agentbench_db import runtime
    runtime.preflight()
    for kind in ['INSERT', 'UPDATE']:
        identity, entry = next((k, v) for k, v in runtime.tasks().items() if v['type'][0] == kind)
        context = {'task_id': identity}
        query = entry['sql']['query']
        responses, _ = runtime.replay(context, [query])
        assert runtime.evaluate(context, [query], ['ignored'], responses)
        assert not runtime.evaluate(context, [], ['pretend success'], [])
        # A new reconstruction starts with pristine source data.
        responses2, _ = runtime.replay(context, [query])
        assert responses2 == responses
    first = {'task_id': 'agentbench-db-0'}
    responses, _ = runtime.replay(first, ['SELECT * FROM mysql.user'])
    assert 'denied' in responses[0].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('name,namespace', [('alfworld', 'ALFWorld'), ('scienceworld', 'ScienceWorld')])
async def test_real_stdio_state_survives_reconnect_and_is_private(tmp_path, name, namespace):
    require_runtime(name)
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    runtime = importlib.import_module(f'evaluation_datasets.{name}.runtime')
    fixture = json.loads((runtime.ROOT / 'fixtures.json').read_text())[1]['request']
    task_id = fixture['case']['id']
    calls = [i['data']['arguments']['action'] for i in fixture['observation']['evidence']['final_items'] if i['data']['kind'] == 'tool_call']
    # First useful action changes position/door state; subsequent calls must see it.
    actions = calls[:2]
    expected, _ = runtime.replay({'task_id': task_id}, actions)
    effect_orders = {}
    async def invoke(candidate, tool, arguments):
        path = tmp_path / f'{candidate}.json'
        path.write_text(json.dumps({'protocol': 'sage.rsi.case/v1', 'context': {'task_id': task_id}, 'state_directory': str(tmp_path / candidate)}))
        parameters = StdioServerParameters(command=sys.executable,
            args=['-m', f'evaluation_datasets.{name}.mcp_server', '--state', str(tmp_path / 'unused')],
            env={**os.environ, 'PYTHONPATH': str(ROOT), 'SAGE_RSI_CASE_CONTEXT_FILE': str(path)})
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {'observe', 'step'}
                result = await session.call_tool(tool, arguments)
                assert not result.isError
                order = result.meta['sage_rsi_effect_order']
                assert order['protocol'] == 'sage.rsi.mcp-effect-order/v1'
                effect_orders.setdefault(candidate, []).append(order)
                return json.loads(result.content[0].text)
    for i, action in enumerate(actions):
        assert await invoke('a', 'step', {'action': action}) == expected[i + 1]
    assert await invoke('a', 'observe', {}) == expected[-1]
    assert await invoke('b', 'observe', {}) == expected[0]
    assert [order['sequence'] for order in effect_orders['a']] == [1, 2, 3]
    assert effect_orders['b'][0]['sequence'] == 1
    assert len({order['case_instance'] for order in effect_orders['a']}) == 1
    assert effect_orders['a'][0]['case_instance'] != effect_orders['b'][0]['case_instance']
    assert not (tmp_path / 'unused').exists()


def test_scienceworld_default_contains_only_verified_paths_and_current_prompts():
    from evaluation_datasets.scienceworld import runtime
    from evaluation_datasets.scienceworld.export_dataset import build_dataset
    report = json.loads((runtime.ROOT / 'data/validation.json').read_text())
    assert hashlib.sha256((runtime.ROOT / 'vendor/scienceworld/scienceworld.jar').read_bytes()).hexdigest() == report['jar_sha256']
    dataset = build_dataset()
    assert {c.id for c in dataset.cases} == set(report['verified_task_ids'])
    assert len(report['failed_reference_paths']) == 20
    assert not report['fold_mismatches']
    for case in dataset.cases:
        assert case.input.startswith(runtime.tasks()[case.id]['input'])
        if case.id in report['prompt_overrides']:
            assert runtime.tasks()[case.id]['input'] == report['prompt_overrides'][case.id]


def test_scienceworld_partial_credit_is_cumulative_official_score():
    require_runtime('scienceworld')
    from evaluation_datasets.scienceworld import scorer
    request = deepcopy(scorer.SCORER_TEST_CASES[1]['request'])
    request['observation']['evidence']['final_items'] = request['observation']['evidence']['final_items'][:10]
    grade = scorer.score(request)['grade']
    assert grade['score'] == .03
    assert grade['passed'] is False


def test_alfworld_terminal_state_is_absorbing_for_already_dispatched_sibling_actions():
    require_runtime('alfworld')
    from evaluation_datasets.alfworld import runtime, scorer
    from evaluation_datasets import _interactive
    fixture = next(x['request'] for x in scorer.SCORER_TEST_CASES if x['expected_passed'])
    context = {'task_id': fixture['case']['id']}
    actions = [i['data']['arguments']['action'] for i in fixture['observation']['evidence']['final_items']
        if i['data']['kind'] == 'tool_call']
    original, original_score = runtime.replay(context, actions)
    assert original[-1]['done'] is True and original_score == 1
    snapshots, value = runtime.replay(context, [*actions, 'look', 'inventory'])
    assert snapshots[:len(original)] == original
    assert snapshots[-2:] == [original[-1], original[-1]]
    assert value == original_score
    request = _interactive.fixture_request('ALFWorld', context['task_id'], [*actions, 'look', 'inventory'], snapshots)
    # The environment boundary may finish a native run without a final model message.
    request['observation']['evidence']['final_items'].pop()
    assert scorer.score(request)['grade']['passed'] is True
    exhausted, exhausted_score = runtime.replay(context, ['look'] * 200)
    assert exhausted[-1]['done'] is True and exhausted_score == 0
    terminal_state, terminal_result, error = runtime.call(context, {'actions': ['look'] * 200},
        'step', {'action': 'look'})
    assert not error and terminal_result == exhausted[-1] and len(terminal_state['actions']) == 200
    following, following_result, error = runtime.call(context, terminal_state, 'step', {'action': 'inventory'})
    assert not error and following == terminal_state and following_result == exhausted[-1]
    with pytest.raises(ValueError, match='budget exceeded'):
        runtime.replay(context, ['look'] * 201)
    # A batch may already contain sibling requests after the 200th action.
    # They do not advance the absorbing world; every returned snapshot is still
    # verified, while the direct replay request budget remains strictly 200.
    tail = _interactive.fixture_request('ALFWorld', context['task_id'], ['look'] * 202,
        [*exhausted, exhausted[-1], exhausted[-1]])
    grade = scorer.score(tail)
    assert grade['grade']['score'] == 0
    assert grade['details']['actions'] == 200 and grade['details']['absorbed_step_calls'] == 2
    bad_tail = deepcopy(tail)
    result = next(item['data'] for item in reversed(bad_tail['observation']['evidence']['final_items'])
        if item['data']['kind'] == 'tool_result')
    altered = json.loads(result['content'][0]['text'])
    altered['observation'] = 'Forged postterminal result'
    result['content'][0]['text'] = json.dumps(altered)
    with pytest.raises(ValueError, match='differs'):
        scorer.score(bad_tail)
