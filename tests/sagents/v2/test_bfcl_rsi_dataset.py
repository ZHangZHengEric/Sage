"""Verify official BFCL replay, split isolation and standard scorer imports."""
import copy
import hashlib
import json

import pytest

from evaluation_datasets.bfcl import runtime
from evaluation_datasets.bfcl.export_dataset import build_dataset
from evaluation_datasets.bfcl.scorer import DESCRIPTOR, SCORER_TEST_CASES, score
from sagents.v2.optimization.python_scorer import PythonExecutionScorer
from sagents.v2.optimization.scoring import ScoringRequest


def test_export_matches_committed_files_and_keeps_variants_in_the_same_split():
    for filename, categories in [('rsi.dataset.json', ('base',)),
                                 ('rsi.all.dataset.json', runtime.CATEGORIES)]:
        dataset = build_dataset(categories=categories)
        assert (runtime.ROOT / filename).read_text() == dataset.model_dump_json(indent=2) + '\n'
        assert len(dataset.cases) == 200 * len(categories)
        assert len(dataset.human_test_suite().cases) == 20 * len(categories)
        splits = {}
        for case in dataset.cases:
            family = case.environment_context['task_id'].rsplit('_', 1)[1]
            assert splits.setdefault(family, case.split) == case.split
            assert set(case.environment_context) == {'task_id'}
            assert 'ground_truth' not in case.user_context


def test_official_state_and_response_checks_accept_reference_and_reject_no_calls():
    for fixture in SCORER_TEST_CASES:
        request = copy.deepcopy(fixture['request'])
        request['observation']['evidence']['bfcl_score'] = 1 - fixture['expected_score']
        assert score(request)['grade']['score'] == fixture['expected_score']


def test_script_drift_and_missing_native_results_are_not_silently_scored():
    request = copy.deepcopy(SCORER_TEST_CASES[1]['request'])
    request['conversation'][1]['user'] = 'invented question'
    assert 'not_applicable_reason' in score(request)
    request = copy.deepcopy(SCORER_TEST_CASES[1]['request'])
    request['conversation'][0]['target']['evidence']['final_items'].pop()
    with pytest.raises(ValueError, match='completed result'):
        score(request)


def test_denied_call_cannot_be_replayed_as_a_successful_write():
    request = copy.deepcopy(SCORER_TEST_CASES[1]['request'])
    request['conversation'][0]['target']['evidence']['final_items'][2]['data']['error'] = {'code': 'authorization.denied'}
    with pytest.raises(ValueError, match='invalid measurement'):
        score(request)


def test_live_backend_call_log_reconstructs_state_without_reference_calls():
    runtime.activate()
    context = {'task_id': 'multi_turn_base_0'}
    first, _, error = runtime.call(context, runtime.initial(context), 'cd', {'folder': 'document'})
    assert not error
    second, _, error = runtime.call(context, json.loads(json.dumps(first)), 'mkdir', {'dir_name': 'private'})
    assert not error
    _, output, _ = runtime.call(context, second, 'ls', {})
    assert 'private' in output
    _, fresh, _ = runtime.call(context, runtime.initial(context), 'ls', {})
    assert 'private' not in fresh


@pytest.mark.asyncio
async def test_scorer_import_and_worker_execute_official_positive_and_negative_cases():
    source = runtime.ROOT / 'scorer.py'
    scorer = PythonExecutionScorer(path=source, source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        descriptor=DESCRIPTOR, timeout=30)
    assert (await scorer.validate())['status'] == 'passed'
    for fixture in SCORER_TEST_CASES:
        result = await scorer.score(ScoringRequest.model_validate(fixture['request']))
        assert result.grade.score == fixture['expected_score']


def test_preflight_loads_every_backend_and_mcp_schemas_are_valid():
    pytest.importorskip('mpmath')
    from jsonschema import Draft202012Validator
    assert runtime.preflight()['tasks'] == 600
    for tool in runtime.tools():
        Draft202012Validator.check_schema(tool['parameters'])
