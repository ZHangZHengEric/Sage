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


@pytest.mark.parametrize('code,category,retryable,expected', [
    ('model.stream_incomplete', 'provider_transient', True, True),
    ('model.provider_transient', 'provider_transient', True, True),
    ('model.context_window_exceeded', 'validation', True, False),
    ('tool.provider_error', 'provider_transient', True, False),
    ('model.provider_permanent', 'provider_permanent', False, False),
])
def test_suspended_transport_recovery_is_typed_and_excludes_other_failures(code, category, retryable, expected):
    from sagents.v2.optimization.recovery import model_transport_interrupted
    observation = OptimizationObservation(state='suspended', evidence={'runtime_events': [
        {'type': 'interaction.requested', 'data': {'payload': {'error': {
            'code': code, 'category': category, 'retryable': retryable}}}}]})
    assert model_transport_interrupted(observation) is expected


@pytest.mark.parametrize('tools,allowed', [(['file_read', 'file_write'], True),
    (['file_read', 'execute_shell_command'], False)])
def test_private_file_evaluator_recovery_requires_explicit_bounded_grant(tmp_path, tools, allowed):
    events = [
        {'event': 'operation_started', 'data': {'internal_agents': {'evaluator': {'package': {
            'manifest': {'agents': {'assistant': {'tools': tools}}}}}}}},
        {'event': 'agent_call_started', 'data': {'call_id': 'pending', 'role': 'evaluation',
            'request': 'Read inputs and write private assessment'}},
    ]
    path = tmp_path / 'audit.jsonl'
    path.write_text('\n'.join(json.dumps(event) for event in events))
    with pytest.raises(OptimizationRecoveryRequired):
        OptimizationRecovery(path)
    if allowed:
        OptimizationRecovery(path, local_file_evaluator=True).require_reconciled()
    else:
        with pytest.raises(OptimizationRecoveryRequired):
            OptimizationRecovery(path, local_file_evaluator=True)


