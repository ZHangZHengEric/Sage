"""Training budgets govern cumulative suites without replaying historical rounds."""
import pytest

from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer


@pytest.mark.asyncio
async def test_generated_training_uses_independent_initial_and_increment_sizes():
    runner = AdaptiveRunner()
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Conversions", rounds=2,
        validation_case_count=1, initial_training_case_count=3,
        training_cases_per_round=2,
    )
    assert [d['case_count'] for split, d in runner.designs if split == 'training'] == [3, 2, 2]
    assert [len(a.cases) for a in result.report.training_additions] == [3, 2, 2]
    assert sum(c.split == 'training' for c in result.report.suite.cases) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize('pool_size,increment,expected,generated', [(8, 2, 6, []), (3, 2, 3, []), (8, 0, 2, [])])
async def test_imported_pool_is_consumed_in_order_before_designer(pool_size, increment, expected, generated):
    runner = AdaptiveRunner()
    pool = [OptimizationCase(id=f'pool-{i}', input=f'Conversion {i}', rubric='Correct conversion') for i in range(pool_size)]
    dev = OptimizationCase(id='dev', input='Independent conversion', rubric='Correct conversion', split='validation')
    events = []
    result = await optimizer(runner).optimize(
        bundle(), context=context(), goal="Conversions", rounds=2,
        suite=OptimizationSuite(cases=(*pool, dev)), validation_case_count=1,
        initial_training_case_count=2, training_cases_per_round=increment, on_event=events.append,
    )
    # An imported dataset is never topped up with generated questions.
    exhausted = any(e['event'] == 'training_pool_exhausted' for e in events)
    assert exhausted == (increment > 0 and pool_size < 2 + 2 * increment)
    training = [c for c in result.report.suite.cases if c.split == 'training']
    assert len(training) == expected
    assert [c.id for c in training[:min(pool_size, expected)]] == [c.id for c in pool[:expected]]
    assert [d['case_count'] for split, d in runner.designs if split == 'training'] == generated
    assert [c.case.id for c in result.report.baseline.cases if c.case.split == 'training'] == ['pool-0', 'pool-1']


@pytest.mark.asyncio
async def test_no_change_round_still_measures_new_training_cases(monkeypatch):
    runner = AdaptiveRunner(proposals=[{'rationale': 'No change is justified'}, {'rationale': 'No change is justified'}])
    pool = [OptimizationCase(id=f'pool-{i}', input=f'Conversion {i}', rubric='Correct') for i in range(3)]
    dev = OptimizationCase(id='dev', input='Independent conversion', rubric='Correct', split='validation')
    events = []
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions', rounds=2,
        suite=OptimizationSuite(cases=(*pool, dev)), validation_case_count=1,
        initial_training_case_count=1, training_cases_per_round=1, on_event=events.append)
    assert [len(row.evaluation.cases) for row in result.report.rounds] == [3, 4]
    # New cases run on the retained version first; an unchanged proposal reuses that measurement.
    challenges = [e['data'] for e in events if e['event'] == 'training_challenge_completed']
    assert [[c['case']['id'] for c in d['evaluation']['cases']] for d in challenges] == [['pool-1'], ['pool-2']]
    assert all(row.evaluation_reused for row in result.report.rounds)


@pytest.mark.asyncio
@pytest.mark.parametrize('grow', [False, True])
async def test_new_failures_reach_next_tuning_and_current_human_metadata_without_rewriting_baseline(monkeypatch, grow):
    import json
    from sagents.v2.optimization.contracts import OptimizationObservation, OptimizationTestSuite
    from sagents.v2.optimization.observer import HumanTestObserver
    class NewCaseFails(AdaptiveRunner):
        sent=[]
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.target':
                self.sent.append(content)
                if content == 'Conversion 1':
                    return OptimizationObservation(state='completed', output='new-failure')
            return await super().run(package, agent_id, content, ctx)
    runner=NewCaseFails(proposals=[{'rationale':'No change justified'}]*2,
        scores={'base':.9,'new-failure':0})
    pool=[OptimizationCase(id=f'pool-{i}',input=f'Conversion {i}',rubric='Correct') for i in range(3)]
    dev=OptimizationCase(id='dev',input='Independent conversion',rubric='Correct',split='validation')
    async def measure(package,case):return {'grade':{'score':.5,'passed':False,'rationale':'Human measurement'}}
    observer=HumanTestObserver(baseline=bundle(),suite=OptimizationTestSuite(cases=(
        OptimizationCase(id='sealed',input='PRIVATE TEST',rubric='PRIVATE TEST',split='test'),)),evaluate=measure,publish=lambda _:None)
    result=await optimizer(runner).optimize(bundle(),context=context(),goal='Conversions',rounds=2,
        suite=OptimizationSuite(cases=(*pool,dev)),validation_case_count=1,initial_training_case_count=1,
        training_cases_per_round=1 if grow else 0,on_event=observer.observe)
    await observer.finish()
    assert len(result.report.baseline.cases)==2
    assert [len(r.evaluation.cases) for r in result.report.rounds]==([3,4] if grow else [2,2])
    assert [len(r['development_cases']) for r in observer.records]==([2,3,4] if grow else [2,2,2])
    assert sorted(runner.sent)==sorted(['Conversion 0','Independent conversion',
        *(['Conversion 1','Conversion 2'] if grow else [])])
    requests=[json.loads(s)['data'] for name,s in runner.requests if name=='test.tuner']
    assert 'PRIVATE TEST' not in json.dumps(requests)
    if grow:
        row=next(t for t in requests[1]['training'] if t['case']['id']=='pool-1')
        assert row['grade']['score']==0
        assert not result.report.rounds[0].accepted
