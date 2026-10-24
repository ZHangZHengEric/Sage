"""Offline scheduling regressions: no provider, live host or runtime directory."""
import asyncio
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
from sagents.v2.optimization.observer import HumanTestObserver, SharedCallPool, SharedCallLimitRunner
from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


async def until(event):
    await asyncio.wait_for(event.wait(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("call_retries", [0, 1])
async def test_slow_first_repeat_does_not_block_second_repeat(call_retries, tmp_path):
    blocked, later, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first = suite().cases[0].input

    class Script(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.target':
                if content == first and OPTIMIZATION_TRIAL.get() == 1 and not blocked.is_set():
                    blocked.set()
                    await release.wait()
                if OPTIMIZATION_TRIAL.get() == 2:
                    later.set()
            return await super().run(package, agent_id, content, ctx)

    task = asyncio.create_task(optimizer(Script()).optimize(bundle(), context=context(),
        goal='Conversions', rounds=1, suite=suite(), validation_case_count=None,
        evaluation_repeats=2, max_concurrency=2, call_retries=call_retries,
        journal_path=tmp_path / "audit.jsonl", final_max_cases=0))
    try:
        await until(blocked)
        await until(later)
        assert not release.is_set()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize('test_score', [0, 1, None])
async def test_baseline_tests_start_early_and_gate_next_round_without_feedback(test_score):
    train_entered, test_entered = asyncio.Event(), asyncio.Event()
    release_train, release_test, at_barrier = asyncio.Event(), asyncio.Event(), asyncio.Event()
    second_repeat = asyncio.Event()
    runner = Runner()
    first = suite().cases[0].input

    class Script:
        async def run(self, package, agent_id, content, ctx):
            if content == first and not train_entered.is_set():
                train_entered.set()
                await release_train.wait()
            return await runner.run(package, agent_id, content, ctx)

    pool_states = []
    pool = SharedCallPool(3, pool_states.append)
    opt = optimizer(SharedCallLimitRunner(Script(), pool))
    async def measure(package, case):
        async with pool:
            test_entered.set()
            if OPTIMIZATION_TRIAL.get() == 2:
                second_repeat.set()
            if case.id == 'slow' and OPTIMIZATION_TRIAL.get() == 1:
                await release_test.wait()
            if test_score is None:
                raise TimeoutError('human-only test error')
            return {'grade': {'score': test_score, 'passed': bool(test_score), 'rationale': 'PRIVATE TEST'}}

    observer = HumanTestObserver(baseline=bundle(), concurrency=3, repeats=2,
        suite=OptimizationTestSuite(cases=tuple(OptimizationCase(id=i, input=i,
            rubric='PRIVATE TEST', split='test') for i in ('slow', 'fast'))),
        evaluate=measure, publish=lambda _: None)
    async def barrier(index, package_hash):
        if index == 0:
            at_barrier.set()
        await observer.wait_for_checkpoint(index, package_hash)
    task = asyncio.create_task(opt.optimize(bundle(), context=context(), goal='Conversions',
        rounds=1, suite=suite(), validation_case_count=None, final_max_cases=0,
        max_concurrency=3, on_event=observer.observe, checkpoint_barrier=barrier))
    try:
        await until(train_entered)
        await until(test_entered)
        await until(second_repeat)  # Another repeat starts while the first is blocked.
        assert not at_barrier.is_set()  # Test admitted before baseline train/dev completes.
        release_train.set()
        await until(at_barrier)
        assert not any(name == 'test.tuner' for name, _ in runner.requests)
        assert not task.done()
        release_test.set()
        result = await asyncio.wait_for(task, 5)
        await observer.finish()
        assert len(result.report.rounds) == 1
        assert 'PRIVATE TEST' not in json.dumps(runner.requests)
        assert [r['round'] for r in observer.records] == [0, 1]
        assert all(r['status'] == ('error' if test_score is None else 'completed') for r in observer.records)
        assert max(s['active'] for s in pool_states) == 3
        assert all(0 <= s['active'] <= 3 for s in pool_states)
        assert pool.active == pool.waiting == 0
    finally:
        release_train.set()
        release_test.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await observer.cancel()


@pytest.mark.asyncio
async def test_cancelled_waiter_and_failed_call_return_every_shared_slot():
    states = []
    pool = SharedCallPool(1, states.append)
    entered = asyncio.Event()
    async def waiter():
        entered.set()
        async with pool:
            pytest.fail('cancelled call must not enter')
    async with pool:
        waiting = asyncio.create_task(waiter())
        await until(entered)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert pool.active == 1 and pool.waiting == 0
    with pytest.raises(RuntimeError):
        async with pool:
            raise RuntimeError('fixture')
    assert pool.active == pool.waiting == 0
    async with pool:
        assert pool.active == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('branch', ['noop', 'invalid', 'review_rejected'])
async def test_rejected_and_unchanged_rounds_also_wait_for_their_measurements(branch):
    proposal = {'rationale': 'No change'} if branch == 'noop' else {
        'rationale': 'Try guidance', 'instruction_guidance': 'guidance-1'}
    if branch == 'invalid':
        proposal = {'rationale': 'Forbidden budget', 'budget': {'max_steps': 999999}}
    class Script(Runner):
        async def run(self, package, agent_id, content, ctx):
            if branch == 'review_rejected' and package.manifest.metadata.id == 'test.reviewer':
                from sagents.v2.optimization.contracts import OptimizationObservation
                return OptimizationObservation(state='completed', output=json.dumps({
                    'approved': False, 'rationale': 'Unacceptable change',
                    'goal_drift_detected': True, 'permission_drift_detected': False}))
            return await super().run(package, agent_id, content, ctx)
    async def measure(package, case):
        await asyncio.sleep(0)
        return {'grade': {'score': 0, 'passed': False, 'rationale': 'PRIVATE TEST'}}
    observer = HumanTestObserver(baseline=bundle(), evaluate=measure, publish=lambda _: None,
        suite=OptimizationTestSuite(cases=(OptimizationCase(id='human', input='PRIVATE', rubric='PRIVATE', split='test'),)))
    completed = []
    async def barrier(index, package_hash):
        await observer.wait_for_checkpoint(index, package_hash)
        assert next(r for r in observer.records if r['round'] == index)['status'] == 'completed'
        completed.append(index)
    result = await optimizer(Script(proposals=[proposal])).optimize(bundle(), context=context(),
        goal='Conversions', rounds=1, suite=suite(), validation_case_count=None,
        final_max_cases=0, max_edit_repairs=0, on_event=observer.observe, checkpoint_barrier=barrier)
    await observer.finish()
    assert completed == [0, 1]
    assert not result.report.rounds[0].accepted
    assert observer.records[1]['package_hash'] == bundle().content_hash
