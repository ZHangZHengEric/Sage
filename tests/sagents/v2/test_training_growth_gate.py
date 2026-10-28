import json

import pytest

from sagents.v2.optimization.contracts import OptimizationRound, OptimizationSuite
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from tests.sagents.v2.test_optimization_evidence import measured
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer


def evaluation(train=.4, dev=.4, *, extra=False):
    from sagents.v2.optimization.contracts import OptimizationEvaluation
    cases = [measured('train', [train]), measured('dev', [dev], 'validation')]
    if extra:
        cases.append(measured('new', [0]))
    return OptimizationEvaluation(package_hash='current', cases=tuple(cases))


def decision(current, *, before=None, retained=(), missing=False):
    suite = OptimizationSuite(cases=tuple(c.case for c in evaluation(extra=missing).cases))
    previous = None if before is None else OptimizationRound(round=1, parent_hash='old',
        evaluation=current, accepted=False,
        regressions=AgentPackageOptimizer._regressions(before, current) if current else (),
        reason='Recorded comparison')
    return AgentPackageOptimizer._training_growth_decision(
        current or evaluation(), suite, previous, retained)


def test_initial_and_equal_or_improved_scores_allow_growth():
    assert decision(evaluation())['allowed']
    assert decision(evaluation(.4, .4), before=evaluation())['allowed']
    assert decision(evaluation(.5, .5), before=evaluation())['allowed']


@pytest.mark.parametrize('train,dev', [(.3, .8), (.5, .3)])
def test_any_common_case_regression_holds_growth(train, dev):
    result = decision(evaluation(train, dev), before=evaluation())
    assert not result['allowed']
    assert result['reason'] == 'regression'
    assert result['regressed_training'] + result['regressed_validation'] == 1


def test_all_training_passed_overrides_validation_regression():
    result = decision(evaluation(1, .1), before=evaluation(.4, .8))
    assert result['allowed'] and result['reason'] == 'training_passed'


def test_unmeasured_round_or_partial_training_cannot_claim_mastery():
    assert not decision(None, before=evaluation())['allowed']
    result = decision(evaluation(1, 1), missing=True)
    assert not result['allowed'] and result['reason'] == 'unmeasured_round'


def test_retained_unrepaired_regression_still_blocks_after_local_improvement():
    regressions = AgentPackageOptimizer._regressions(evaluation(.4), evaluation(.2))
    assert not decision(evaluation(.3), before=evaluation(.2), retained=regressions)['allowed']


def test_fresh_stability_failure_overrides_stale_perfect_round():
    old = evaluation(1, 1)
    fresh = evaluation(0, 1)
    previous = OptimizationRound(round=1, parent_hash='old', evaluation=old,
        accepted=True, reason='Earlier perfect result')
    suite = OptimizationSuite(cases=tuple(c.case for c in old.cases))
    regressions = AgentPackageOptimizer._regressions(old, fresh)
    result = AgentPackageOptimizer._training_growth_decision(fresh, suite, previous, regressions,
        fresh_retained=True)
    assert not result['allowed']
    assert result['training_passed'] == 0 and result['reason'] == 'regression'


def train_counts(result):
    return [sum(c.case.split == 'training' for c in r.evaluation.cases)
            for r in result.report.rounds]


@pytest.mark.asyncio
async def test_rejected_regression_pauses_one_round_and_growth_resumes():
    events = []
    runner = AdaptiveRunner(scores={'base': .4, 'guidance-1': .2, 'guidance-2': .5, 'guidance-3': .55})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        rounds=3, validation_case_count=2, on_event=events.append)
    assert train_counts(result) == [4, 4, 6]
    assert [r.accepted for r in result.report.rounds] == [False, True, True]
    deferred = [e['data'] for e in events if e['event'] == 'training_growth_deferred']
    assert [d['round'] for d in deferred] == [2]
    assert deferred[0]['reason'] == 'regression'
    requests = [json.loads(content)['data'] for name, content in runner.requests if name == 'test.tuner']
    assert requests[1]['training_growth']['allowed'] is False
    # Questions added before the rejected attempt remain unmeasured by its retained parent.
    # Deferral keeps them; it must not add another batch.
    assert {c['id'] for c in requests[1]['unmeasured_training_cases']} == {c['id'] for c in requests[0]['unmeasured_training_cases']}
    assert all('test' not in d for d in deferred)


