"""Human-only test results cannot steer the adaptive optimizer."""
import asyncio
import json
import re

import pytest
from pydantic import ValidationError

from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite, OptimizationTestSuite
from sagents.v2.optimization.observer import HumanTestObserver
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer


def suite():
    return OptimizationTestSuite(cases=(OptimizationCase(id="sealed-test", input="HIDDEN TEST QUESTION",
        rubric="HIDDEN TEST RUBRIC", split="test"),))


def event(name, **data):
    return {"event": name, "data": data}


@pytest.mark.asyncio
async def test_test_scores_and_errors_do_not_change_optimizer_inputs_or_selection():
    payloads, outcomes = [], []
    for score in (0, 1, None):
        runner = AdaptiveRunner(scores={"base": {"training": .4, "validation": .4},
            "guidance-1": {"training": .3, "validation": .8},
            "guidance-2": {"training": .6, "validation": .8}})
        async def evaluate(package, case):
            if score is None:
                raise TimeoutError("test-only failure")
            return {"grade": {"score": score, "passed": score == 1, "rationale": "HIDDEN TEST FEEDBACK"}}
        records = []
        observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=evaluate,
            publish=lambda value: records.append(value))
        result = await optimizer(runner).optimize(bundle(), context=context(), goal="Conversions",
            rounds=2, validation_case_count=2, on_event=observer.observe)
        await observer.finish()
        requests = [json.loads(text)["data"] for name, text in runner.requests if name == "test.tuner"]
        assert "HIDDEN TEST" not in json.dumps(runner.requests)
        # Runtime package versions have random IDs; compare actual decision inputs.
        payloads.append(re.sub(r'\.opt\.[0-9a-f]{32}\.', '.opt.RUN.', json.dumps(requests, sort_keys=True)))
        outcomes.append(([r.accepted for r in result.report.rounds], result.report.termination.reason))
        assert [r["round"] for r in records[-1]] == [0, 1, 2]
        for r in records[-1]:
            assert r['scores']['test'] == score
            assert r['status'] == ('error' if score is None else 'completed')
        assert records[-1][1]['package_hash'] == result.report.rounds[0].candidate_package.content_hash
    assert payloads[0] == payloads[1] == payloads[2]
    assert outcomes[0] == outcomes[1] == outcomes[2]


@pytest.mark.asyncio
async def test_rejected_round_measures_retained_package_and_current_development_scores():
    original = bundle()
    seen = []
    async def evaluate(package, case):
        seen.append(package.content_hash)
        return {'grade': {'score': .7, 'passed': False, 'rationale': 'observed'}}
    observer = HumanTestObserver(baseline=original, suite=suite(), evaluate=evaluate, publish=lambda _: None)
    evaluation = {'cases': [{'case': {'id': 't', 'split': 'training'}, 'grade': {'score': .4}},
                            {'case': {'id': 'd', 'split': 'validation'}, 'grade': {'score': .6}}]}
    observer.observe(event('evaluation_completed', round=0, evaluation=evaluation))
    observer.observe(event('round_completed', record={'round': 1, 'accepted': False,
        'candidate_package': bundle('rejected').model_dump(mode='json'), 'evaluation': {}}))
    await observer.finish()
    assert seen == [original.content_hash] * 2
    assert observer.records[1]['scores'] == {'training': .4, 'validation': .6, 'test': .7}


@pytest.mark.asyncio
async def test_overlap_invalidates_observation_without_disclosing_to_optimizer():
    async def never(*args):
        pytest.fail('overlapping test must not be measured')
    observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=never, publish=lambda _: None)
    observer.observe(event('suite_fixed', suite={'cases': [{'id': 'different', 'input': 'hidden TEST question'}]}))
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    await observer.finish()
    assert observer.records[0]['status'] == 'invalid'
    assert observer.records[0]['scores']['test'] is None


@pytest.mark.asyncio
async def test_cancellation_drains_active_measurements_and_marks_pending():
    entered = asyncio.Event()
    stopped = asyncio.Event()
    async def evaluate(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=evaluate, publish=lambda _: None)
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    observer.observe(event('round_completed', record={'round': 1, 'accepted': False}))
    await entered.wait()
    await observer.cancel()
    assert stopped.is_set()
    assert all(r['status'] == 'cancelled' for r in observer.records)


def test_test_suite_cannot_enter_optimizer_suite():
    with pytest.raises(ValidationError):
        OptimizationSuite(cases=(*suite().cases, OptimizationCase(id='t', input='train', rubric='ok')))


