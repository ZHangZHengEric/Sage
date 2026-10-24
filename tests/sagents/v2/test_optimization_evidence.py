import json

import pytest

from sagents.v2.optimization.contracts import (
    OptimizationCase, OptimizationCaseResult, OptimizationCaseTrial,
    OptimizationEvaluation, OptimizationGrade, OptimizationObservation, OptimizationRound,
)
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from sagents.v2.optimization.evidence import IterationEvidenceStore, materialize_tuner_workspace, training_evidence_files
from sagents.v2.optimization.feedback import training_feedback_batch
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner
from tests.sagents.v2.test_package_optimizer import AdaptiveRunner, bundle, context, optimizer, suite


def measured(name, scores, split='training'):
    trials = tuple(OptimizationCaseTrial(observation=OptimizationObservation(
        state='completed', output=f'FULL EXECUTION {name}'),
        grade=OptimizationGrade(score=score, passed=score == 1, rationale='Recorded diagnosis'))
        for score in scores)
    return OptimizationCaseResult(case=OptimizationCase(id=name, input=f'Question {name}',
        rubric='Complete', split=split, reference_answer='EVALUATOR-ONLY'),
        observation=trials[0].observation, grade=trials[0].grade, trials=trials)


def test_training_folders_prioritize_mixed_and_failed_without_hidden_data():
    files, index = training_evidence_files([
        measured('../../unsafe', [0, 1]), measured('failure', [0, 0]),
        measured('success', [1, 1]), measured('PRIVATE-DEV', [0, 1], 'validation'),
        measured('PRIVATE-TEST', [0, 1], 'test')])
    assert index['reading_order'] == ['mixed', 'failed', 'passed']
    assert all(index['groups'][group]['count'] == 1 for group in index['reading_order'])
    assert all('..' not in path for path in files)
    all_text = '\n'.join(files.values())
    assert 'PRIVATE-DEV' not in all_text and 'PRIVATE-TEST' not in all_text
    assert 'EVALUATOR-ONLY' not in all_text
    assert 'FULL EXECUTION failure' in all_text
    mixed = json.loads(files['training-evidence/mixed/index.json'])[0]
    trial = mixed['trials'][1]
    assert json.loads(files[trial['assessment']])['score'] == 1
    assert 'FULL EXECUTION ../../unsafe' in files[trial['execution']]


def test_persistent_tuner_workspace_keeps_archives_and_rejects_escape(tmp_path):
    root = tmp_path / 'workspace'
    materialize_tuner_workspace(root, {'training-evidence/index.json': 'first'})
    archive = root / 'iterations/round-000/decision.json'
    archive.parent.mkdir(parents=True)
    archive.write_text('preserved')
    materialize_tuner_workspace(root, {'training-evidence/index.json': 'second'})
    assert (root / 'training-evidence/index.json').read_text() == 'second'
    assert archive.read_text() == 'preserved'
    assert (root / 'training-evidence/index.json').stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        materialize_tuner_workspace(root, {'../escape': 'bad'})
    (root / 'outside').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        materialize_tuner_workspace(root, {'outside/escape': 'bad'})


def test_expanding_questions_cannot_create_fake_improvement_or_hide_common_case_regressions():
    def evaluation(train, dev, extra=None):
        cases = (measured('train', [train]), measured('dev', [dev], 'validation'))
        if extra is not None:
            cases += (measured('new', [extra]),)
        return OptimizationEvaluation(package_hash='p', cases=cases)
    previous = evaluation(.5, .5)
    assert not AgentPackageOptimizer._select_adaptive(previous, evaluation(.5, .5, 1), .03)[0]
    changed = evaluation(.4, .9, 0)
    accepted, reason = AgentPackageOptimizer._select_adaptive(previous, changed, .03)
    assert accepted and '2 common cases' in reason and '1 new training cases' in reason
    assert AgentPackageOptimizer._regressions(previous, changed)[0].case_id == 'train'
    missing = OptimizationEvaluation(package_hash='p', cases=(measured('train', [.9]),))
    with pytest.raises(ValueError, match='missing or changed'):
        AgentPackageOptimizer._select_adaptive(previous, missing, .03)


