import hashlib

import pytest

from sagents.v2.optimization.python_scorer import PythonExecutionScorer, ScorerExecutionError
from sagents.v2.optimization.scoring import ScorerDescriptor, ScoringRequest
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationObservation


def scorer(tmp_path, source, timeout=5):
    path = tmp_path / 'scorer.py'
    path.write_text(source)
    return PythonExecutionScorer(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        descriptor=ScorerDescriptor(id='fixture', name='Fixture', version='1'), timeout=timeout)


def request():
    return ScoringRequest(goal='Accuracy', case=OptimizationCase(id='train', input='6*7?', rubric='42', reference_answer='42'),
        observation=OptimizationObservation(state='completed', output='42'))


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['def', 'async def'])
async def test_python_sync_and_async_use_standard_answer_and_execution(tmp_path, prefix):
    module = scorer(tmp_path, f'''{prefix} score(request):
    print("module diagnostic")
    correct = request['case']['reference_answer'] == request['observation']['output']
    return {{'score': .8 if correct else 0, 'passed': correct, 'rationale': 'Compared answer'}}
''')
    result = await module.score(request())
    assert result.grade.score == .8 and result.grade.passed


@pytest.mark.asyncio
async def test_large_valid_json_is_read_to_eof(tmp_path):
    module = scorer(tmp_path, "def score(request):\n return {'grade': {'score': .5, 'passed': False, 'rationale': 'Compared'}, 'details': {'trace': 'x' * 150000}}\n")
    result = await module.score(request())
    assert len(result.details['trace']) == 150000


@pytest.mark.asyncio
@pytest.mark.parametrize('source,error', [
    ("def score(request):\n raise RuntimeError('broken')\n", ScorerExecutionError),
    ("def score(request):\n return {'score': 2, 'passed': True, 'rationale': 'Invalid'}\n", ScorerExecutionError),
    ("def score(request):\n import time; time.sleep(10)\n", TimeoutError),
])
async def test_broken_or_slow_scorer_is_not_a_zero_grade(tmp_path, source, error):
    with pytest.raises(error):
        await scorer(tmp_path, source, timeout=.7).score(request())


@pytest.mark.asyncio
async def test_mutated_frozen_source_is_rejected(tmp_path):
    module = scorer(tmp_path, "def score(request):\n return {}\n")
    module.path.write_text("def score(request):\n return {'score': 1}\n")
    with pytest.raises(ScorerExecutionError, match='changed'):
        await module.score(request())


@pytest.mark.asyncio
async def test_python_scorer_can_explicitly_decline_without_inventing_a_score(tmp_path):
    module = scorer(tmp_path, "def score(request):\n return {'not_applicable_reason': 'No supported reference answer'}\n")
    result = await module.score(request())
    assert result.grade is None
    assert result.not_applicable_reason == 'No supported reference answer'


@pytest.mark.asyncio
@pytest.mark.parametrize('numeric_case', [True, False])
async def test_import_validation_requires_a_real_scoring_case_even_with_decline_cases(tmp_path, numeric_case):
    supported = request().model_dump(mode='json')
    unsupported = request().model_copy(update={'case': request().case.model_copy(update={'reference_answer': None})}).model_dump(mode='json')
    cases = [{'request': unsupported, 'expected_applicable': False}]
    if numeric_case:
        cases.append({'request': supported, 'expected_score': 1, 'expected_passed': True})
    module = scorer(tmp_path, '''def score(request):
    if request['case']['reference_answer'] is None:
        return {'not_applicable_reason': 'Reference absent'}
    return {'score': 1, 'passed': True, 'rationale': 'Reference matched'}
SCORER_TEST_CASES = ''' + repr(cases))
    if numeric_case:
        assert (await module.validate())['cases'] == 2
    else:
        with pytest.raises(ScorerExecutionError, match='at least one numeric'):
            await module.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize('grade', ["{'score': True, 'passed': True, 'rationale': 'bad'}", "{'score': '1', 'passed': True, 'rationale': 'bad'}", "{'score': 1, 'passed': 'true', 'rationale': 'bad'}"])
async def test_python_grade_rejects_coerced_protocol_types(tmp_path, grade):
    with pytest.raises(ScorerExecutionError):
        await scorer(tmp_path, 'def score(request):\n return ' + grade + '\n').score(request())


@pytest.mark.asyncio
async def test_early_worker_import_failure_with_large_input_is_typed_not_broken_pipe(tmp_path):
    module = scorer(tmp_path, "raise ImportError('private credential must not escape')\n", timeout=10)
    large = request().model_copy(update={
        'observation': OptimizationObservation(state='completed', output='x' * 2_000_000)})
    with pytest.raises(ScorerExecutionError, match='ImportError') as caught:
        await module.score(large)
    assert 'private credential' not in str(caught.value)
