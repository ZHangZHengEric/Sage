"""Paired trials, judge order, durable recovery and actual optimizer selection."""
import asyncio
import json

import pytest

from sagents.v2.optimization.builtin_scoring import BuiltinScoring
from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.pairwise import PairwiseEvaluator, PairwiseMeasurementError, comparison_summary
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


def artifact(text):
    return OptimizationObservation(state='completed', output=text,
        evidence={'package_hash': 'PRIVATE-VERSION', 'path': '/private/artifact'}, elapsed_seconds=9)


def comparison_evaluations():
    from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationCaseTrial, OptimizationEvaluation, OptimizationGrade
    cases = (*suite().cases, *(c.model_copy(update={'id':c.id+'-2'}) for c in suite().cases))
    def evaluation(prefix):
        values = []
        for case in cases:
            trials = tuple(OptimizationCaseTrial(observation=artifact('site'), grade=OptimizationGrade(
                score=.5, passed=True, rationale='Frozen artifact',
                scorer_details={'pairwise':{'artifact_key':f'{prefix}:{case.id}:{i}'}})) for i in (1, 2))
            values.append(OptimizationCaseResult(case=case, observation=trials[0].observation,
                grade=trials[0].grade, trials=trials))
        return OptimizationEvaluation(package_hash=prefix, cases=tuple(values))
    return evaluation('old'), evaluation('new')


@pytest.mark.asyncio
async def test_case_comparisons_are_bounded_concurrent_and_preserve_trial_pairing_and_order():
    from sagents.v2.optimization.contracts import OptimizationGrade
    from sagents.v2.optimization.pairwise import compare_evaluations
    previous, candidate = comparison_evaluations()
    active = peak = 0
    seen = {}
    class Engine:
        async def compare_prepared(self, case, *, trial, reference_key, candidate_key):
            nonlocal active, peak
            assert reference_key == f'old:{case.id}:{trial}'
            assert candidate_key == f'new:{case.id}:{trial}'
            seen.setdefault(case.id, []).append(trial)
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return OptimizationGrade(score=1 if trial == 1 else 0, passed=trial == 1,
                rationale='Paired result', scorer_details={'pairwise':{'outcome':'win' if trial == 1 else 'loss'}})
    summary, result = await compare_evaluations(Engine(), previous, candidate, max_concurrency=2)
    assert peak == 2 and active == 0
    assert [c.case.id for c in result.cases] == [c.case.id for c in candidate.cases]
    assert all(v == [1, 2] for v in seen.values())
    assert summary['splits']['validation']['pairs'] == 4
    assert summary['splits']['validation']['preference_score'] == .5


@pytest.mark.asyncio
async def test_comparison_failure_drains_started_siblings_and_stops_queued_dispatch():
    from sagents.v2.optimization.contracts import OptimizationGrade
    from sagents.v2.optimization.pairwise import compare_evaluations
    previous, candidate = comparison_evaluations()
    started, completed = [], []
    class Engine:
        async def compare_prepared(self, case, **kwargs):
            started.append(case.id)
            await asyncio.sleep(0)
            if case.id == candidate.cases[0].case.id:
                raise PairwiseMeasurementError('Missing measurement')
            completed.append(case.id)
            return OptimizationGrade(score=.5, passed=True, rationale='Tie')
    with pytest.raises(PairwiseMeasurementError) as caught:
        await compare_evaluations(Engine(), previous, candidate, max_concurrency=2)
    assert caught.value.rsi_siblings_drained
    assert set(started) == {c.case.id for c in candidate.cases[:2]}
    assert completed == [candidate.cases[1].case.id] * 2