@pytest.mark.asyncio
async def test_overall_acceptance_does_not_hide_outstanding_training_regression():
    proposals = [{'rationale': f'Change {i}', 'instruction_guidance': f'guidance-{i}'} for i in range(1, 5)]
    runner = AdaptiveRunner(proposals=proposals, scores={
        'base': .4, 'guidance-1': {'training': .3, 'validation': .8},
        'guidance-2': {'training': .35, 'validation': .85},
        'guidance-3': {'training': .5, 'validation': .9},
        'guidance-4': {'training': .55, 'validation': .95}})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        rounds=4, validation_case_count=2)
    assert all(r.accepted for r in result.report.rounds)
    assert train_counts(result) == [4, 4, 4, 6]


@pytest.mark.asyncio
async def test_training_mastery_allows_growth_despite_dev_regression():
    runner = AdaptiveRunner(scores={'base': {'training': .7, 'validation': .8},
        'guidance-1': {'training': 1, 'validation': .6},
        'guidance-2': {'training': 1, 'validation': .7}})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        rounds=2, validation_case_count=2)
    assert not result.report.rounds[0].accepted
    assert result.report.rounds[0].regressions
    assert train_counts(result) == [4, 6]


@pytest.mark.asyncio
async def test_failed_stability_check_pauses_growth_before_first_proposal():
    from collections import Counter
    from sagents.v2.optimization.contracts import OptimizationObservation, OptimizationStoppingPolicy

    class StabilityFailure(AdaptiveRunner):
        def __init__(self):
            super().__init__(scores={'base': .99, 'guidance-1': .5, 'guidance-2': .55})
            self.grades = Counter()

        async def run(self, package, agent_id, content, ctx):
            request = json.loads(content) if content.startswith('{') else {}
            data = request.get('data', {})
            if package.manifest.metadata.id == 'test.evaluator' and 'observation' in data:
                output = data['observation']['output']
                case = data['case']
                if output == 'base':
                    self.grades[case['id']] += 1
                    score = .4 if case['split'] == 'training' and self.grades[case['id']] > 1 else .99
                    self.requests.append((package.manifest.metadata.id, content))
                    return OptimizationObservation(state='completed', output=json.dumps({
                        'score': score, 'passed': score >= .6, 'rationale': 'Fresh stability observation'}))
            return await super().run(package, agent_id, content, ctx)

    events = []
    result = await optimizer(StabilityFailure()).optimize(bundle(), context=context(), goal='Accuracy',
        rounds=2, validation_case_count=2, on_event=events.append,
        stopping_policy=OptimizationStoppingPolicy(target_score=.9, patience=5))
    assert result.report.stability_checks and not result.report.stability_checks[0].passed
    assert train_counts(result) == [2, 2]
    assert [e['data']['round'] for e in events if e['event'] == 'training_growth_deferred'] == [1, 2]


@pytest.mark.asyncio
async def test_resuming_deferred_round_preserves_curriculum_and_completed_results(tmp_path):
    class CutAtSecondTuning(AdaptiveRunner):
        async def run(self, package, agent_id, content, ctx):
            request = json.loads(content) if content.startswith('{') else {}
            if package.manifest.metadata.id == 'test.tuner' and request.get('data', {}).get('round') == 2:
                raise ConnectionError('Transport interrupted before second proposal')
            return await super().run(package, agent_id, content, ctx)

    scores = {'base': .4, 'guidance-1': .2, 'guidance-2': .5, 'guidance-3': .55}
    kwargs = dict(context=context(), goal='Accuracy', rounds=3, validation_case_count=2,
        restart_readonly_roles=('tuning',), recovery_binding_id='readonly-fixture')
    first = tmp_path/'first.jsonl'
    with pytest.raises(ConnectionError):
        await optimizer(CutAtSecondTuning(scores=scores)).optimize(bundle(), journal_path=first, **kwargs)
    next_runner = AdaptiveRunner(proposals=[
        {'rationale': 'Repair', 'instruction_guidance': 'guidance-2'},
        {'rationale': 'Continue', 'instruction_guidance': 'guidance-3'}], scores=scores)
    result = await optimizer(next_runner).optimize(bundle(), journal_path=tmp_path/'resumed.jsonl',
        resume_from=first, **kwargs)
    assert train_counts(result) == [4, 4, 6]
    assert [a.round for a in result.report.training_additions] == [0, 1, 3]
    assert bundle().content_hash not in next_runner.target_hashes
    assert result.report.rounds[0].candidate_package.content_hash not in next_runner.target_hashes
