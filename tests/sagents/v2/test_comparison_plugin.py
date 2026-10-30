"""Dataset-owned comparison ABI, isolated worker and artifact preparation."""
import hashlib
import json
import sys

import pytest

from sagents.v2.optimization.comparison_plugin import (
    ComparisonPreparationRequest, ComparisonRequest, PreparedComparisonArtifact, PythonComparisonPlugin,
)
from sagents.v2.optimization.scoring import ScorerDescriptor
from sagents.v2.optimization.pairwise import PairwiseEvaluator
from tests.sagents.v2.test_pairwise_evaluation import artifact
from tests.sagents.v2.test_package_optimizer import suite


def plugin_source():
    case = suite().cases[0]
    prepare = ComparisonPreparationRequest(capture_id='self-test', goal='Clarity', case=case, observation=artifact('good'))
    compare = ComparisonRequest(goal='Clarity', case=case,
        A=PreparedComparisonArtifact(artifact={'text': 'good'}), B=PreparedComparisonArtifact(artifact={'text': 'bad'}))
    tests = [dict(operation='prepare', request=prepare.model_dump(mode='json'), expected_artifact={'text': 'good'}),
        dict(operation='compare', request=compare.model_dump(mode='json'), expected_winner='A')]
    return '''COMPARISON_CONTRACT = "Freeze textual artifacts and prefer good over bad. No rendering."
def prepare(request):
    return {'artifact': {'text': request['observation']['output']}}
def compare(request):
    a, b = request['A']['artifact']['text'], request['B']['artifact']['text']
    return {'winner': 'tie' if a == b else 'A' if a == 'good' else 'B', 'rationale': 'Checked frozen artifact'}
COMPARISON_TEST_CASES = ''' + repr(tests)


@pytest.mark.asyncio
async def test_comparison_worker_uses_selected_runtime_and_keeps_absolute_protocol_separate(tmp_path):
    source = plugin_source()
    path = tmp_path/'plugin.py'
    path.write_text(source)
    plugin = PythonComparisonPlugin(path=path, source_hash=hashlib.sha256(source.encode()).hexdigest(),
        descriptor=ScorerDescriptor(id='compare', name='Dataset comparator', version='1'), python_executable=sys.executable)
    result = await plugin.validate()
    assert result['protocol'] == 'sage.rsi.comparison/v1' and result['cases'] == 2
    assert plugin.dependency_manifest['environment']['executable'] == sys.executable
    evaluator = PairwiseEvaluator(binding='run', plugin=plugin, goal='Clarity', directory=tmp_path/'private')
    case = suite().cases[0]
    await evaluator.grade(case, artifact('bad'), trial=1, is_reference=True, execution_id='original')
    grade = await evaluator.grade(case, artifact('good'), trial=1, execution_id='candidate')
    assert grade.score == 1 and grade.scorer_details['pairwise']['outcome'] == 'win'
    with pytest.raises(RuntimeError, match='prepare/compare'):
        await plugin.score(None)


@pytest.mark.asyncio
async def test_capture_ids_separate_identical_outputs_across_trials_and_versions(tmp_path):
    class Plugin:
        prepared = []
        async def prepare(self, request):
            self.prepared.append(request.capture_id)
            return PreparedComparisonArtifact(artifact={'capture': request.capture_id})
        async def compare(self, request):
            return {'winner': 'tie', 'rationale': 'No preference'}
    plugin = Plugin()
    evaluator = PairwiseEvaluator(binding='run', plugin=plugin, directory=tmp_path)
    case = suite().cases[0]
    for trial in (1, 2):
        await evaluator.grade(case, artifact('same'), trial=trial, is_reference=True, execution_id='base')
        await evaluator.grade(case, artifact('same'), trial=trial, execution_id='candidate')
    assert len(plugin.prepared) == len(set(plugin.prepared)) == 4
    # Same receipt is reused on replay, never recaptured from mutable output paths.
    await evaluator.grade(case, artifact('same'), trial=1, execution_id='candidate')
    await evaluator.grade(case, artifact('same'), trial=1, is_reference=True)
    assert len(plugin.prepared) == 4


def test_wire_schemas_reject_absolute_results_and_empty_artifacts():
    from sagents.v2.optimization.pairwise import PairwiseDecision
    with pytest.raises(ValueError):
        PairwiseDecision.model_validate({'score': 1, 'passed': True, 'rationale': 'Not a comparison'})
    with pytest.raises(ValueError):
        PreparedComparisonArtifact(artifact={})
    assert json.loads(PreparedComparisonArtifact(artifact={'text': 'x'}).model_dump_json())['protocol'] == 'sage.rsi.comparison.artifact/v1'