@pytest.mark.asyncio
async def test_shared_call_limit_covers_target_and_grader_without_dialogue_deadlock():
    from contextlib import asynccontextmanager
    from sagents.v2.optimization.observer import SharedCallLimitRunner
    active, peak = 0, 0
    async def call():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return 'ok'
    class Runner:
        async def run(self):
            return await call()
        @asynccontextmanager
        async def conversation(self):
            class Session:
                async def send(self, content):
                    return await call()
            yield Session()
    semaphore = asyncio.Semaphore(1)
    optimizer_runner = SharedCallLimitRunner(Runner(), semaphore)
    test_runner = SharedCallLimitRunner(Runner(), semaphore)
    async def dialogue(runner):
        async with runner.conversation() as session:
            await session.send('question')
            await runner.run()  # grade while target session is still open
            await session.send('followup')
    await asyncio.wait_for(asyncio.gather(dialogue(optimizer_runner), dialogue(test_runner)), 1)
    assert peak == 1


@pytest.mark.asyncio
async def test_restored_checkpoints_preserve_errors_without_remeasuring_and_follow_retained_parent():
    original = bundle()
    calls = []
    async def evaluate(package, case):
        calls.append(package.content_hash)
        return {'grade': {'score': .8, 'passed': False, 'rationale': 'new checkpoint'}}
    old = {'round': 0, 'status': 'error', 'package_hash': original.content_hash,
           'valid': True, 'scores': {'training': .4, 'validation': .6, 'test': None},
           'cases': [{'id': 'sealed-test', 'status': 'error', 'error_type': 'RuntimeError', 'score': None}]}
    observer = HumanTestObserver(baseline=original, suite=suite(), evaluate=evaluate,
        publish=lambda _: None, completed_records=[old])
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    selected = bundle('new-parent')
    observer.observe(event('round_completed', record={'round': 1, 'accepted': True,
        'candidate_package': selected.model_dump(mode='json'), 'evaluation': {'cases': []}}))
    await observer.finish()
    assert calls == [selected.content_hash]
    assert observer.records[0] == old
    assert observer.records[1]['scores']['test'] == .8
    assert observer.records[0] is not old
    with pytest.raises(ValueError, match='terminal'):
        HumanTestObserver(baseline=original, suite=suite(), evaluate=evaluate,
            publish=lambda _: None, completed_records=[{**old, 'status': 'running'}])


@pytest.mark.asyncio
async def test_independent_test_repeats_preserve_trials_and_average_only_complete_measurements():
    snapshots = []
    calls = []
    async def evaluate(package, case):
        index = len(calls)
        calls.append(package.content_hash)
        return {'grade': {'score': index / 2, 'passed': index == 2, 'rationale': f'trial-{index + 1}'},
                'conversation': [{'user': f'question-{index + 1}', 'target': {'output': f'answer-{index + 1}'}}]}
    observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=evaluate,
        repeats=3, concurrency=1, publish=snapshots.append)
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    await observer.finish()
    record = observer.records[0]
    row = record['cases'][0]
    assert len(calls) == 3
    assert record['repeats'] == 3
    assert record['scores']['test'] == row['score'] == .5
    assert row['passed'] is False
    assert [t['trial'] for t in row['trials']] == [1, 2, 3]
    assert [t['score'] for t in row['trials']] == [0, .5, 1]
    assert row['trials'][1]['conversation'][0]['target']['output'] == 'answer-2'
    assert [e['trial'] for e in observer.evidence] == [1, 2, 3]
    assert all(r[0]['scores']['test'] is None for r in snapshots if r[0]['status'] == 'running')


@pytest.mark.asyncio
async def test_repeat_failure_keeps_successes_and_does_not_fabricate_aggregate_score():
    calls = 0
    async def evaluate(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('measurement failed')
        return {'grade': {'score': 1, 'passed': True, 'rationale': 'ok'}}
    observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=evaluate,
        repeats=3, publish=lambda _: None)
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    await observer.finish()
    record = observer.records[0]
    assert record['status'] == 'error'
    assert record['scores']['test'] is None
    assert record['cases'][0]['score'] is None
    assert [t['status'] for t in record['cases'][0]['trials']] == ['completed', 'error', 'completed']


@pytest.mark.parametrize('repeats', [0, 11])
def test_test_repeat_limits(repeats):
    with pytest.raises(ValueError, match='repeats'):
        HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=None, publish=None, repeats=repeats)


@pytest.mark.asyncio
async def test_different_dialogue_scenarios_can_share_a_greeting_without_invalidating_test():
    held = suite().cases[0].model_copy(update={'input': 'Hello.', 'mode': 'dialogue',
        'user_context': 'Private observation scenario'})
    async def evaluate(package, case):
        return {'grade': {'score': .5, 'passed': False, 'rationale': 'Observed'}}
    observer = HumanTestObserver(baseline=bundle(), suite=OptimizationTestSuite(cases=(held,)),
        evaluate=evaluate, publish=lambda _: None)
    observer.observe(event('suite_fixed', suite={'cases': [{'id': 'train', 'input': 'Hello.',
        'mode': 'dialogue', 'user_context': 'Different training scenario'}]}))
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    await observer.finish()
    assert observer.records[0]['status'] == 'completed'
    assert observer.records[0]['scores']['test'] == .5


