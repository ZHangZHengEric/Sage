"""Actual pre-measurement gates and retained-first discovery, using fake models."""
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationExperiment, OptimizationObservation
from sagents.v2.optimization.experiments import validate_experiment
from tests.sagents.v2.test_package_optimizer import Runner, optimizer, bundle, context, suite
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner


def experiment(parent_hash=None, **updates):
    data = dict(parent_hash=parent_hash or bundle().content_hash,
        mechanism='Use dimensional analysis before arithmetic', applicability='Unit conversions',
        change_locations=['manifest.agents.assistant.instructions'], existing_rule_gap='Current procedure lacks unit cancellation',
        expected_observation='Cancel units before computing', support_condition='Prior failure becomes correct with unit cancellation',
        falsification_condition='Same unit error persists despite cancellation', inconclusive_condition='No relevant execution evidence',
        training_case_ids=['train'], protection_case_ids=[], protected_behaviors=['Preserve required refusal boundaries'])
    return OptimizationExperiment(**{**data, **updates})


@pytest.mark.parametrize('updates,error', [
    ({'parent_hash': 'other'}, 'retained version'),
    ({'training_case_ids': ['holdout-secret']}, 'only measured training'),
    ({'protection_case_ids': ['test']}, 'only measured training'),
    ({'mechanism': ' '}, 'at least 1 character'),
    ({'falsification_condition': 'Prior failure becomes correct with unit cancellation'}, 'distinguish'),
])
def test_predeclared_experiment_rejects_wrong_binding_or_hidden_cases(updates, error):
    from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationGrade
    measured = [OptimizationCaseResult(case=suite().cases[0], observation=OptimizationObservation(state='completed'),
        grade=OptimizationGrade(score=1, passed=True, rationale='Fixed'))]
    with pytest.raises(ValueError, match=error):
        validate_experiment(experiment(**updates), bundle(), measured)


@pytest.mark.asyncio
async def test_experiment_is_bound_and_journaled_before_candidate_execution(tmp_path):
    events = []
    class Script(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.target' and package.content_hash != bundle().content_hash:
                assert any(e['event'] == 'experiment_declared' for e in events)
            return await super().run(package, agent_id, content, ctx)
    runner = Script(proposals=[{'rationale': 'Test one mechanism', 'instruction_guidance': 'guidance-1',
        'experiment': experiment().model_dump(mode='json')}])
    opt = optimizer(runner)
    opt.require_experiment = True
    result = await opt.optimize(bundle(), context=context(), goal='Conversions', suite=suite(), rounds=1,
        validation_case_count=None, grow_training=False, final_max_cases=0, on_event=events.append)
    declared, = [e['data'] for e in events if e['event'] == 'experiment_declared']
    assert declared['parent_hash'] == bundle().content_hash
    assert declared['actual_changes'] == ['manifest.agents.assistant.instructions']
    assert result.report.rounds[0].patch.experiment == experiment()


@pytest.mark.asyncio
async def test_missing_experiment_prevents_any_candidate_execution():
    runner = Runner(proposals=[{'rationale': 'Unverified edit', 'instruction_guidance': 'guidance-1'}])
    opt = optimizer(runner)
    opt.require_experiment = True
    result = await opt.optimize(bundle(), context=context(), goal='Conversions', suite=suite(), rounds=1,
        validation_case_count=None, grow_training=False, final_max_cases=0, max_edit_repairs=0)
    assert not result.report.rounds[0].accepted
    assert result.report.rounds[0].candidate_package is None
    assert set(runner.target_hashes) == {bundle().content_hash}


@pytest.mark.asyncio
async def test_discovery_cases_measure_retained_before_tuner_and_keep_previous_failures():
    events = []
    added = suite().cases[0].model_copy(update={'id': 'fresh-training', 'input': 'New conversion'})
    class Script(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                assert any(e['event'] == 'training_challenge_completed' for e in events)
                payload = json.loads(content)
                cases = {item['case']['id']: item for item in payload['data']['training']}
                assert 'fresh-training' in cases
                assert cases['fresh-training']['grade']['score'] == .4
                assert payload['data']['unmeasured_training_cases'] == []
            return await super().run(package, agent_id, content, ctx)
    runner = Script(proposals=[{'rationale': 'No unsupported edit'}])
    expanded = suite().model_copy(update={'cases': (*suite().cases, added)})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions', suite=expanded,
        initial_training_case_count=1, rounds=1, validation_case_count=1, training_cases_per_round=1,
        final_max_cases=0, on_event=events.append)
    challenge, = [e['data'] for e in events if e['event'] == 'training_challenge_completed']
    assert challenge['evaluation']['package_hash'] == bundle().content_hash
    assert challenge['evaluation']['cases'][0]['grade']['score'] == .4
    assert len(result.report.selected.cases) == len(suite().cases) + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['measure', 'measurement_issue', 'no_change'])
