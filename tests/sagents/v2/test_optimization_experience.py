import json

import pytest

from sagents.v2.optimization.contracts import OptimizationPatch, OptimizationRound, OptimizationStoppingPolicy, OptimizationObservation
from sagents.v2.optimization.experience import experience_document
from tests.sagents.v2.test_optimization_evidence import measured
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


def test_experience_distinguishes_hypothesis_from_acceptance_and_excludes_hidden_evidence():
    from sagents.v2.optimization.contracts import OptimizationEvaluation
    record = OptimizationRound(round=1, parent_hash='parent', accepted=False,
        reason='PRIVATE rejection details',
        patch=OptimizationPatch(rationale='Try parameterized units', experience_notes='Check unit preconditions'),
        evaluation=OptimizationEvaluation(package_hash='candidate', cases=(
            measured('train', [0]), measured('HIDDEN-DEV', [1], 'validation'), measured('HIDDEN-TEST', [1], 'test'))))
    text = experience_document([record])
    assert '未采纳' in text and 'Check unit preconditions' in text and 'train: 0' in text
    assert all(secret not in text for secret in ('PRIVATE', 'HIDDEN-DEV', 'HIDDEN-TEST', 'EVALUATOR-ONLY'))


@pytest.mark.asyncio
@pytest.mark.parametrize('file_mode', [False, True])
async def test_every_round_reads_accumulated_notes_beyond_recent_attempt_window(tmp_path, file_mode):
    class LessonsRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                payload = json.loads(content)['data']
                index = payload['round']
                if file_mode:
                    entry = payload['training_evidence']['experience']
                    text = (tmp_path / 'workspace' / entry).read_text()
                    assert payload['tuning_experience']['path'] == entry
                else:
                    text = payload['tuning_experience']['document']
                for previous in range(1, index):
                    assert f'lesson-{previous}' in text
                assert 'holdout-secret' not in text and 'Convert 7 cm' not in text
            return await super().run(package, agent_id, content, ctx)

    runner = LessonsRunner(proposals=[{'rationale': 'No package change', 'experience_notes': f'lesson-{i}'} for i in range(1, 7)])
    engine = optimizer(runner)
    if file_mode:
        data = engine.tuner.model_dump(mode='json')
        data['package']['manifest']['agents'][engine.tuner.agent_id]['tools'] = ['file_read']
        engine.tuner = type(engine.tuner).model_validate(data)
    original = bundle()
    result = await engine.optimize(original, context=context(), goal='Accuracy', suite=suite(), rounds=6,
        stopping_policy=OptimizationStoppingPolicy(patience=100),
        validation_case_count=1, grow_training=False, tuner_workspace=tmp_path / 'workspace',
        journal_path=tmp_path / 'audit.jsonl')
    assert all(not record.accepted and record.evaluation_reused for record in result.report.rounds)
    assert result.candidate_package == original
    assert 'lesson-6' in result.report.tuning_experience
    for index in range(1, 7):
        before = tmp_path / f'iterations/round-{index:03d}/input/training-evidence/experience.md'
        after = tmp_path / f'iterations/round-{index:03d}/experience.md'
        assert f'lesson-{index}' not in before.read_text()
        assert f'lesson-{index}' in after.read_text()
    assert not any('experience' in name for name in result.candidate_package.files)


@pytest.mark.asyncio
async def test_resume_reconstructs_experience_without_replaying_completed_target(tmp_path):
    from tests.sagents.v2.test_optimization_recovery import safe_optimizer

    class InterruptedRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner' and json.loads(content)['data']['round'] == 2:
                raise ConnectionError('interrupted tuning')
            return await super().run(package, agent_id, content, ctx)

    source = tmp_path / 'first.jsonl'
    kwargs = dict(context=context(), goal='Accuracy', suite=suite(), rounds=3,
        validation_case_count=1, grow_training=False, stopping_policy=OptimizationStoppingPolicy(patience=100),
        recovery_binding_id='frozen-experience-test')
    first = InterruptedRunner(proposals=[{'rationale': 'Keep parent', 'experience_notes': 'lesson-one'}])
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source, **kwargs)
    second = Runner(proposals=[{'rationale': 'Keep parent', 'experience_notes': 'lesson-two'},
                              {'rationale': 'Keep parent', 'experience_notes': 'lesson-three'}])
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path / 'resumed.jsonl',
        resume_from=source, **kwargs)
    assert second.target_hashes == []
    for lesson in ('lesson-one', 'lesson-two', 'lesson-three'):
        assert result.report.tuning_experience.count(lesson) == 1
    data = [json.loads(text)['data'] for name, text in second.requests if name == 'test.tuner']
    assert 'lesson-one' in data[0]['tuning_experience']['document']


@pytest.mark.asyncio
async def test_file_editor_notes_are_separate_from_authored_package_and_next_round_reads_them(tmp_path):
    from sagents.v2.optimization.package_workspace import EDIT_CONTEXT
    class EditorRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.tuner':
                number = json.loads(package.files[EDIT_CONTEXT])['round']
                root = tmp_path / f'iterations/round-{number:03d}/editor'
                if number == 2:
                    assert 'editor-lesson-1' in (root / 'evidence/training-evidence/experience.md').read_text()
                path = root / 'package/files/prompts/base.md'
                path.write_text('Do unit conversions. Never send messages. Verify units.')
                return OptimizationObservation(state='completed', output=json.dumps({
                    'rationale': 'Explicit precondition', 'experience_notes': f'editor-lesson-{number}'}))
            return await super().run(package, agent_id, content, ctx)
    engine = optimizer(EditorRunner())
    data = engine.tuner.model_dump(mode='json')
    data['package']['manifest']['agents'][engine.tuner.agent_id]['tools'] = ['file_read', 'file_write']
    engine.tuner = type(engine.tuner).model_validate(data)
    result = await engine.optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=2, tuner_workspace=tmp_path,
        edit_package_files=True, journal_path=tmp_path / 'audit.jsonl')
    assert [r.patch.experience_notes for r in result.report.rounds] == ['editor-lesson-1', 'editor-lesson-2']
    for record in result.report.rounds:
        assert 'editor-lesson' not in record.candidate_package.model_dump_json()