def test_rejected_failures_include_full_traces_and_retained_parent_comparison_without_dev():
    retained = [measured('regressed', [1, 1]), measured('stable', [1, 1])]
    failed = OptimizationEvaluation(package_hash='rejected', cases=(
        measured('regressed', [0, 0]), measured('stable', [1, 1]),
        measured('new-training', [1, 1]), measured('PRIVATE-DEV', [0, 0], 'validation')))
    attempt = OptimizationRound(round=3, parent_hash='retained', evaluation=failed,
        accepted=False, reason='PRIVATE-DEV text must never enter the evidence folder')
    files, index = training_evidence_files(retained, attempts=[attempt])
    previous = index['rejected_attempts'][0]
    assert previous['round'] == 3 and previous['accepted'] is False
    assert previous['comparisons'][0]['case_id'] == 'regressed'
    assert previous['comparisons'][0]['retained_analysis'] in files
    assert previous['comparisons'][0]['rejected_analysis'] in files
    old_index = json.loads(files[previous['index']])
    assert old_index['groups']['failed']['count'] == 1
    assert old_index['groups']['passed']['count'] == 1  # new training case
    assert 'PRIVATE-DEV' not in '\n'.join(files.values())
    rejected = json.loads(files[previous['comparisons'][0]['rejected_analysis']])
    assert 'FULL EXECUTION regressed' in files[rejected['trials'][0]['execution']]


@pytest.mark.asyncio
async def test_file_enabled_tuner_receives_index_and_training_only_files(tmp_path):
    class FileRunner(DiagnosticRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                self.files = package.files
                self.tuning = json.loads(content)['data']
            return await super().run(package, agent_id, content, ctx)
    runner = FileRunner()
    engine = optimizer(runner)
    data = engine.tuner.model_dump(mode='json')
    data['package']['manifest']['agents'][engine.tuner.agent_id]['tools'] = ['file_read']
    engine.tuner = type(engine.tuner).model_validate(data)
    await engine.optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=1, journal_path=tmp_path / 'audit.jsonl')
    assert runner.tuning['training'] == []
    assert runner.tuning['training_evidence']['groups']['failed']['count'] == 1
    assert 'training-evidence/index.json' in runner.files
    assert 'holdout-secret' not in '\n'.join(runner.files.values())
    assert (tmp_path / 'iterations/round-001/input/training-evidence/index.json').exists()
    assert (tmp_path / 'iterations/round-000/evaluation/training-evidence/index.json').exists()
    assert (tmp_path / 'iterations/round-001/decision.json').exists()


