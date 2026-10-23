import json

import pytest

from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationObservation
from sagents.v2.optimization.diagnostics import diagnose_scored_execution, execution_chunks, synthesis_evidence
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


def diagnosis(index=0, cause='Skipped required confirmation'):
    return {'summary': cause, 'findings': [{'category': 'confirmation', 'cause': cause,
        'evidence_indexes': [index], 'recommendation': 'Use a reusable confirmation step before state-changing tools.',
        'scope': 'skills', 'confidence': 'confirmed'}], 'strengths': [], 'uncertainties': [], 'coverage': 'Recorded execution'}


def test_chunking_is_lossless_even_for_one_huge_escaped_tool_payload():
    entries = [{'tool_result': '\\"\n' * 10000}, {'user': 'last request'}]
    chunks = execution_chunks(entries, max_chars=2048)
    recovered = {}
    for chunk in chunks:
        assert len(json.dumps(chunk, ensure_ascii=False)) <= 2048
        for part in chunk:
            recovered.setdefault(part['index'], []).append(part)
    for index, entry in enumerate(entries):
        parts = sorted(recovered[index], key=lambda item: item['offset'])
        text = ''.join(part['record'] for part in parts)
        assert text == json.dumps(entry, ensure_ascii=False)
        assert len(text) == parts[0]['total_chars']


@pytest.mark.asyncio
async def test_external_score_is_immutable_and_every_chunk_is_analyzed():
    requests = []
    async def invoke(request):
        requests.append(request)
        data = request['data']
        index = data['execution'][0]['index'] if 'execution' in data else 0
        return json.dumps(diagnosis(index))
    grade = OptimizationGrade(score=.25, passed=False, rationale='External checker fixed grade')
    result = await diagnose_scored_execution(grade=grade, entries=[{'text': 'a' * 70000}],
        rubric='Complete task', policy='Require confirmation', invoke=invoke)
    assert (result.score, result.passed) == (.25, False)
    assert result.diagnosis.findings[0].scope == 'skills'
    assert len([r for r in requests if 'execution' in r['data']]) > 1
    assert 'chunk_diagnoses' in requests[-1]['data']
    assert 'Reviewed all 1 recorded entries' in result.diagnosis.coverage
    assert grade.diagnosis is None


@pytest.mark.asyncio
async def test_unknown_evidence_is_rejected_instead_of_becoming_tuner_advice():
    async def invoke(request):
        return json.dumps(diagnosis(12345))
    with pytest.raises(ValueError, match='outside its chunk'):
        await diagnose_scored_execution(grade=OptimizationGrade(score=0, passed=False, rationale='Failed'),
            entries=[{'user': 'request'}], rubric='Complete', policy='', invoke=invoke)


class DiagnosticRunner(Runner):
    def __init__(self):
        super().__init__(proposals=[{'rationale': 'No unverified patch'}])
        self.comparisons = []
        self.summaries = []

    async def run(self, package, agent_id, content, ctx):
        if package.manifest.metadata.id != 'test.evaluator':
            return await super().run(package, agent_id, content, ctx)
        request = json.loads(content)
        title = request['response_schema']['title']
        if title == 'OptimizationDiagnosis':
            if request['task'].startswith('Compare repeated'):
                self.comparisons.append(request)
            index = request['data']['execution'][0]['index'] if 'execution' in request['data'] else 0
            output = diagnosis(index)
        elif title == 'OptimizationDiagnosisSummary':
            self.summaries.append(request)
            ids = [item['case_id'] for item in request['data']['training_diagnoses']]
            assert ids == ['train']
            assert 'holdout-secret' not in content and 'Convert 7 cm' not in content
            output = {'summary': 'Prioritize reproducible confirmation', 'priorities': [{
                'title': 'Stabilize successful path', 'cause': 'Repeated results differ',
                'recommendation': 'Create a reusable confirmation Skill', 'scope': 'skills',
                'supporting_case_ids': ids}], 'uncertainties': []}
        else:
            observation = await super().run(package, agent_id, content, ctx)
            output = json.loads(observation.output)
            output['diagnosis'] = diagnosis()
        return OptimizationObservation(state='completed', output=json.dumps(output))