@pytest.mark.asyncio
async def test_repeats_pair_by_index_and_count_swapped_orders_as_one_pair(tmp_path):
    seen = []
    async def judge(payload, case):
        seen.append(payload)
        assert set(payload) == {'input', 'rubric', 'reference_answer', 'A', 'B'}
        assert 'PRIVATE-VERSION' not in json.dumps(payload)
        assert '/private/artifact' not in json.dumps(payload)
        a, b = int(payload['A']), int(payload['B'])
        return {'winner': 'tie' if a == b else 'A' if a > b else 'B', 'rationale': 'Larger result'}
    evaluator = PairwiseEvaluator(binding='run', directory=tmp_path, judge=judge)
    case = suite().cases[0]
    grades = []
    for index, (base, candidate) in enumerate([(1, 2), (8, 7), (4, 4)], 1):
        neutral = await evaluator.grade(case, artifact(str(base)), trial=index, is_reference=True)
        assert neutral.score == .5
        grades.append(await evaluator.grade(case, artifact(str(candidate)), trial=index))
    summary = comparison_summary(grades)
    assert (summary['wins'], summary['ties'], summary['losses'], summary['pairs']) == (1, 1, 1, 3)
    assert summary['preference_score'] == .5
    assert len(seen) == 6  # Not 3 x 3 comparisons or 6 independent samples.
    for i in range(0, len(seen), 2):
        assert seen[i]['A'] == seen[i + 1]['B'] and seen[i]['B'] == seen[i + 1]['A']
    # Recovery reuses artifacts and decisions without model calls.
    restored = PairwiseEvaluator(binding='run', directory=tmp_path, judge=judge)
    assert (await restored.grade(case, artifact('2'), trial=1)).score == 1
    assert len(seen) == 6


@pytest.mark.asyncio
async def test_position_bias_is_a_tie_and_interrupted_second_judgment_resumes(tmp_path):
    calls = 0
    async def interrupted(payload, case):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError('judge unavailable')
        return {'winner': 'A', 'rationale': 'Position preference'}
    engine = PairwiseEvaluator(binding='run', directory=tmp_path, judge=interrupted)
    case = suite().cases[0]
    await engine.grade(case, artifact('base'), trial=1, is_reference=True)
    with pytest.raises(TimeoutError):
        await engine.grade(case, artifact('candidate'), trial=1)
    restored = PairwiseEvaluator(binding='run', directory=tmp_path, judge=interrupted)
    grade = await restored.grade(case, artifact('candidate'), trial=1)
    assert calls == 3 and grade.score == .5
    assert grade.scorer_details['pairwise']['order_disagreement']
    assert comparison_summary([grade])['ties'] == 1


@pytest.mark.asyncio
async def test_missing_or_changed_reference_and_incomplete_outputs_are_errors(tmp_path):
    async def judge(*args):
        pytest.fail('Invalid measurements must not call judge')
    engine = PairwiseEvaluator(binding='run', directory=tmp_path, judge=judge)
    case = suite().cases[0]
    with pytest.raises(PairwiseMeasurementError, match='Missing'):
        await engine.grade(case, artifact('candidate'), trial=1)
    await engine.grade(case, artifact('base'), trial=1, is_reference=True)
    with pytest.raises(PairwiseMeasurementError, match='reference changed'):
        await engine.grade(case, artifact('different'), trial=1, is_reference=True)
    for observation in [OptimizationObservation(state='failed')]:
        with pytest.raises(PairwiseMeasurementError):
            await engine.grade(case, observation, trial=1)
    with pytest.raises(PairwiseMeasurementError, match='single-turn'):
        await engine.grade(case.model_copy(update={'mode': 'dialogue'}), artifact('text'), trial=1)
    assert (await engine.grade(case, artifact(''), trial=1)).score == 0
    isolated = PairwiseEvaluator(binding='another-run', directory=tmp_path, judge=judge)
    assert isolated.reference(case, 1) is None


class FixtureComparisonPlugin:
    from sagents.v2.optimization.scoring import ScorerDescriptor
    descriptor = ScorerDescriptor(id='comparison', name='Fixture comparison', version='1')

    def __init__(self, runner):
        self.runner = runner

    async def prepare(self, request):
        from sagents.v2.optimization.comparison_plugin import PreparedComparisonArtifact
        return PreparedComparisonArtifact(artifact={'text': request.observation.output})

    async def compare(self, request):
        self.runner.comparisons.append({'A': request.A.artifact['text'], 'B': request.B.artifact['text']})
        scores = {'base': 0, 'guidance-1': 2, 'guidance-2': 1, 'guidance-3': 3}
        a, b = scores[request.A.artifact['text']], scores[request.B.artifact['text']]
        return {'winner': 'tie' if a == b else 'A' if a > b else 'B', 'rationale': 'Clearer work'}


