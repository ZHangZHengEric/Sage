"""Exercise genuine official world-state/milestone behavior, not canned scores."""
import copy
import hashlib
import json

import pytest

pytest.importorskip('polars')
pytest.importorskip('scipy')

from evaluation_datasets.toolsandbox import runtime
from evaluation_datasets.toolsandbox.export_dataset import build_dataset, family
from evaluation_datasets.toolsandbox.scorer import DESCRIPTOR, SCORER_TEST_CASES, score
from sagents.v2.optimization.python_scorer import PythonExecutionScorer
from sagents.v2.optimization.scoring import ScoringRequest


def test_export_is_reproducible_offline_and_family_disjoint():
    dataset = build_dataset()
    assert (runtime.ROOT / 'rsi.dataset.json').read_text() == dataset.model_dump_json(indent=2) + '\n'
    splits = {}
    for case in dataset.cases:
        name = case.environment_context['scenario']
        assert splits.setdefault(family(name), case.split) == case.split
        assert set(case.environment_context) == {'scenario'}
        for function in runtime.scenario(name).starting_context.get_available_tools(False).values():
            assert '.rapid_api_search_tools' not in function.__module__
    assert dataset.human_test_suite()


def test_official_milestones_do_not_trust_output_claims_or_prefilled_scores():
    for fixture in SCORER_TEST_CASES:
        request = copy.deepcopy(fixture['request'])
        request['observation']['evidence']['similarity'] = 1 - fixture['expected_score']
        assert score(request)['grade']['score'] == fixture['expected_score']
    request = copy.deepcopy(SCORER_TEST_CASES[1]['request'])
    # Claim success without changing the actual device state.
    request['observation']['evidence']['final_items'][1]['data']['arguments']['on'] = True
    request['observation']['evidence']['final_items'][2]['data']['error'] = {'code': 'mcp.tool_error'}
    assert score(request)['grade']['score'] < 1


def test_denied_call_is_not_replayed_as_a_successful_device_transition():
    request = copy.deepcopy(SCORER_TEST_CASES[1]['request'])
    request['observation']['evidence']['final_items'][2]['data']['error'] = {'code': 'authorization.denied'}
    with pytest.raises(ValueError, match='invalid measurement'):
        score(request)


def test_scenario_clock_is_utc_without_patching_host_datetime():
    import datetime
    from tool_sandbox.tools.utilities import get_current_timestamp
    from evaluation_datasets.toolsandbox.clock import frozen_clock
    original = datetime.datetime
    with frozen_clock():
        assert datetime.datetime is original
        assert get_current_timestamp() == datetime.datetime(2024, 5, 17, 12, tzinfo=datetime.timezone.utc).timestamp()
    assert datetime.datetime is original


def test_json_snapshot_roundtrip_and_case_reset():
    runtime.activate()
    context = {'scenario': 'cellular_off'}
    original = runtime.initial(context)
    changed, _, error = runtime.call(context, copy.deepcopy(original), 'set_cellular_service_status', {'on': False})
    assert not error
    changed = json.loads(json.dumps(changed))
    from tool_sandbox.common.execution_context import DatabaseNamespace
    current = runtime._set_state(changed)
    assert current.get_database(DatabaseNamespace.SETTING)['cellular'][0] is False
    fresh = runtime._set_state(runtime.initial(context))
    assert fresh.get_database(DatabaseNamespace.SETTING)['cellular'][0] is True


@pytest.mark.asyncio
async def test_scorer_import_and_isolated_worker():
    source = runtime.ROOT / 'scorer.py'
    scorer = PythonExecutionScorer(path=source, source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        descriptor=DESCRIPTOR, timeout=30)
    assert (await scorer.validate())['status'] == 'passed'
    for fixture in SCORER_TEST_CASES:
        result = await scorer.score(ScoringRequest.model_validate(fixture['request']))
        assert result.grade.score == fixture['expected_score']


def test_preflight_and_tool_schemas():
    from jsonschema import Draft202012Validator
    assert runtime.preflight()['scenarios'] > 10
    for tool in runtime.tools():
        Draft202012Validator.check_schema(tool['parameters'])