@pytest.mark.asyncio
async def test_external_grades_trial_contrast_and_training_only_summary_reach_tuner():
    from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
    runner = DiagnosticRunner()
    async def score(case, observation):
        value = 1 if case.split == 'validation' else float(OPTIMIZATION_TRIAL.get() == 2)
        return OptimizationGrade(score=value, passed=bool(value), rationale='Immutable host checker')
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1,
        evaluation_repeats=3, evaluation_aggregation='mean', authoritative_grader=score)
    training = next(c for c in result.report.baseline.cases if c.case.split == 'training')
    assert training.grade.score == pytest.approx(1/3)
    assert [t.grade.score for t in training.trials] == [0, 1, 0]
    assert training.contrast and runner.comparisons and runner.summaries
    tuning = [json.loads(text)['data'] for name, text in runner.requests if name == 'test.tuner'][0]
    assert tuning['training_diagnosis']['priorities'][0]['scope'] == 'skills'
    assert 'holdout-secret' not in json.dumps(synthesis_evidence(result.report.baseline.cases))
    assert all(c.grade.diagnosis for c in result.report.baseline.cases if c.case.split == 'training')


@pytest.mark.asyncio
async def test_without_external_scorer_eval_decides_numeric_grade_and_supplies_advice():
    runner = DiagnosticRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1)
    assert result.report.baseline.cases[0].grade.score == .4
    assert result.report.baseline.cases[0].grade.diagnosis
    assert runner.summaries


@pytest.mark.asyncio
async def test_tool_audit_rejection_preserves_execution_diagnosis_for_tuning():
    from sagents.v2.optimization.contracts import OptimizationConstraints
    runner = DiagnosticRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1,
        constraints=OptimizationConstraints(require_clean_generated_tools=True))
    training = next(c for c in result.report.baseline.cases if c.case.split == 'training')
    assert training.grade.score == 0 and not training.grade.passed
    assert 'execution audit failed' in training.grade.rationale
    assert training.grade.diagnosis == training.model_grade.diagnosis
    assert training.grade.diagnosis is not None and runner.summaries


@pytest.mark.asyncio
async def test_overlong_diagnostic_summary_is_repaired_without_repeating_target_execution():
    class OverlongSummary(DiagnosticRunner):
        repairs = 0
        async def run(self, package, agent_id, content, ctx):
            request = json.loads(content) if content.startswith('{') else {}
            if request.get('response_schema', {}).get('title') == 'OptimizationDiagnosisSummary':
                if request['task'].startswith('Repair your previous'):
                    self.repairs += 1
                    output = {'summary': 'Concise corrected diagnosis', 'priorities': [], 'uncertainties': []}
                else:
                    output = {'summary': 'x' * 2001, 'priorities': [], 'uncertainties': []}
                return OptimizationObservation(state='completed', output=json.dumps(output))
            return await super().run(package, agent_id, content, ctx)
    runner = OverlongSummary()
    events = []
    await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=1, on_event=events.append)
    assert runner.repairs == 1
    assert sum(e['event'] == 'target_call_started' for e in events) == 2
    assert sum(e['event'] == 'agent_response_repair_requested' for e in events) == 1


@pytest.mark.asyncio
async def test_independent_trial_contrasts_run_in_parallel_with_the_configured_ceiling():
    import asyncio
    from sagents.v2.optimization.contracts import OptimizationCase, OptimizationSuite
    from sagents.v2.optimization.runner import OPTIMIZATION_TRIAL
    class ParallelRunner(DiagnosticRunner):
        active = 0
        peak = 0
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.evaluator':
                request = json.loads(content)
                if request['response_schema']['title'] == 'OptimizationDiagnosisSummary':
                    return OptimizationObservation(state='completed', output=json.dumps({
                        'summary': 'Use the successful execution paths', 'priorities': [], 'uncertainties': []}))
                if request['task'].startswith('Compare repeated'):
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    try:
                        await asyncio.sleep(.01)
                        return await super().run(package, agent_id, content, ctx)
                    finally:
                        self.active -= 1
            return await super().run(package, agent_id, content, ctx)
    async def score(case, observation):
        value = float(case.split == 'validation' or OPTIMIZATION_TRIAL.get() == 2)
        return OptimizationGrade(score=value, passed=bool(value), rationale='Fixed score')
    cases = OptimizationSuite(cases=tuple(OptimizationCase(id=f'train-{i}', input=f'task-{i}', rubric='Complete')
        for i in range(3)) + (OptimizationCase(id='hidden', input='private', rubric='Complete', split='validation'),))
    runner = ParallelRunner()
    await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy', suite=cases,
        validation_case_count=1, grow_training=False, rounds=1, max_concurrency=2,
        evaluation_repeats=3, evaluation_aggregation='mean', authoritative_grader=score)
    assert len(runner.comparisons) == 3
    assert runner.peak == 2