@pytest.mark.asyncio
async def test_large_execution_files_are_staged_outside_bounded_agent_package(tmp_path):
    from sagents.v2.agent.management import AgentPackageBundle

    class LargeEvidenceRunner(DiagnosticRunner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                # The real native runner performs this validation before calling
                # its factory; a >4 MiB bundled execution would fail here.
                AgentPackageBundle.model_validate(package.model_dump(mode='json'))
                assert 'training-evidence/index.json' not in package.files
                assert (tmp_path / 'workspace/training-evidence/index.json').exists()
            result = await super().run(package, agent_id, content, ctx)
            if package.manifest.metadata.id == bundle().manifest.metadata.id:
                result = result.model_copy(update={'evidence': {'final_items': [{'data': {
                    'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'x' * 4300000}]}}]}})
            return result
    runner = LargeEvidenceRunner()
    engine = optimizer(runner)
    data = engine.tuner.model_dump(mode='json')
    data['package']['manifest']['agents'][engine.tuner.agent_id]['tools'] = ['file_read']
    engine.tuner = type(engine.tuner).model_validate(data)
    await engine.optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=1,
        tuner_workspace=tmp_path / 'workspace', evidence_directory=tmp_path / 'workspace/iterations')
    records = list((tmp_path / 'workspace/training-evidence').rglob('execution-*.json'))
    assert records and records[0].stat().st_size > 4 * 1024 * 1024
    assert (tmp_path / 'workspace/iterations/round-000/evaluation.json').exists()


def test_iteration_storage_separates_rounds_and_hides_private_material(tmp_path):
    store = IterationEvidenceStore(tmp_path)
    for number, score in enumerate((0, 1)):
        evaluation = OptimizationEvaluation(package_hash=f'p{number}', cases=(
            measured('train', [score]), measured('PRIVATE-DEV', [1], 'validation'),
            measured('PRIVATE-TEST', [0], 'test')))
        store.observe({'event': 'evaluation_completed', 'data': {
            'round': number, 'evaluation': evaluation.model_dump(mode='json')}})
    first = tmp_path / 'round-000/evaluation/training-evidence/failed/index.json'
    second = tmp_path / 'round-001/evaluation/training-evidence/passed/index.json'
    assert json.loads(first.read_text())[0]['scores'] == [0]
    assert json.loads(second.read_text())[0]['scores'] == [1]
    contents = '\n'.join(p.read_text() for p in tmp_path.rglob('*') if p.is_file())
    assert all(secret not in contents for secret in ('PRIVATE-DEV', 'PRIVATE-TEST', 'EVALUATOR-ONLY'))
    assert json.loads((tmp_path / 'round-001/validation-scores.json').read_text()) == [
        {'slot': 1, 'score': 1, 'trials': [1]}]
    assert first.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        store.write(1, '../escape', 'bad')


def test_rich_repeated_diagnoses_fit_history_budget_without_losing_scores():
    from sagents.v2.optimization.contracts import OptimizationDiagnosis

    diagnosis = OptimizationDiagnosis(summary='Detailed analysis', findings=tuple({
        'category': 'procedure', 'cause': 'cause ' * 300,
        'recommendation': 'recommendation ' * 100, 'evidence_indexes': tuple(range(12)),
        'scope': 'skills', 'confidence': 'confirmed'} for _ in range(8)),
        strengths=('strength ' * 100,) * 4, coverage='Full recorded trajectory')
    results = []
    for number in range(16):
        result = measured(f'case-{number}', [0, 1, 0])
        trials = tuple(t.model_copy(update={'grade': t.grade.model_copy(update={
            'diagnosis': diagnosis, 'rationale': 'Long diagnostic evidence ' * 500})})
            for t in result.trials)
        results.append(result.model_copy(update={'trials': trials, 'grade': trials[0].grade}))
    originals = [r.model_dump(mode='json') for r in results]
    view = training_feedback_batch(results, max_chars=12000)
    assert len(json.dumps(view, ensure_ascii=False)) <= 12000
    assert [v['case']['id'] for v in view] == [r.case.id for r in results]
    assert all([t['grade']['score'] for t in v['trials']] == [0, 1, 0] for v in view)
    assert all('reference_answer' not in v['case'] for v in view)
    assert [r.model_dump(mode='json') for r in results] == originals
    review = training_feedback_batch([measured('review', [0])], include_reference_answer=True)
    assert review[0]['case']['reference_answer'] == 'EVALUATOR-ONLY'


@pytest.mark.asyncio
async def test_new_questions_are_measured_by_retained_before_candidates():
    events = []
    result = await optimizer(AdaptiveRunner()).optimize(bundle(), context=context(),
        goal='Conversions', rounds=2, validation_case_count=2, on_event=events.append)
    started = [e['data'] for e in events if e['event'] == 'target_call_started']
    assert any(e['phase'] == 'training_challenge' for e in started)
    added = {c.id for addition in result.report.training_additions if addition.round > 0 for c in addition.cases}
    challenges = [e for e in started if e['phase'] == 'training_challenge']
    assert {e['case_id'] for e in challenges} == added
    parents = {r.round: r.parent_hash for r in result.report.rounds}
    assert all(e['package_hash'] == parents[e['round']] for e in challenges)
    for record in result.report.rounds:
        expected = {c.case.id for c in record.evaluation.cases}
        actual = {e['case_id'] for e in started if e['round'] == record.round
                  and e['phase'] == 'optimization' and e['package_hash'] == record.candidate_package.content_hash}
        assert expected == actual