@pytest.mark.asyncio
async def test_hidden_evaluator_uses_separate_fixed_artifacts_and_trial_indexes(tmp_path):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from sagents.v2.optimization.contracts import OptimizationAgent
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
    from tests.sagents.v2.test_package_optimizer import bundle, context
    original = bundle()
    changed = original.model_copy(update={'files': {**original.files, 'prompts/base.md': 'new policy'}})
    seen = []
    class Runner:
        @asynccontextmanager
        async def conversation(self, package, target, ctx):
            async def send(content):
                seen.append((package.content_hash, OPTIMIZATION_TRIAL.get()))
                return artifact('bad' if package.content_hash == original.content_hash else 'good')
            yield SimpleNamespace(send=send)
    class Plugin:
        async def prepare(self, request):
            return PreparedComparisonArtifact(artifact={'text': request.observation.output})
        async def compare(self, request):
            return {'winner': 'A' if request.A.artifact['text'] == 'good' else 'B', 'rationale': 'Good artifact'}
    role = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=Runner(), evaluator=role, driver=role, context=context(), goal='Clarity',
        pairwise_baseline=original, comparison_plugin=Plugin(), evidence_directory=tmp_path)
    case = suite().cases[0].model_copy(update={'id': 'hidden', 'input': 'HIDDEN TASK', 'split': 'test'})
    for trial in (1, 2):
        token = OPTIMIZATION_TRIAL.set(trial)
        try:
            assert (await measure(changed, case))['grade']['score'] == 1
            # Retained original reuses its frozen artifact rather than executing again.
            assert (await measure(original, case))['grade']['score'] == .5
        finally:
            OPTIMIZATION_TRIAL.reset(token)
    assert len(seen) == 4
    assert seen.count((original.content_hash, 1)) == seen.count((original.content_hash, 2)) == 1


@pytest.mark.asyncio
async def test_changed_frozen_artifact_fails_measurement_instead_of_becoming_a_loss(tmp_path):
    from sagents.v2.optimization.comparison_plugin import FrozenComparisonFile
    from sagents.v2.optimization.pairwise import PairwiseMeasurementError
    captured = []
    class Plugin:
        async def prepare(self, request):
            from pathlib import Path
            frozen = Path(request.artifact_directory)/'snapshot.bin'
            frozen.write_bytes(b'original')
            captured.append(frozen)
            return PreparedComparisonArtifact(artifact={'label': 'snapshot'}, files=(FrozenComparisonFile(
                path=str(frozen), sha256=hashlib.sha256(b'original').hexdigest(), size_bytes=8,
                media_type='application/octet-stream'),))
        async def compare(self, request):
            pytest.fail('Changed frozen evidence must not be judged')
    evaluator = PairwiseEvaluator(binding='run', plugin=Plugin(), directory=tmp_path/'private')
    case = suite().cases[0]
    await evaluator.grade(case, artifact('base'), trial=1, is_reference=True)
    captured[0].write_bytes(b'modified')
    with pytest.raises(PairwiseMeasurementError, match='missing or changed'):
        await evaluator.grade(case, artifact('candidate'), trial=1)


@pytest.mark.asyncio
async def test_plugin_runtime_file_reads_are_not_mistaken_for_static_dependencies(tmp_path):
    source = plugin_source().replace("return {'artifact': {'text': request['observation']['output']}}", """text = request['observation']['output']
    if text.startswith('FILE:'):
        from pathlib import Path
        text = Path(text[5:]).read_text()
    return {'artifact': {'text': text}}""")
    path = tmp_path/'plugin.py'
    path.write_text(source)
    plugin = PythonComparisonPlugin(path=path, source_hash=hashlib.sha256(source.encode()).hexdigest(),
        descriptor=ScorerDescriptor(id='files', name='Runtime file comparator', version='1'))
    await plugin.validate()
    case = suite().cases[0]
    for index, text in enumerate(['bad', 'good']):
        data = tmp_path/f'execution-{index}.txt'
        data.write_text(text)
        request = ComparisonPreparationRequest(capture_id=str(index), goal='Clarity', case=case,
            observation=artifact('FILE:'+str(data)))
        prepared = await plugin.prepare(request)
        assert prepared.artifact == {'text': text}
