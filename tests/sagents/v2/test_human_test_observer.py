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
