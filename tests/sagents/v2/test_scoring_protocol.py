import pytest

from evaluation_datasets.tau_bench.scorer import TauBenchScorer
from sagents.v2.optimization import OptimizationDataset, ScorerDescriptor, ScoringRequest, ScoringResult
from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationObservation
from tests.sagents.v2.test_package_optimizer import bundle, context, optimizer, suite
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [0, .5, 1])
async def test_precomputed_reward_alone_is_not_an_official_scoring_input(value):
    request = ScoringRequest(goal='Service', case=suite().cases[0],
        observation=OptimizationObservation(state='completed', evidence={'tau_reward': {'reward': value}}))
    with pytest.raises(ValueError, match='reference_answer'):
        await TauBenchScorer().score(request)


@pytest.mark.asyncio
async def test_standard_scorer_fixes_numbers_while_eval_still_diagnoses_execution():
    class Scorer:
        descriptor = ScorerDescriptor(id='contract-check', name='Contract check', version='1')
        requests = []
        async def score(self, request):
            self.requests.append(request)
            return ScoringResult(grade=OptimizationGrade(score=.25, passed=False, rationale='Fixed external score'),
                details={'reason': 'SEALED_DEV_SCORER_REASON' if request.case.split == 'validation' else 'TRAIN_SCORER_REASON'})
    scorer = Scorer()
    runner = DiagnosticRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1, scorer=scorer)
    assert all(c.grade.score == .25 for c in result.report.baseline.cases)
    assert all(c.grade.diagnosis for c in result.report.baseline.cases)
    assert scorer.requests and runner.summaries
    import json
    tuning_requests = [text for name, text in runner.requests if name == 'test.tuner']
    assert tuning_requests
    assert all('SEALED_DEV_SCORER_REASON' not in text for text in tuning_requests)
    assert all('SEALED_DEV_SCORER_REASON' not in json.dumps(summary) for summary in runner.summaries)
    assert next(c for c in result.report.baseline.cases if c.case.split == 'validation').grade.scorer_details == {
        'reason': 'SEALED_DEV_SCORER_REASON'}
    with pytest.raises(ValueError, match='not both'):
        await optimizer(runner).optimize(bundle(), context=context(), goal='x', scorer=scorer, authoritative_grader=lambda *a: None)


def test_dataset_answers_and_splits_follow_one_schema():
    dataset = OptimizationDataset(name='Conversions', cases=suite().cases)
    assert dataset.optimization_suite() == suite()
    assert dataset.human_test_suite() is None
    with pytest.raises(ValueError, match='duplicate dataset case IDs'):
        OptimizationDataset(name='bad', cases=(suite().cases[0], suite().cases[0]))


@pytest.mark.parametrize('response', [{}, {'not_applicable_reason': ' '}, {
    'grade': {'score': 1, 'passed': True, 'rationale': 'ok'},
    'not_applicable_reason': 'No reference',
}])
def test_scorer_requires_exactly_one_explicit_outcome(response):
    with pytest.raises(ValueError):
        ScoringResult.model_validate(response)


@pytest.mark.asyncio
async def test_custom_scorer_decline_never_falls_back_to_eval():
    class Scorer:
        descriptor = ScorerDescriptor(id='partial', name='Partial checker', version='1')

        async def score(self, request):
            return ScoringResult(not_applicable_reason='Generated challenge has no reference for this checker')

    runner = DiagnosticRunner()
    with pytest.raises(ValueError, match='Custom scorer cannot score case'):
        await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
            suite=suite(), validation_case_count=1, grow_training=False, rounds=1, scorer=Scorer())
    assert not runner.summaries


@pytest.mark.asyncio
async def test_checker_exception_does_not_silently_switch_to_eval():
    class Scorer:
        descriptor = ScorerDescriptor(id='broken', name='Broken checker', version='1')

        async def score(self, request):
            raise RuntimeError('checker broken')

    runner = DiagnosticRunner()
    with pytest.raises(RuntimeError, match='checker broken'):
        await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
            suite=suite(), validation_case_count=1, grow_training=False, rounds=1, scorer=Scorer())
    assert not runner.summaries


@pytest.mark.asyncio
@pytest.mark.parametrize('broken', [False, True])
async def test_human_test_never_falls_back_to_eval(broken):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.observer import IsolatedTestEvaluator

    class Runner:
        assessments = 0

        @asynccontextmanager
        async def conversation(self, *args):
            async def send(content):
                return OptimizationObservation(state='completed', output='answer')
            yield SimpleNamespace(send=send)

        async def run(self, *args):
            self.assessments += 1
            return OptimizationObservation(state='completed', output=OptimizationGrade(
                score=.6, passed=True, rationale='Whole conversation checked').model_dump_json())

    class Scorer:
        async def score(self, request):
            if broken:
                raise RuntimeError('checker unavailable')
            return ScoringResult(not_applicable_reason='Unsupported reference')

    runner = Runner()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=Scorer())
    if broken:
        with pytest.raises(RuntimeError, match='checker unavailable'):
            await measure(bundle(), suite().cases[0])
        assert runner.assessments == 0
    else:
        with pytest.raises(ValueError, match='Custom scorer cannot score'):
            await measure(bundle(), suite().cases[0])
        assert runner.assessments == 0


@pytest.mark.asyncio
async def test_human_test_custom_score_stays_fixed_while_eval_analyzes():
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    import json
    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis

    class Runner:
        analyses = 0
        @asynccontextmanager
        async def conversation(self, *args):
            async def send(content):
                return OptimizationObservation(state='completed', output='answer')
            yield SimpleNamespace(send=send)
        async def run(self, package, agent_id, content, ctx):
            self.analyses += 1
            payload = json.loads(content)
            assert payload['response_schema']['title'] == 'OptimizationDiagnosis'
            return OptimizationObservation(state='completed', output=json.dumps(diagnosis()))

    class Scorer:
        async def score(self, request):
            return ScoringResult(grade=OptimizationGrade(score=.25, passed=False, rationale='Fixed official outcome'))

    runner = Runner()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=Scorer())
    result = await measure(bundle(), suite().cases[0])
    assert result['grade']['score'] == .25
    assert result['grade']['passed'] is False
    assert result['grade']['diagnosis']['findings'] and runner.analyses == 1


def test_scorer_details_survive_grade_checkpoint_without_aliasing():
    original = ScoringResult(grade=OptimizationGrade(score=0, passed=False, rationale='Fixed'),
        details={'checks': [{'matched': False}]})
    grade = original.authoritative_grade()
    original.details['checks'][0]['matched'] = True
    recovered = OptimizationGrade.model_validate_json(grade.model_dump_json())
    assert recovered.scorer_details == {'checks': [{'matched': False}]}
    assert (recovered.score, recovered.passed) == (0, False)


def test_v1_scorer_wire_keeps_grade_shape_compatible():
    import json
    result = ScoringResult(grade=OptimizationGrade(score=0, passed=False, rationale='Fixed'),
        details={'checks': ['failed']})
    payload = json.loads(result.wire_json())
    assert set(payload['grade']) == {'score', 'passed', 'rationale', 'diagnosis'}
    assert payload['details'] == {'checks': ['failed']}