class ComparisonRunner(Runner):
    def __init__(self):
        super().__init__()
        self.comparisons = []
        self.target_hashes = []

    async def run(self, package, agent_id, content, ctx):
        if package.manifest.metadata.id == 'test.evaluator':
            data = json.loads(content)
            if data['response_schema'].get('title') == 'PairwiseDecision':
                payload = data['data']
                self.comparisons.append(payload)
                scores = {'base': 0, 'guidance-1': 2, 'guidance-2': 1, 'guidance-3': 3}
                a, b = scores[payload['A']], scores[payload['B']]
                return artifact(json.dumps({'winner': 'tie' if a == b else 'A' if a > b else 'B',
                    'rationale': 'Clearer work'}))
        return await super().run(package, agent_id, content, ctx)


@pytest.mark.asyncio
async def test_optimizer_uses_only_direct_incumbent_pairs_with_repeats(tmp_path):
    runner = ComparisonRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Clarity', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=2, evaluation_repeats=3,
        builtin_scoring=BuiltinScoring(mode='pairwise'), comparison_plugin=FixtureComparisonPlugin(runner),
        journal_path=tmp_path/'journal.jsonl')
    assert result.report.evaluation_aggregation == 'mean'
    assert result.report.baseline.mean_score('validation') == .5
    assert result.report.selected.mean_score('validation') == 1
    assert result.report.rounds[0].accepted
    assert not result.report.rounds[1].accepted  # Second candidate loses to the retained incumbent.
    assert result.report.stopping_policy is None and result.report.goal_verified is None
    assert result.report.improved is None
    assert all(r.overall_before is None and r.overall_after is None for r in result.report.rounds)
    assert not any({p['A'], p['B']} == {'base', 'guidance-2'} for p in runner.comparisons)
    assert len(runner.comparisons) == 2 * 2 * 3 * 2
    assert any('base' not in [p['A'], p['B']] for p in runner.comparisons)
    assert result.report.rounds[1].comparison['splits']['validation']['losses'] == 3
    assert runner.target_hashes.count(bundle().content_hash) == 6
    for case in result.report.selected.cases:
        assert len(case.trials) == 3
        assert case.grade.scorer_details['pairwise_summary']['pairs'] == 3


@pytest.mark.asyncio
async def test_pairwise_rejects_external_absolute_scorer_before_any_execution():
    with pytest.raises(ValueError, match='absolute scorer'):
        await optimizer(ComparisonRunner()).optimize(bundle(), context=context(), goal='Clarity', suite=suite(),
            builtin_scoring=BuiltinScoring(mode='pairwise'), scorer=object())


@pytest.mark.asyncio
async def test_pairwise_resume_reuses_completed_executions_and_decisions(tmp_path):
    from tests.sagents.v2.test_optimization_recovery import safe_optimizer
    class Interrupted(ComparisonRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('cut after paired round')
            return await super().run(package, agent_id, content, ctx)
    first = Interrupted()
    source = tmp_path/'first.jsonl'
    options = dict(context=context(), goal='Clarity', suite=suite(), validation_case_count=1,
        grow_training=False, rounds=2, evaluation_repeats=2, builtin_scoring=BuiltinScoring(mode='pairwise'),
        recovery_binding_id='frozen-model')
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source,
            comparison_plugin=FixtureComparisonPlugin(first), **options)
    second = ComparisonRunner()
    second.proposals = [{'rationale': 'Try another design', 'instruction_guidance': 'guidance-2'}]
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'resumed.jsonl', resume_from=source,
        comparison_plugin=FixtureComparisonPlugin(second), **options)
    assert result.report.rounds[0].accepted
    assert len(second.target_hashes) == 4  # Two cases x two repeats, only the new candidate.
    assert bundle().content_hash not in second.target_hashes
    assert len(second.comparisons) == 8  # Only incumbent comparisons for the new candidate.


