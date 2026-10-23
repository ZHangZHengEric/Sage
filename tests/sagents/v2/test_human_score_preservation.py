import pytest
from tests.sagents.v2.test_human_test_observer import suite,event
from tests.sagents.v2.test_package_optimizer import bundle,context
from sagents.v2.optimization.observer import HumanTestObserver,IsolatedTestEvaluator


@pytest.mark.asyncio
async def test_real_scorer_result_survives_exhausted_diagnosis_without_resampling(monkeypatch):
    from sagents.v2.optimization import OptimizationAgent
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner,Scorer
    runner, scorer = Runner(),Scorer()
    evaluator=OptimizationAgent(package=bundle('eval'),agent_id='assistant')
    measure=IsolatedTestEvaluator(runner=runner,evaluator=evaluator,driver=evaluator,
        context=context(),goal='Accuracy',scorer=scorer)
    attempts=[]
    async def invalid_analysis(*args,**kwargs):
        attempts.append(1)
        raise ValueError('All permitted assessment repairs exhausted')
    monkeypatch.setattr(measure,'_ask',invalid_analysis)
    observer=HumanTestObserver(baseline=bundle(),suite=suite(),evaluate=measure,publish=lambda _:None)
    observer.observe(event('evaluation_completed',round=0,evaluation={'cases':[]}))
    await observer.finish()
    record=observer.records[0]
    assert record['status']=='error'
    assert record['scores']['test']==.2
    assert record['cases'][0]['trials'][0]['diagnosis_status']=='error'
    assert len(scorer.histories)==1
    assert len(attempts)==1
    assert observer.evidence[0]['grade']['diagnosis'] is None

@pytest.mark.asyncio
@pytest.mark.parametrize('missing_score',[False,True])
async def test_only_complete_fixed_scores_form_mean_and_diagnosis_errors_stay_visible(missing_score):
    calls=[]
    async def evaluate(*args):
        calls.append(1)
        if missing_score and len(calls)==2:
            raise RuntimeError('Scorer unavailable')
        error=ValueError('Diagnosis failed')
        error.rsi_failure_metadata={'phase':'evaluation','code':'evaluation.invalid_record','retryable':False}
        error.rsi_completed_measurement={'grade':{'score':.5 if len(calls)==1 else 1,'passed':False,'rationale':'Fixed'}}
        raise error
    observer=HumanTestObserver(baseline=bundle(),suite=suite(),evaluate=evaluate,repeats=2,publish=lambda _:None)
    observer.observe(event('evaluation_completed',round=0,evaluation={'cases':[]}))
    await observer.finish()
    record=observer.records[0]
    assert record['status']=='error'
    assert record['scores']['test']==(None if missing_score else .75)
    assert len(observer.evidence)==(1 if missing_score else 2)
