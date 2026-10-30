"""Capability dispatch, strict outputs and anonymous multimodal Eval Agent input."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

import pytest

from sagents.v2.optimization.comparison_plugin import PreparedComparisonArtifact
from sagents.v2.optimization.contracts import OptimizationDiagnosis, OptimizationObservation
from sagents.v2.optimization.evaluation_plugin import (
    EvaluationCapabilities, EvaluationRequest, EvaluationResult, PythonEvaluationPlugin, agent_fallback, evidence_content,
)
from sagents.v2.optimization.pairwise import PairwiseDecision
from sagents.v2.optimization.scoring import ScorerDescriptor
from tests.sagents.v2.test_package_optimizer import suite


def diagnosis():
    return OptimizationDiagnosis(summary='Typography and spacing support the brief.', coverage='Supplied visual evidence',
        next_action='test_hypothesis', next_verification='Compare visual hierarchy while preserving readability')


@pytest.mark.asyncio
@pytest.mark.parametrize('declared_analysis', [False, True])
async def test_initial_reference_is_single_result_analysis_without_a_fabricated_judgment(tmp_path, declared_analysis):
    instance = plugin(tmp_path, {'mode':'pairwise', 'analyze':declared_analysis,
        'evaluate':True, 'evaluation_includes_analysis':True})
    evidence = PreparedComparisonArtifact(artifact={'presentation':{'text':'Initial website'}})
    observation = OptimizationObservation(state='completed', output='index.html')
    calls = []
    async def invoke(operation, request, schema):
        calls.append(operation)
        assert operation == 'analyze'
        assert request.result is None
        assert request.goal == 'Beauty'
        assert request.evaluation.observation == observation
        assert request.evaluation.evidence == evidence
        assert request.evaluation.A is None and request.evaluation.B is None
        return diagnosis()
    async def ask(task, data, schema):
        assert 'absence of a comparison is expected' in task
        assert data['authoritative_result'] is None
        assert [label for label, _ in data['_evaluation_artifacts']] == ['result']
        return diagnosis()
    instance._operation = invoke
    instance.fallback = agent_fallback(ask)
    result = await instance.analyze_reference(goal='Beauty', case=suite().cases[0],
        observation=observation, evidence=evidence)
    assert result == diagnosis()
    assert calls == (['analyze'] if declared_analysis else [])


def plugin(tmp_path, capabilities):
    path = tmp_path/'scorer.py'
    path.write_text('')
    return PythonEvaluationPlugin(path=path, source_hash=hashlib.sha256(b'').hexdigest(),
        descriptor=ScorerDescriptor(id='capabilities', name='Capabilities', version='1'), capabilities=capabilities)


@pytest.mark.asyncio
@pytest.mark.parametrize('evaluate,analyze,combined,expected', [
    (False, False, False, ['agent:evaluate']),
    (False, True, False, ['agent:evaluate', 'plugin:analyze']),
    (True, False, False, ['plugin:evaluate', 'agent:analyze']),
    (True, True, False, ['plugin:evaluate', 'plugin:analyze']),
    (True, False, True, ['plugin:evaluate']),
])
async def test_capabilities_fill_only_missing_stages_and_always_supply_goal(tmp_path, evaluate, analyze, combined, expected):
    instance = plugin(tmp_path, {'mode': 'pairwise', 'evaluate': evaluate, 'analyze': analyze,
        'evaluation_includes_analysis': combined})
    calls = []
    async def invoke(owner, operation, request, schema):
        assert request.goal == 'Artistic beauty'
        calls.append(f'{owner}:{operation}')
        if operation == 'evaluate':
            return EvaluationResult(comparison=PairwiseDecision(winner='A', rationale='Stronger composition'),
                analysis=diagnosis() if combined or owner == 'agent' and not analyze else None)
        return diagnosis()
    instance._operation = lambda *args: invoke('plugin', *args)
    instance.fallback = lambda *args: invoke('agent', *args)
    evidence = PreparedComparisonArtifact(artifact={'presentation': {'text': 'Rendered output'}})
    result = await instance.assess(EvaluationRequest(goal='Artistic beauty', case=suite().cases[0], A=evidence, B=evidence))
    assert result.analysis == diagnosis()
    assert calls == expected


@pytest.mark.asyncio
async def test_promised_analysis_missing_is_a_failure_not_agent_fallback(tmp_path):
    instance = plugin(tmp_path, {'mode': 'pairwise', 'evaluate': True, 'evaluation_includes_analysis': True})
    async def evaluate(*args):
        return EvaluationResult(comparison=PairwiseDecision(winner='A', rationale='A'))
    instance._operation = evaluate
    instance.fallback = lambda *args: pytest.fail('Do not hide a broken capability declaration')
    evidence = PreparedComparisonArtifact(artifact={'text': 'x'})
    with pytest.raises(ValueError, match='promised analysis'):
        await instance.assess(EvaluationRequest(goal='Beauty', case=suite().cases[0], A=evidence, B=evidence))


@pytest.mark.asyncio
async def test_hidden_test_and_training_fallbacks_are_task_local(tmp_path):
    instance = plugin(tmp_path, {'mode': 'pairwise', 'prepare': True})
    async def task(name):
        instance.fallback = name
        instance.artifact_root = name
        await asyncio.sleep(.01)
        assert instance.fallback == name and instance.artifact_root == name
    await asyncio.gather(task('training'), task('hidden-test'))
    assert instance.fallback is None


def test_native_images_are_bound_and_no_source_or_version_is_presented(tmp_path):
    from evaluation_datasets.web_design.rendering import frozen
    path = tmp_path/'image.png'
    path.write_bytes(b'fixture-image-bytes')
    artifact = PreparedComparisonArtifact(artifact={'private_version': 'SECRET-VERSION',
        'presentation': {'text': 'Mobile view', 'images': [str(path)]}}, files=(frozen(path, 'image/png'),))
    content = evidence_content('Compare', {'goal': 'Beauty'}, EvaluationResult, [('A', artifact)])
    assert content[-1].kind == 'image' and content[-1].uri.startswith('data:image/png;base64,')
    assert 'SECRET-VERSION' not in content[0].text and str(path) not in content[0].text
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='missing or changed'):
        evidence_content('Compare', {}, EvaluationResult, [('A', artifact)])


@pytest.mark.asyncio
async def test_web_plugin_import_validation_in_isolated_worker():
    path = Path('evaluation_datasets/web_design/scorer.py').resolve()
    instance = PythonEvaluationPlugin(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        descriptor=ScorerDescriptor(id='web', name='Web', version='1'), python_executable=sys.executable, timeout=20)
    result = await instance.validate()
    assert result['protocol'] == 'sage.rsi.comparison/v1'
    assert instance.capabilities.prepare and not instance.capabilities.evaluate


def test_schemas_reject_ambiguous_results_and_incomplete_pairs():
    with pytest.raises(ValueError):
        EvaluationCapabilities(mode='pairwise', evaluation_includes_analysis=True)
    with pytest.raises(ValueError):
        EvaluationResult()
    with pytest.raises(ValueError):
        EvaluationRequest(goal='Beauty', case=suite().cases[0], A=PreparedComparisonArtifact(artifact={'text': 'x'}))


@pytest.mark.asyncio
async def test_fallback_receives_goal_and_excludes_split_history_and_reference():
    seen = []
    async def ask(task, data, schema):
        seen.append(data)
        return EvaluationResult(comparison=PairwiseDecision(winner='tie', rationale='Equal beauty'), analysis=diagnosis())
    artifact = PreparedComparisonArtifact(artifact={'presentation': {'text': 'View'}})
    request = EvaluationRequest(goal='Beauty', case=suite().cases[0].model_copy(update={'reference_answer': 'PRIVATE'}),
        A=artifact, B=artifact)
    await agent_fallback(ask)('evaluate', request, EvaluationResult)
    assert seen[0]['goal'] == 'Beauty'
    assert 'PRIVATE' not in json.dumps(seen)
    assert set(seen[0]['case']) == {'input', 'rubric'}


@pytest.mark.asyncio
async def test_absolute_assessment_uses_structured_analysis_without_changing_score(tmp_path):
    from sagents.v2.optimization.scoring import ScoringRequest
    instance = plugin(tmp_path, {'mode': 'absolute', 'evaluate': True, 'evaluation_includes_analysis': True})
    async def operation(*args):
        from sagents.v2.optimization.contracts import OptimizationGrade
        return EvaluationResult(grade=OptimizationGrade(score=.2, passed=False, rationale='Fixed result'), analysis=diagnosis())
    instance._operation = operation
    instance.fallback = lambda *args: pytest.fail('Fully supplied evaluation must not invoke Eval Agent')
    result = await instance.score(ScoringRequest(goal='Beauty', case=suite().cases[0],
        observation=OptimizationObservation(state='completed', output='Website')))
    assert result.grade.score == .2 and result.grade.diagnosis == diagnosis()


@pytest.mark.asyncio
async def test_diagnostic_evidence_is_hidden_from_judgment_and_loaded_afterward(tmp_path):
    from evaluation_datasets.web_design.rendering import frozen
    from sagents.v2.optimization.evaluation_plugin import AnalysisRequest
    record = tmp_path/'execution.json'
    record.write_text('[{"tool":"file_write","success":true}]')
    artifact = PreparedComparisonArtifact(artifact={'presentation':{'text':'Rendered result'}},
        files=(frozen(record,'application/json'),), diagnostics={'text':'Recorded process', 'files':[str(record)]})
    seen = []
    async def ask(task, data, schema):
        seen.append(data)
        if schema is EvaluationResult:
            assert 'diagnostic_evidence' not in data
            assert 'judgment only' in task
            return EvaluationResult(comparison=PairwiseDecision(winner='A',rationale='Better visual hierarchy'))
        assert data['_evaluation_use_files']
        assert data['diagnostic_evidence'][0]['documents'][0]['content'] == record.read_text()
        assert data['authoritative_result']['comparison']['winner'] == 'A'
        return diagnosis()
    fallback = agent_fallback(ask)
    request = EvaluationRequest(goal='Beauty',case=suite().cases[0],A=artifact,B=artifact)
    result = await fallback('evaluate', request, EvaluationResult)
    await fallback('analyze', AnalysisRequest(goal='Beauty',case=request.case,evaluation=request,result=result), OptimizationDiagnosis)
    assert len(seen)==2


@pytest.mark.asyncio
async def test_full_plugin_replaces_judgment_analysis_and_direction_summary(tmp_path):
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer
    from sagents.v2.optimization.builtin_scoring import BuiltinScoring
    evidence = PreparedComparisonArtifact(artifact={'presentation': {'text': 'base'}})
    request = EvaluationRequest(goal='Beauty', case=suite().cases[0], A=evidence, B=evidence)
    summary = {'summary': 'Preserve typography; verify composition.', 'priorities': [], 'uncertainties': [],
        'next_action': 'test_hypothesis', 'next_verification': 'Measure composition improvement'}
    from sagents.v2.optimization.evaluation_plugin import SummaryRequest
    source = '''EVALUATION_CAPABILITIES = {'mode':'pairwise','evaluate':True,'evaluation_includes_analysis':True,'analyze':True,'summarize':True}
EVALUATION_CONTRACT = 'Judge text fixture quality and supply complete analysis and training directions.'
ANALYSIS = ''' + repr(diagnosis().model_dump(mode='json')) + '''
SUMMARY = ''' + repr(summary) + '''
def evaluate(request):
    a = request['A']['artifact']['presentation']['text']
    b = request['B']['artifact']['presentation']['text']
    return {'comparison': {'winner': 'tie' if a == b else 'B' if a == 'base' else 'A', 'rationale':'Stronger composition'}, 'analysis': ANALYSIS}
def analyze(request):
    assert request['result'] is None
    assert request['evaluation']['A'] is None
    assert request['evaluation']['observation']['state'] == 'completed'
    return ANALYSIS
def summarize(request):
    assert request['goal'] == 'Beauty'
    assert all(row['case_id'] == 'train' for row in request['training_diagnoses'])
    return SUMMARY
EVALUATION_TEST_CASES = ''' + repr([
        {'operation': 'evaluate', 'request': request.model_dump(mode='json'), 'expected': {'analysis': diagnosis().model_dump(mode='json')}},
        {'operation': 'analyze', 'request': {'goal':'Beauty', 'case':suite().cases[0].model_dump(mode='json'),
            'evaluation':EvaluationRequest(goal='Beauty',case=suite().cases[0],observation=OptimizationObservation(state='completed',output='base'),evidence=evidence).model_dump(mode='json')},
            'expected':{'summary':diagnosis().summary}},
        {'operation': 'summarize', 'request': SummaryRequest(goal='Beauty', training_diagnoses=({'case_id': 'train'},)).model_dump(mode='json'),
            'expected': {'summary': summary['summary']}}])
    path = tmp_path/'full.py'
    path.write_text(source)
    instance = PythonEvaluationPlugin(path=path, source_hash=hashlib.sha256(source.encode()).hexdigest(),
        descriptor=ScorerDescriptor(id='full', name='Full', version='1'), timeout=20)
    await instance.validate()
    class NoEvaluationRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            assert package.manifest.metadata.id != 'test.evaluator', 'Plugin fully replaces evaluation and summary'
            return await super().run(package, agent_id, content, ctx)
    result = await optimizer(NoEvaluationRunner()).optimize(bundle(), context=context(), goal='Beauty', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=1,
        builtin_scoring=BuiltinScoring(mode='pairwise'), comparison_plugin=instance,
        journal_path=tmp_path/'journal.jsonl')
    assert result.report.rounds
    assert result.report.baseline.cases[0].grade.diagnosis is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('split', ['validation', 'test'])
async def test_nonlearning_comparisons_skip_unused_analysis_but_keep_real_judgment(tmp_path, split):
    from sagents.v2.optimization.comparison_plugin import ComparisonRequest
    instance = plugin(tmp_path, {'mode':'pairwise', 'prepare':True})
    calls = []
    async def fallback(operation, request, schema):
        calls.append(operation)
        return EvaluationResult(comparison=PairwiseDecision(winner='B', rationale='Better rhythm'))
    instance.fallback = fallback
    evidence = PreparedComparisonArtifact(artifact={'text':'Captured website'})
    case = suite().cases[0].model_copy(update={'split':split})
    result = await instance.compare(ComparisonRequest(goal='Beauty', case=case, A=evidence, B=evidence))
    assert result.winner == 'B' and result.analysis is None
    assert calls == ['evaluate']