@pytest.mark.asyncio
async def test_growing_training_reference_executions_are_reconciled_on_resume(tmp_path):
    from tests.sagents.v2.test_package_optimizer import AdaptiveRunner
    from tests.sagents.v2.test_optimization_recovery import safe_optimizer
    class Growing(AdaptiveRunner, ComparisonRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('cut after growing training')
            return await super().run(package, agent_id, content, ctx)
    runner = Growing()
    source = tmp_path/'first.jsonl'
    options = dict(context=context(), goal='Clarity', suite=suite(), validation_case_count=1,
        grow_training=True, training_cases_per_round=1, rounds=2,
        builtin_scoring=BuiltinScoring(mode='pairwise'), recovery_binding_id='fixed-model')
    with pytest.raises(ConnectionError):
        await safe_optimizer(runner).optimize(bundle(), journal_path=source,
            comparison_plugin=FixtureComparisonPlugin(runner), **options)
    class Resumed(AdaptiveRunner, ComparisonRunner):
        pass
    resumed = Resumed()
    result = await safe_optimizer(resumed).optimize(bundle(), journal_path=tmp_path/'resumed.jsonl', resume_from=source,
        comparison_plugin=FixtureComparisonPlugin(resumed), **options)
    assert result.report.rounds[0].accepted
    assert result.report.training_additions


@pytest.mark.asyncio
async def test_later_candidate_can_improve_incumbent_after_original_reference_is_saturated(tmp_path):
    runner = ComparisonRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Clarity', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=3, builtin_scoring=BuiltinScoring(mode='pairwise'),
        comparison_plugin=FixtureComparisonPlugin(runner), journal_path=tmp_path/'audit.jsonl')
    assert [r.accepted for r in result.report.rounds] == [True, False, True]
    assert [r.evaluation.mean_score('validation') for r in result.report.rounds] == [1, 0, 1]
    assert result.report.rounds[-1].comparison['splits']['validation']['wins'] == 1


@pytest.mark.asyncio
async def test_nontransitive_preferences_do_not_infer_or_review_unrequested_pairs(tmp_path):
    class CyclicPlugin(FixtureComparisonPlugin):
        async def compare(self, request):
            a, b = request.A.artifact['text'], request.B.artifact['text']
            self.runner.comparisons.append({'A': a, 'B': b})
            wins = {('guidance-1', 'base'), ('guidance-2', 'guidance-1'), ('base', 'guidance-2')}
            return {'winner': 'tie' if a == b else 'A' if (a, b) in wins else 'B', 'rationale': 'Cyclic preference'}
    runner = ComparisonRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Preference', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=2, builtin_scoring=BuiltinScoring(mode='pairwise'),
        comparison_plugin=CyclicPlugin(runner), journal_path=tmp_path/'audit.jsonl')
    assert [r.accepted for r in result.report.rounds] == [True, True]
    assert len(runner.comparisons) == 8  # Two cases, two rounds, two orders; no extra original-reference reviews.
    assert not any({p['A'], p['B']} == {'base', 'guidance-2'} for p in runner.comparisons)
    assert result.report.improved is None and result.report.goal_verified is None
    assert result.report.selected.comparison_reference_hash == result.report.rounds[0].candidate_package.content_hash


def failed_target():
    return OptimizationObservation(state='suspended', evidence={'error': {
        'code': 'model.tool_arguments_invalid_json', 'metadata': {
            'side_effect_state': 'not_applied', 'tool_execution_started': False}}})


@pytest.mark.asyncio
async def test_target_failures_freeze_compare_and_recover_without_plugin_or_judge(tmp_path):
    async def judge(*args):
        pytest.fail('Execution failures do not need aesthetic judgments')
    engine = PairwiseEvaluator(binding='failures', directory=tmp_path, judge=judge)
    case = suite().cases[0]
    for base, candidate, outcome, score in [
        (artifact('ok'), failed_target(), 'loss', 0),
        (failed_target(), artifact('ok'), 'win', 1),
        (failed_target(), failed_target(), 'both_failed', 0),
    ]:
        trial = {'loss': 1, 'win': 2, 'both_failed': 3}[outcome]
        await engine.grade(case, base, trial=trial, is_reference=True)
        grade = await engine.grade(case, candidate, trial=trial)
        assert grade.score == score
        assert grade.scorer_details['pairwise']['outcome'] == outcome
        restored = PairwiseEvaluator(binding='failures', directory=tmp_path, judge=judge)
        assert await restored.grade(case, candidate, trial=trial) == grade
    summary = comparison_summary([grade])
    assert summary['both_failed'] == 1 and summary['ties'] == 0
    assert summary['pairs'] == 1 and summary['preference_score'] == 0


@pytest.mark.asyncio
async def test_unknown_or_uncertain_failure_is_not_a_target_loss():
    engine = PairwiseEvaluator(binding='missing')
    for state, evidence in [('failed', {}), ('suspended', {'error': {'code': 'model.transport_error'}}),
            ('suspended', {'error': {'code': 'model.tool_arguments_invalid_json',
                'metadata': {'side_effect_state': 'unknown', 'tool_execution_started': True}}})]:
        with pytest.raises(PairwiseMeasurementError):
            await engine.capture(suite().cases[0], OptimizationObservation(state=state, evidence=evidence),
                trial=1, execution_id='fixture')