@pytest.mark.asyncio
@pytest.mark.parametrize('safe_role', [False, True])
async def test_measurement_diagnosis_transport_retry_preserves_execution_and_score(safe_role):
    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.contracts import OptimizationObservation
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner, Scorer
    class InterruptedDiagnosis(Runner):
        failed = 0
        async def run(self, package, agent_id, content, ctx):
            if json.loads(content).get('response_schema', {}).get('title') == 'OptimizationDiagnosis' and not self.failed:
                self.failed += 1
                return OptimizationObservation(state='suspended', evidence={'runtime_events': [
                    {'type': 'interaction.requested', 'data': {'payload': {'error': {
                        'code': 'model.stream_incomplete', 'category': 'provider_transient', 'retryable': True}}}}]})
            return await super().run(package, agent_id, content, ctx)
    runner, scorer = InterruptedDiagnosis(), Scorer()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    if safe_role:
        data = evaluator.model_dump(mode='json')
        data['package']['manifest']['agents']['assistant']['tools'] = []
        evaluator = OptimizationAgent.model_validate(data)
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=scorer)
    case = suite().cases[0].model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 1})
    if not safe_role:
        from sagents.v2.optimization.observer import HumanTestExecutionFailure
        with pytest.raises(HumanTestExecutionFailure):
            await measure(bundle(), case)
        assert runner.failed == 1 and len(scorer.histories) == 1
        return
    result = await measure(bundle(), case)
    assert runner.failed == 1 and len(runner.diagnoses) == 1
    assert len(scorer.histories) == 1 and len(result['conversation']) == 1
    assert result['infrastructure_retries'] == {'evaluation': 1}
    assert result['grade']['score'] == pytest.approx(.2)


@pytest.mark.asyncio
@pytest.mark.parametrize('disposable', [False, True])
async def test_measurement_target_restart_requires_explicit_disposable_grant(disposable):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.contracts import OptimizationObservation
    from sagents.v2.optimization.observer import IsolatedTestEvaluator, HumanTestExecutionFailure
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner, Scorer
    class InterruptedTarget(Runner):
        sends = 0
        @asynccontextmanager
        async def conversation(self, *args):
            async def send(content):
                self.sends += 1
                if self.sends == 1:
                    return OptimizationObservation(state='failed', evidence={'error': {
                        'code': 'model.provider_transient', 'category': 'provider_transient', 'retryable': True}})
                return OptimizationObservation(state='completed', output='Valid completed reply')
            yield SimpleNamespace(send=send)
    runner, scorer = InterruptedTarget(), Scorer()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=scorer, restart_incomplete_dialogues=disposable)
    case = suite().cases[0].model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 1})
    if disposable:
        result = await measure(bundle(), case)
        assert runner.sends == 2 and len(scorer.histories) == 1
        assert result['infrastructure_retries'] == {'execution': 1}
    else:
        with pytest.raises(HumanTestExecutionFailure) as error:
            await measure(bundle(), case)
        assert error.value.rsi_failure_metadata == {'phase': 'execution', 'code': 'model.provider_transient',
            'state': 'failed', 'retryable': True, 'suspension_reason': None,
            'infrastructure_retries': {}, 'retry_budget_exhausted': False}
        assert runner.sends == 1 and not scorer.histories


@pytest.mark.asyncio
async def test_measurement_phase_metadata_contains_no_hidden_content():
    from sagents.v2.optimization.observer import HumanTestExecutionFailure
    async def evaluate(package, case):
        raise HumanTestExecutionFailure('evaluation', code='model.provider_permanent')
    observer = HumanTestObserver(baseline=bundle(), suite=suite(), evaluate=evaluate, publish=lambda _: None)
    observer.observe(event('evaluation_completed', round=0, evaluation={'cases': []}))
    await observer.finish()
    trial = observer.records[0]['cases'][0]['trials'][0]
    assert trial['status'] == 'error'
    assert trial['failure']['phase'] == 'evaluation'
    assert trial['failure']['retryable'] is False
    assert observer.records[0]['scores']['test'] is None
    assert 'HIDDEN' not in json.dumps(trial['failure'])


@pytest.mark.asyncio
async def test_valid_zero_measurement_is_not_retried_or_resampled():
    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.contracts import OptimizationGrade
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from sagents.v2.optimization.scoring import ScoringResult
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner, Scorer
    class FailedTask(Scorer):
        async def score(self, request):
            self.histories.append(request.conversation)
            return ScoringResult(grade=OptimizationGrade(score=0, passed=False, rationale='Valid task failure'))
    runner, scorer = Runner(), FailedTask()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=scorer, restart_incomplete_dialogues=True)
    case = suite().cases[0].model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 1})
    result = await measure(bundle(), case)
    assert result['grade']['score'] == 0 and not result['grade']['passed']
    assert len(scorer.histories) == 1 and result['infrastructure_retries'] == {}
