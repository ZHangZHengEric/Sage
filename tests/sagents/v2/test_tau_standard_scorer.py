import copy
import hashlib
import json

import pytest

from evaluation_datasets.tau_bench.scorer import DESCRIPTOR, ROOT, SCORER_TEST_CASES, score
from sagents.v2.optimization.python_scorer import PythonExecutionScorer
from sagents.v2.optimization.scoring import ScoringRequest


def test_official_scorer_recomputes_database_outcome_and_ignores_precomputed_reward():
    for fixture in (f for f in SCORER_TEST_CASES if 'model_responses' not in f):
        request = copy.deepcopy(fixture['request'])
        request['observation']['evidence']['tau_reward'] = {'reward': 1 - fixture['expected_score']}
        result = score(request)
        assert result['grade']['score'] == fixture['expected_score']
        assert result['details']['source'] == 'recomputed_native_execution'


def test_precomputed_reward_without_native_items_is_rejected():
    request = copy.deepcopy(SCORER_TEST_CASES[0]['request'])
    request['observation']['evidence'] = {'tau_reward': {'reward': 1}}
    with pytest.raises(ValueError, match='canonical native final_items'):
        score(request)


@pytest.mark.parametrize('met', [False, True])
def test_official_natural_language_assertions_use_scorer_owned_model(met, monkeypatch):
    request = copy.deepcopy(SCORER_TEST_CASES[0]['request'])
    reference = json.loads(request['case']['reference_answer'])
    reference['evaluation_criteria'] = {'actions': [], 'reward_basis': ['DB', 'NL_ASSERTION'],
        'nl_assertions': ['The assistant offered to help.']}
    request['case']['reference_answer'] = json.dumps(reference)
    request['observation']['evidence']['final_items'].append({'data': {'kind': 'message', 'role': 'assistant',
        'content': [{'kind': 'text', 'text': 'I can help with that.'}]}})
    from evaluation_datasets.tau_bench.runtime import activate
    activate()
    import tau2.evaluator.evaluator_nl_assertions as nl
    from tau2.data_model.message import AssistantMessage
    calls = []
    def official_generate(**kwargs):
        calls.append(kwargs)
        return AssistantMessage(role='assistant', content=json.dumps({'results': [{
            'expectedOutcome': 'The assistant offered to help.',
            'reasoning': 'Recorded assertion judgment', 'metExpectation': met}]}))
    import evaluation_datasets.tau_bench.scorer as module
    monkeypatch.setattr(module, 'generate_official_assertion', official_generate)
    result = score(request)
    assert result['grade']['score'] == int(met)
    assert len(calls) == 1
    assert calls[0]['model'] == nl.DEFAULT_LLM_NL_ASSERTIONS
    assert 'I can help with that.' in calls[0]['messages'][1].content


@pytest.mark.asyncio
async def test_imported_file_runs_official_scorer_in_the_standard_worker():
    source = ROOT / 'scorer.py'
    module = PythonExecutionScorer(path=source, source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        descriptor=DESCRIPTOR, timeout=30)
    assert (await module.validate())['status'] == 'passed'
    for fixture in (f for f in SCORER_TEST_CASES if 'model_responses' not in f):
        result = await module.score(ScoringRequest.model_validate(fixture['request']))
        assert result.grade.score == fixture['expected_score']
