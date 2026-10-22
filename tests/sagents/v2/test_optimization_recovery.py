import json

import pytest

from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationGrade, OptimizationObservation
from sagents.v2.optimization.recovery import OptimizationRecovery, OptimizationRecoveryRequired
from tests.sagents.v2.test_package_optimizer import suite


def safe_optimizer(runner):
    from tests.sagents.v2.test_package_optimizer import optimizer
    value = optimizer(runner)
    for name in ('evaluator', 'tuner', 'reviewer', 'suite_reviewer', 'test_driver', 'test_designer'):
        agent = getattr(value, name)
        data = agent.model_dump(mode='json')
        for definition in data['package']['manifest']['agents'].values():
            definition['tools'] = []
        setattr(value, name, type(agent).model_validate(data))
    return value


def journal(path, *, complete=True):
    observation = OptimizationObservation(state='completed', output='Preserved official failure')
    case = OptimizationCaseResult(case=suite().cases[0], observation=observation,
        grade=OptimizationGrade(score=0, passed=False, rationale='Completed scored failure'))
    events = [
        ('operation_started', {'goal': 'Improve', 'package': {'hash': 'fixed'}}),
        ('target_call_started', {'call_id': 'target', 'package_hash': 'package', 'case_id': 'train', 'round': 0, 'trial': 1}),
    ]
    if complete:
        events += [('target_call_completed', {'call_id': 'target', 'observation': observation.model_dump(mode='json')}),
            ('agent_call_started', {'call_id': 'eval', 'role': 'evaluation', 'round': 0, 'trial': 1, 'case_id': 'train', 'request': 'exact eval request'}),
            ('agent_call_completed', {'call_id': 'eval', 'observation': observation.model_dump(mode='json')}),
            ('case_completed', {'round': 0, 'trial': 1, 'result': case.model_dump(mode='json')})]
    path.write_text('\n'.join(json.dumps({'event': name, 'data': data}) for name, data in events))


def test_recovery_preserves_scored_failure_without_replaying_execution_or_judge(tmp_path):
    path = tmp_path / 'audit.jsonl'
    journal(path)
    index = OptimizationRecovery(path)
    index.verify({'goal': 'Improve', 'package': {'hash': 'fixed'}})
    index.require_reconciled()
    case = index.completed_case('package', phase='optimization', round=0, trial=1, case_id='train')
    assert case.grade.score == 0 and not case.grade.passed
    assert case.observation.output == 'Preserved official failure'
    assert index.completed_call(role='evaluation', phase='optimization', round=0, trial=1,
                                case_id='train', request='exact eval request') is None
    assert index.completed_case('package', phase='optimization', round=0, trial=1, case_id='train') is None


def test_pending_tool_using_internal_role_requires_explicit_host_readonly_attestation(tmp_path):
    from sagents.v2.optimization.recovery import OptimizationRecoveryRequired
    path = tmp_path / 'pending.jsonl'
    events = [
        {'event': 'operation_started', 'data': {'internal_agents': {'tuner': {'package': {
            'manifest': {'agents': {'assistant': {'tools': ['file_read']}}}}}}}},
        {'event': 'agent_call_started', 'data': {'call_id': 'pending', 'role': 'tuning',
            'round': 1, 'request': 'read local training evidence'}},
    ]
    path.write_text('\n'.join(json.dumps(e) for e in events))
    with pytest.raises(OptimizationRecoveryRequired, match='tool access'):
        OptimizationRecovery(path)
    with pytest.raises(OptimizationRecoveryRequired, match='tool access'):
        OptimizationRecovery(path, readonly_roles=('evaluation',))
    recovered = OptimizationRecovery(path, readonly_roles=('tuning',))
    recovered.require_reconciled()


@pytest.mark.asyncio
async def test_readonly_recovery_attestation_requires_frozen_binding_before_any_call():
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    runner = Runner()
    with pytest.raises(ValueError, match='frozen host binding'):
        await safe_optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
            suite=suite(), rounds=1, restart_readonly_roles=('tuning',))
    assert not runner.requests


def test_pending_effect_requires_reconciliation_and_config_changes_are_rejected(tmp_path):
    path = tmp_path / 'audit.jsonl'
    journal(path, complete=False)
    index = OptimizationRecovery(path)
    with pytest.raises(OptimizationRecoveryRequired, match='unknown outcomes'):
        index.require_reconciled()
    with pytest.raises(ValueError, match='configuration differs'):
        index.verify({'goal': 'Changed'})


def test_only_partial_tail_is_ignored_earlier_corruption_is_rejected(tmp_path):
    path = tmp_path / 'audit.jsonl'
    journal(path)
    with path.open('a') as stream:
        stream.write('\n{"event":')
    assert OptimizationRecovery(path).operation['goal'] == 'Improve'
    path.write_text(path.read_text() + '\n' + json.dumps({'event': 'more', 'data': {}}))
    with pytest.raises(ValueError, match='corrupt'):
        OptimizationRecovery(path)