@pytest.mark.asyncio
async def test_optimizer_continues_other_cases_and_next_round_after_target_failure(tmp_path):
    class Failing(ComparisonRunner):
        async def run(self, package, agent_id, content, ctx):
            result = await super().run(package, agent_id, content, ctx)
            if result.output == 'guidance-1':
                return failed_target()
            return result
    runner = Failing()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Clarity', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=2, evaluation_repeats=2,
        builtin_scoring=BuiltinScoring(mode='pairwise'), comparison_plugin=FixtureComparisonPlugin(runner),
        journal_path=tmp_path/'audit.jsonl')
    assert len(result.report.rounds) == 2
    assert not result.report.rounds[0].accepted
    assert result.report.rounds[0].comparison['splits']['validation']['losses'] == 2
    assert result.report.rounds[1].accepted


@pytest.mark.asyncio
async def test_dataset_declared_invalid_submission_bypasses_judge_but_preserves_integrity(tmp_path):
    from sagents.v2.optimization.comparison_plugin import PreparedComparisonArtifact, FrozenComparisonFile
    import hashlib
    evidence = tmp_path/'proof.txt'
    evidence.write_text('no entry page')
    class Plugin:
        async def prepare(self, request):
            # The artifact directory is mandatory for plugin-owned evidence.
            directory = __import__('pathlib').Path(request.artifact_directory)
            proof = directory/'proof.txt'
            proof.write_bytes(evidence.read_bytes())
            return PreparedComparisonArtifact(artifact={'status': 'invalid'},
                execution_failure='missing_entry', files=(FrozenComparisonFile(path=str(proof),
                    sha256=hashlib.sha256(proof.read_bytes()).hexdigest(), size_bytes=proof.stat().st_size,
                    media_type='text/plain'),))
        async def compare(self, request):
            pytest.fail('Invalid submissions must not be aesthetic ties')
    engine = PairwiseEvaluator(binding='invalid-file', plugin=Plugin(), directory=tmp_path/'receipts')
    case = suite().cases[0]
    baseline = await engine.grade(case, artifact('done'), trial=1, is_reference=True)
    assert baseline.score == 0 and not baseline.passed
    grade = await engine.grade(case, artifact('done again'), trial=1)
    assert grade.scorer_details['pairwise']['outcome'] == 'both_failed'
    next((tmp_path/'receipts'/'artifacts').glob('*/proof.txt')).write_text('changed')
    with pytest.raises(PairwiseMeasurementError, match='missing or changed'):
        await engine.grade(case, artifact('done again'), trial=1)


@pytest.mark.asyncio
async def test_evaluation_validation_upgrade_preserves_completed_targets_and_judgments(tmp_path, monkeypatch):
    from tests.sagents.v2.test_optimization_recovery import safe_optimizer
    import importlib
    module = importlib.import_module('sagents.v2.optimization.optimizer')
    monkeypatch.setattr(module, 'engine_fingerprint', lambda: 'a' * 64)
    class Interrupted(ComparisonRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('stop before next round')
            return await super().run(package, agent_id, content, ctx)
    first = Interrupted()
    source = tmp_path/'first.jsonl'
    options = dict(context=context(), goal='Clarity', suite=suite(), validation_case_count=1,
        grow_training=False, rounds=2, evaluation_repeats=2, builtin_scoring=BuiltinScoring(mode='pairwise'),
        recovery_binding_id='frozen-model')
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source,
            comparison_plugin=FixtureComparisonPlugin(first), **options)
    monkeypatch.setattr(module, 'engine_fingerprint', lambda: 'b' * 64)
    resumed = ComparisonRunner()
    resumed.proposals = [{'rationale': 'Try another design', 'instruction_guidance': 'guidance-2'}]
    result = await safe_optimizer(resumed).optimize(bundle(), journal_path=tmp_path/'resume.jsonl',
        resume_from=source, allow_evaluation_validation_upgrade=True,
        comparison_plugin=FixtureComparisonPlugin(resumed), **options)
    assert result.report.rounds[0].accepted
    assert len(resumed.target_hashes) == 4
    assert bundle().content_hash not in resumed.target_hashes
    assert len(resumed.comparisons) == 8