async def test_eval_can_request_verification_without_forcing_an_edit(action):
    class Script(DiagnosticRunner):
        async def run(self, package, agent_id, content, ctx):
            payload = json.loads(content) if package.manifest.metadata.id != 'test.target' else {}
            if package.manifest.metadata.id == 'test.tuner':
                raise AssertionError('No supported mechanism: tuner must not be forced to edit')
            if payload.get('response_schema', {}).get('title') == 'OptimizationDiagnosisSummary':
                return OptimizationObservation(state='completed', output=json.dumps({
                    'summary': 'Need evidence before intervention', 'priorities': [], 'next_action': action,
                    'next_verification': 'Measure a training case with a different initial state'}))
            return await super().run(package, agent_id, content, ctx)
    opt = optimizer(Script())
    opt.require_experiment = True
    result = await opt.optimize(bundle(), context=context(), goal='Conversions', suite=suite(), rounds=1,
        validation_case_count=1, grow_training=False, final_max_cases=0)
    assert result.report.rounds[0].candidate_package is None
    assert result.report.rounds[0].reason == 'No candidate: ' + action


@pytest.mark.asyncio
async def test_recovery_preserves_retained_discovery_without_reusing_it_as_candidate_evidence(tmp_path):
    from tests.sagents.v2.test_optimization_recovery import safe_optimizer
    added = suite().cases[0].model_copy(update={'id': 'fresh', 'input': 'New conversion'})
    expanded = suite().model_copy(update={'cases': (*suite().cases, added)})
    class Interrupt(Runner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == 'test.tuner':
                raise ConnectionError('Interrupted after discovery, before edit')
            return await super().run(package, *args)
    options = dict(context=context(), goal='Conversions', suite=expanded, rounds=1,
        initial_training_case_count=1, training_cases_per_round=1, validation_case_count=1,
        final_max_cases=0, recovery_binding_id='fixed-offline-binding', restart_incomplete=True,
        restart_readonly_roles=('tuning', 'evaluation', 'suite_review'))
    first = Interrupt()
    journal = tmp_path / 'first.jsonl'
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=journal, **options)
    assert len(first.target_hashes) == 3  # Baseline pair and retained discovery.
    second = Runner(proposals=[{'rationale': 'Keep measured parent'}])
    result = await safe_optimizer(second).optimize(bundle(), resume_from=journal,
        journal_path=tmp_path / 'resume.jsonl', **options)
    assert second.target_hashes == []
    assert {c.case.id for c in result.report.selected.cases} == {c.id for c in expanded.cases}


def test_an_existing_failure_cannot_be_described_as_a_success_protection_case():
    from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationGrade
    failed = OptimizationCaseResult(case=suite().cases[0], observation=OptimizationObservation(state='completed'),
        grade=OptimizationGrade(score=0, passed=False, rationale='Failed retained execution'))
    with pytest.raises(ValueError, match='recorded passing'):
        validate_experiment(experiment(protection_case_ids=['train']), bundle(), [failed])


@pytest.mark.asyncio
async def test_failed_stability_cannot_relabel_new_training_as_an_old_round():
    from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationStoppingPolicy
    added = suite().cases[0].model_copy(update={'id': 'fresh-after-stability', 'input': 'New conversion'})
    expanded = suite().model_copy(update={'cases': (*suite().cases, added)})
    seen = 0
    async def grade(case, observation):
        nonlocal seen
        seen += 1
        # Baseline meets target; its next validation confirmation fails while
        # training still passes, so new training discovery is permitted.
        score = 0 if seen == 4 else 1
        return OptimizationGrade(score=score, passed=bool(score), rationale='Fixed independent measurement')
    class Script(DiagnosticRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.evaluator':
                payload = json.loads(content)
                if payload.get('response_schema', {}).get('title') == 'OptimizationDiagnosisSummary':
                    return OptimizationObservation(state='completed', output=json.dumps({
                        'summary': 'Keep measured parent', 'priorities': [],
                        'next_action': 'measure', 'next_verification': 'Collect a new independent trial'}))
            return await super().run(package, agent_id, content, ctx)
    events = []
    await optimizer(Script()).optimize(bundle(), context=context(), goal='Conversions', suite=expanded,
        rounds=1, initial_training_case_count=1, training_cases_per_round=1, validation_case_count=1,
        stopping_policy=OptimizationStoppingPolicy(stability_passes=2), authoritative_grader=grade,
        final_max_cases=0, on_event=events.append)
    measured = [e['data'] for e in events if e['event']=='target_call_started'
                and e['data']['phase']=='training_challenge']
    assert measured and all(e['round']==1 and e['case_id']==added.id for e in measured)