@pytest.mark.asyncio
async def test_resume_retains_accepted_round_and_does_not_repeat_completed_cases(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    class InterruptedTuner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('interrupted after one accepted round')
            return await super().run(package, agent_id, content, ctx)
    first = InterruptedTuner()
    source, resumed = tmp_path / 'first.jsonl', tmp_path / 'resumed.jsonl'
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), validation_case_count=None,
                  rounds=3, final_max_cases=0, recovery_binding_id='frozen-model-route-v1')
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source, **kwargs)
    assert len(first.target_hashes) == 4
    second = Runner(proposals=[{'rationale': 'Try shorter output', 'instruction_guidance': 'guidance-2'},
                               {'rationale': 'Improve clarity', 'instruction_guidance': 'guidance-3'}])
    result = await safe_optimizer(second).optimize(bundle(), journal_path=resumed, resume_from=source, **kwargs)
    assert [item.accepted for item in result.report.rounds] == [True, False, True]
    assert len(second.target_hashes) == 4  # only two new candidate evaluations
    original = OptimizationRecovery(source)
    recovered = OptimizationRecovery(resumed)
    assert original.operation['optimization_id'] == recovered.operation['optimization_id']
    assert any(json.loads(line)['data'].get('recovered') for line in resumed.read_text().splitlines())


@pytest.mark.asyncio
async def test_resume_finishes_eval_without_reexecuting_already_completed_target(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    class InterruptedEval(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.evaluator':
                raise ConnectionError('eval interrupted after target completed')
            return await super().run(package, agent_id, content, ctx)
    source = tmp_path / 'first.jsonl'
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), validation_case_count=None,
                  rounds=1, final_max_cases=0, recovery_binding_id='binding')
    first = InterruptedEval()
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source, **kwargs)
    assert len(first.target_hashes) == 1
    second = Runner()
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'second.jsonl', resume_from=source, **kwargs)
    assert result.report.rounds[0].accepted
    assert len(second.target_hashes) == 3  # baseline validation + candidate pair


@pytest.mark.asyncio
async def test_resume_blocks_unknown_effects_unless_host_grants_disposable_restart(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    class InterruptedTarget(Runner):
        async def run(self, package, *args):
            if package.manifest.metadata.id == 'test.target':
                raise ConnectionError('outcome unknown')
            return await super().run(package, *args)
    source = tmp_path / 'first.jsonl'
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), validation_case_count=None,
                  rounds=1, final_max_cases=0, recovery_binding_id='binding')
    with pytest.raises(ConnectionError):
        await safe_optimizer(InterruptedTarget()).optimize(bundle(), journal_path=source, **kwargs)
    second = Runner()
    with pytest.raises(OptimizationRecoveryRequired):
        await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'blocked.jsonl', resume_from=source, **kwargs)
    assert not second.requests
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'allowed.jsonl', resume_from=source,
                                              restart_incomplete=True, **kwargs)
    assert result.report.rounds[0].accepted


@pytest.mark.asyncio
async def test_resume_rejects_changed_host_model_binding_before_any_invocation(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    source = tmp_path / 'first.jsonl'
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), validation_case_count=None,
                  rounds=1, final_max_cases=0)
    await safe_optimizer(Runner()).optimize(bundle(), journal_path=source, recovery_binding_id='old', **kwargs)
    second = Runner()
    with pytest.raises(ValueError, match='configuration differs'):
        await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'second.jsonl', resume_from=source,
                                          recovery_binding_id='changed', **kwargs)
    assert not second.requests


@pytest.mark.asyncio
async def test_resume_preserves_three_trial_diagnoses_contrast_and_priority_synthesis(tmp_path):
    from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner
    from tests.sagents.v2.test_package_optimizer import bundle, context
    from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
    class CutSecondProposal(DiagnosticRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('cut after diagnostics and first decision')
            return await super().run(package, agent_id, content, ctx)
    async def score(case, observation):
        value = 1 if case.split == 'validation' else float(OPTIMIZATION_TRIAL.get() == 2)
        return OptimizationGrade(score=value, passed=bool(value), rationale='Fixed host score')
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), rounds=2, validation_case_count=1,
        grow_training=False, evaluation_repeats=3, evaluation_aggregation='mean',
        authoritative_grader=score, recovery_binding_id='fixed-scored-environment')
    source = tmp_path / 'first.jsonl'
    first = CutSecondProposal()
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source, **kwargs)
    assert first.comparisons and len(first.summaries) == 2
    second = DiagnosticRunner()
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'second.jsonl',
                                                   resume_from=source, **kwargs)
    assert not second.target_hashes and not second.comparisons and not second.summaries
    case = next(case for case in result.report.baseline.cases if case.case.split == 'training')
    assert [trial.grade.score for trial in case.trials] == [0, 1, 0]
    assert all(trial.grade.diagnosis for trial in case.trials)
    assert case.contrast and len(result.report.rounds) == 2