@pytest.mark.asyncio
async def test_completed_dialogue_recovers_after_diagnosis_failure_without_target_or_score_replay(tmp_path):
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner, Scorer
    from tests.sagents.v2.test_package_optimizer import bundle, context
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    class CountedRunner(DialogueRunner):
        def __init__(self, fail=False):
            super().__init__()
            self.sent, self.fail = 0, fail
        @asynccontextmanager
        async def conversation(self, *args):
            count = 0
            async def send(content):
                nonlocal count
                self.sent += 1
                count += 1
                return OptimizationObservation(state='completed', output=f'target-turn-{count}')
            yield SimpleNamespace(send=send)
        async def run(self, package, agent_id, content, ctx):
            if self.fail and json.loads(content).get('response_schema', {}).get('title') == 'OptimizationDiagnosis':
                raise ConnectionError('diagnosis interrupted after complete execution and score')
            return await super().run(package, agent_id, content, ctx)

    cases = suite().model_copy(update={'cases': tuple(case.model_copy(update={
        'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 3}) for case in suite().cases)})
    first, later = CountedRunner(fail=True), CountedRunner()
    first_scorer, later_scorer = Scorer(), Scorer()
    source, resumed = tmp_path / 'first.jsonl', tmp_path / 'resumed.jsonl'
    options = dict(context=context(), goal='Accuracy', suite=cases, rounds=1,
        validation_case_count=1, grow_training=False, max_concurrency=1, recovery_binding_id='fixed')
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), **options, scorer=first_scorer, journal_path=source)
    assert first.sent == 3 and len(first_scorer.histories) == 1
    interrupted_again, middle_scorer = CountedRunner(fail=True), Scorer()
    middle = tmp_path / 'middle.jsonl'
    with pytest.raises(ConnectionError):
        await safe_optimizer(interrupted_again).optimize(bundle(), **options, scorer=middle_scorer,
            journal_path=middle, resume_from=source)
    assert interrupted_again.sent == 0 and not middle_scorer.histories
    result = await safe_optimizer(later).optimize(bundle(), **options, scorer=later_scorer,
        journal_path=resumed, resume_from=middle)
    assert later.sent == 3  # only the remaining baseline case; fixture proposes no edit
    assert len(later_scorer.histories) == 1  # the completed first score is immutable
    assert result.report.rounds[0].evaluation_reused
    restored = [json.loads(line) for line in resumed.read_text().splitlines()]
    assert sum(e['event'] == 'target_call_completed' and e['data'].get('recovered', False) for e in restored) == 3
    assert len(result.report.baseline.cases[0].dialogue) == 3
    assert result.report.baseline.cases[0].grade.score == pytest.approx(.6)


def test_rejected_evaluation_response_is_not_reused_as_a_completed_decision(tmp_path):
    observation = OptimizationObservation(state='completed', output='invalid JSON')
    events = [
        {'event': 'operation_started', 'data': {}},
        {'event': 'agent_call_started', 'data': {'call_id': 'bad', 'role': 'evaluation', 'request': 'assess'}},
        {'event': 'agent_call_completed', 'data': {'call_id': 'bad', 'observation': observation.model_dump(mode='json')}},
        {'event': 'evaluation_response_rejected', 'data': {'call_id': 'bad'}},
    ]
    path = tmp_path / 'audit.jsonl'
    path.write_text('\n'.join(json.dumps(e) for e in events))
    recovered = OptimizationRecovery(path)
    assert recovered.completed_call(role='evaluation', phase='optimization', round=0,
        trial=1, case_id=None, request='assess') is None
    recovered.assert_consumed()


@pytest.mark.asyncio
async def test_final_scorer_transport_failure_reuses_the_complete_unscored_dialogue(tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from sagents.v2.optimization.recovery import OptimizationTransientFailure
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner, Scorer
    from tests.sagents.v2.test_package_optimizer import bundle, context
    class CountedRunner(DialogueRunner):
        sent = 0
        @asynccontextmanager
        async def conversation(self, *args):
            async with super().conversation(*args) as session:
                async def send(content):
                    self.sent += 1
                    return await session.send(content)
                yield SimpleNamespace(send=send)
    class InterruptedScorer(Scorer):
        async def score(self, request):
            raise OptimizationTransientFailure('model transport interrupted during final scoring')
    first, later = CountedRunner(), CountedRunner()
    cases = suite().model_copy(update={'cases': tuple(case.model_copy(update={
        'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 3}) for case in suite().cases)})
    source = tmp_path / 'unscored.jsonl'
    options = dict(context=context(), goal='Accuracy', suite=cases, rounds=1,
        validation_case_count=1, grow_training=False, max_concurrency=1, recovery_binding_id='fixed')
    with pytest.raises(OptimizationTransientFailure):
        await safe_optimizer(first).optimize(bundle(), **options, scorer=InterruptedScorer(), journal_path=source)
    assert first.sent == 3
    scorer = Scorer()
    result = await safe_optimizer(later).optimize(bundle(), **options, scorer=scorer,
        resume_from=source, journal_path=tmp_path / 'resumed.jsonl')
    assert later.sent == 3 and len(scorer.histories) == 2
    assert all(case.grade.score == pytest.approx(.6) for case in result.report.baseline.cases)


@pytest.mark.asyncio
async def test_internal_evaluation_grade_is_restored_on_final_dialogue_turn(tmp_path):
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner
    from tests.sagents.v2.test_package_optimizer import bundle, context
    first, later = DialogueRunner(), DialogueRunner()
    first.scores['target-turn-3'] = later.scores['target-turn-3'] = .6
    source = tmp_path / 'scored.jsonl'
    cases = suite().model_copy(update={'cases': tuple(case.model_copy(update={
        'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 3}) for case in suite().cases)})
    def interrupt(event):
        if event['event'] == 'dialogue_execution_scored':
            raise ConnectionError('storage callback interrupted after score checkpoint')
    options = dict(context=context(), goal='Accuracy', suite=cases, rounds=1,
        validation_case_count=1, grow_training=False, max_concurrency=1, recovery_binding_id='fixed')
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), **options,
            journal_path=source, on_event=interrupt)
    result = await safe_optimizer(later).optimize(bundle(), **options,
        resume_from=source, journal_path=tmp_path / 'resumed.jsonl')
    restored = result.report.baseline.cases[0]
    assert restored.dialogue[-1].grade == restored.grade
    assert all(turn.grade is None for turn in restored.dialogue[:-1])


@pytest.mark.asyncio
async def test_disposable_partial_dialogue_restart_discards_stale_user_decisions(tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as DialogueRunner, Scorer
    from tests.sagents.v2.test_package_optimizer import bundle, context
    class ChangingConversation(DialogueRunner):
        def __init__(self, version, fail=False):
            super().__init__()
            self.version, self.fail, self.sent, self.driver_requests = version, fail, 0, []
        @asynccontextmanager
        async def conversation(self, *args):
            turn = 0
            async def send(content):
                nonlocal turn
                turn += 1
                self.sent += 1
                if self.fail and turn == 2:
                    raise ConnectionError('Incomplete isolated conversation')
                return OptimizationObservation(state='completed', output=f'{self.version}-target-turn-{turn}')
            yield SimpleNamespace(send=send)
        async def run(self, package, agent_id, content, ctx):
            payload = json.loads(content)
            if payload.get('response_schema', {}).get('title') == 'OptimizationDialogueReply':
                self.driver_requests.append(content)
            return await super().run(package, agent_id, content, ctx)
    cases = suite().model_copy(update={'cases': tuple(case.model_copy(update={
        'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 2}) for case in suite().cases)})
    options = dict(context=context(), goal='Accuracy', suite=cases, rounds=1,
        validation_case_count=1, grow_training=False, max_concurrency=1, recovery_binding_id='fixed')
    source, resumed = tmp_path/'source.jsonl', tmp_path/'resumed.jsonl'
    original, restored = ChangingConversation('before', True), ChangingConversation('after')
    with pytest.raises(ConnectionError):
        await safe_optimizer(original).optimize(bundle(), **options, scorer=Scorer(), journal_path=source)
    with pytest.raises(OptimizationRecoveryRequired, match='unknown outcomes'):
        await safe_optimizer(restored).optimize(bundle(), **options, scorer=Scorer(),
            journal_path=resumed, resume_from=source)
    result = await safe_optimizer(restored).optimize(bundle(), **options, scorer=Scorer(),
        journal_path=resumed, resume_from=source, restart_incomplete=True)
    assert result.report.baseline.cases
    assert restored.sent == 4
    assert restored.driver_requests and all('after-target-turn-1' in text for text in restored.driver_requests)
    assert all('before-target-turn' not in text for text in restored.driver_requests)
    events = [json.loads(line) for line in resumed.read_text().splitlines()]
    restart = next(e for e in events if e['event'] == 'partial_dialogue_restarted')
    assert restart['data']['discarded_decisions'] == 1
