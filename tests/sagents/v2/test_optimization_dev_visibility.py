"""Dev influences host decisions but cannot become model-facing score feedback."""
import json

import pytest

from sagents.v2.optimization.builtin_scoring import BuiltinScoring
from sagents.v2.optimization.feedback import training_growth_feedback
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


def test_growth_feedback_keeps_training_facts_not_hidden_gate_diagnostics():
    host = {'enabled': True, 'allowed': False, 'previous_round': 1,
            'training_passed': 0, 'training_total': 2, 'training_measured': 2,
            'regressed_training': 0, 'regressed_validation': 1, 'reason': 'regression',
            'future_private_score': .72341}
    visible = training_growth_feedback(host)
    assert visible == {key: host[key] for key in (
        'enabled', 'allowed', 'previous_round', 'training_passed', 'training_total',
        'training_measured', 'regressed_training')}
    assert host['regressed_validation'] == 1  # Projection must not mutate the audit.


@pytest.mark.asyncio
@pytest.mark.parametrize('file_mode', [False, True])
@pytest.mark.parametrize('scoring', ['quality', 'quality_tokens'])
async def test_dev_score_changes_do_not_change_tuner_payload_or_training_files(tmp_path, file_mode, scoring):
    async def run(offset, folder):
        folder.mkdir()
        class Metered(Runner):
            async def run(self, *args):
                result = await super().run(*args)
                return result.model_copy(update={'usage_reported': True})
        runner = Metered(scores={
            'base': {'training': .4, 'validation': .2 + offset},
            'guidance-1': {'training': .6, 'validation': .3 + offset},
            'guidance-2': {'training': .5, 'validation': .25 + offset},
        })
        engine = optimizer(runner)
        if file_mode:
            data = engine.tuner.model_dump(mode='json')
            data['package']['manifest']['agents'][engine.tuner.agent_id]['tools'] = ['file_read']
            engine.tuner = type(engine.tuner).model_validate(data)
        result = await engine.optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
            rounds=2, validation_case_count=1, grow_training=False,
            builtin_scoring=BuiltinScoring(mode=scoring), resume_optimization_id='a' * 32,
            tuner_workspace=folder / 'workspace', journal_path=folder / 'audit.jsonl')
        requests = [json.loads(content)['data'] for name, content in runner.requests if name == 'test.tuner']
        assert [r.accepted for r in result.report.rounds] == [True, False]
        assert requests[1]['selected_round'] == 1
        assert requests[1]['previous_attempts'][0]['accepted'] is True
        for request in requests:
            assert not {'validation', 'validation_history'} & request.keys()
            for attempt in request['previous_attempts']:
                assert not {'overall_before', 'overall_after', 'objective_before', 'objective_after'} & attempt.keys()
            assert 'regressed_validation' not in request['training_growth']
            assert 'reason' not in request['training_growth']
        artifacts = {str(p.relative_to(folder)): p.read_text()
            for p in folder.rglob('*') if p.is_file() and 'training-evidence' in p.parts}
        assert artifacts
        assert all('holdout-secret' not in text and 'Convert 7 cm' not in text for text in artifacts.values())
        # The existing human audit remains lossless and outside tuner evidence.
        score_file = folder / 'iterations/round-000/validation-scores.json'
        assert json.loads(score_file.read_text())[0]['score'] == .2 + offset
        assert result.report.rounds[0].overall_before is not None
        return requests, artifacts

    low_requests, low_files = await run(0, tmp_path / 'low')
    high_requests, high_files = await run(.4, tmp_path / 'high')
    # Same train evidence, packages and host outcomes: changing only hidden dev
    # scores must not reveal their values through any tuner-facing channel.
    assert low_requests == high_requests
    assert low_files == high_files


@pytest.mark.asyncio
async def test_dev_still_controls_host_retention_when_training_evidence_is_identical():
    results = []
    for dev in (.8, 0):
        runner = Runner(scores={'base': {'training': .4, 'validation': .4},
            'guidance-1': {'training': .5, 'validation': dev}})
        result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
            suite=suite(), rounds=1, validation_case_count=1, grow_training=False)
        results.append(result.report.rounds[0].accepted)
    assert results == [True, False]


@pytest.mark.asyncio
async def test_dev_only_regression_exposes_schedule_but_not_hidden_gate_reason():
    from tests.sagents.v2.test_package_optimizer import AdaptiveRunner

    runner = AdaptiveRunner(scores={
        'base': {'training': .4, 'validation': .4},
        'guidance-1': {'training': .5, 'validation': .2},
        'guidance-2': {'training': .6, 'validation': .6},
    })
    events = []
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        rounds=2, validation_case_count=2, on_event=events.append)
    assert not result.report.rounds[0].accepted
    requests = [json.loads(c)['data'] for name, c in runner.requests if name == 'test.tuner']
    growth = requests[1]['training_growth']
    assert growth['allowed'] is False and growth['regressed_training'] == 0
    assert 'regressed_validation' not in growth and 'reason' not in growth
    host, = [e['data'] for e in events if e['event'] == 'training_growth_deferred']
    assert host['regressed_validation'] == 2 and host['reason'] == 'regression'
