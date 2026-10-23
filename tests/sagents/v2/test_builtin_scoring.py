import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from sagents.v2 import BuiltinScoring
from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationGrade, OptimizationObservation
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite


class ResourceRunner(Runner):
    def __init__(self, *, candidate_quality=.8):
        super().__init__(proposals=[{'rationale': 'Remove redundant work', 'instruction_guidance': 'guidance-1'}],
                         scores={'base': .8, 'guidance-1': candidate_quality})

    async def run(self, package, agent_id, content, ctx):
        result = await super().run(package, agent_id, content, ctx)
        if package.manifest.metadata.id == 'test.target':
            old = result.output == 'base'
            result = result.model_copy(update={'cost': 2 if old else .01,
                'elapsed_seconds': 120 if old else 1, 'input_tokens': 20000 if old else 100,
                'usage_reported': True})
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['quality', 'quality_cost', 'quality_latency', 'quality_tokens'])
async def test_default_preserves_quality_only_and_opt_in_can_select_same_quality_with_less_work(mode):
    runner = ResourceRunner()
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy', suite=suite(),
        validation_case_count=1, grow_training=False, rounds=1, builtin_scoring=BuiltinScoring(mode=mode))
    assert result.report.rounds[0].accepted is (mode != 'quality')
    assert result.report.baseline.overall_score() == result.report.selected.overall_score() == .8
    assert all(c.grade.passed for c in result.report.selected.cases)
    if mode == 'quality':
        assert result.report.baseline.objective_score() == .8
        assert all(c.objective_score is None and not c.score_metrics for c in result.report.baseline.cases)
    else:
        assert result.report.selected.objective_score() > result.report.baseline.objective_score()
        assert result.report.rounds[0].objective_after > result.report.rounds[0].objective_before
    assert result.report.builtin_scoring['mode'] == mode


@pytest.mark.asyncio
async def test_savings_cannot_make_a_failed_zero_quality_candidate_successful():
    result = await optimizer(ResourceRunner(candidate_quality=0)).optimize(bundle(), context=context(),
        goal='Accuracy', suite=suite(), validation_case_count=1, grow_training=False, rounds=1,
        builtin_scoring=BuiltinScoring(mode='quality_cost'))
    assert not result.report.rounds[0].accepted
    assert all(c.objective_score == 0 and not c.grade.passed for c in result.report.rounds[0].evaluation.cases)


def test_unknown_cost_is_not_free_and_references_are_validated():
    case = OptimizationCaseResult(case=suite().cases[0], observation=OptimizationObservation(state='completed'),
        grade=OptimizationGrade(score=1, passed=True, rationale='Correct'))
    with pytest.raises(ValueError, match='missing cost is not zero'):
        BuiltinScoring(mode='quality_cost').apply(case)
    with pytest.raises(ValueError, match='complete provider usage'):
        BuiltinScoring(mode='quality_tokens').apply(case)
    for fields in ({'cost_reference': 0}, {'efficiency_weight': 1}, {'token_reference': float('nan')}):
        with pytest.raises(ValueError):
            BuiltinScoring(**fields)


@pytest.mark.asyncio
async def test_repeat_aggregation_retains_trial_objectives_and_per_execution_resource_metrics():
    result = await optimizer(ResourceRunner()).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1,
        evaluation_repeats=3, evaluation_aggregation='mean', builtin_scoring=BuiltinScoring(mode='quality_tokens'))
    for case in result.report.baseline.cases:
        assert len(case.trials) == 3
        assert case.score_metrics['tokens'] == 20005  # Per execution, not three times the budget.
        assert case.objective_score == pytest.approx(case.trials[0].objective_score)
        assert case.grade.score == pytest.approx(.8) and case.grade.passed


@pytest.mark.asyncio
async def test_dialogue_efficiency_includes_all_turns_without_changing_quality_or_stop_condition():
    class DialogueRunner(Runner):
        def __init__(self):
            super().__init__(proposals=[{'rationale': 'No change'}])

        @asynccontextmanager
        async def conversation(self, *args):
            turns = 0
            async def send(content):
                nonlocal turns
                turns += 1
                return OptimizationObservation(state='completed', output='done' if turns == 2 else 'question',
                    cost=3 if turns == 1 else 2, elapsed_seconds=10, input_tokens=100, output_tokens=10)
            yield SimpleNamespace(send=send)

        async def run(self, package, agent_id, content, ctx):
            data = json.loads(content)
            if data['task'].startswith('Continue this test'):
                return OptimizationObservation(state='completed', output=json.dumps({
                    'can_continue': True, 'message': 'Known fact', 'rationale': 'Use context'}))
            if package.manifest.metadata.id == 'test.evaluator':
                done = data['data']['observation']['output'] == 'done'
                return OptimizationObservation(state='completed', output=json.dumps({
                    'score': 1 if done else 0, 'passed': done, 'rationale': 'Actual completion'}))
            return await super().run(package, agent_id, content, ctx)

    cases = suite().model_copy(update={'cases': tuple(c.model_copy(update={
        'mode': 'dialogue', 'user_context': 'Known fact', 'max_turns': 3}) for c in suite().cases)})
    result = await optimizer(DialogueRunner()).optimize(bundle(), context=context(), goal='Complete dialogue',
        suite=cases, validation_case_count=1, grow_training=False, rounds=1,
        builtin_scoring=BuiltinScoring(mode='quality_cost'))
    for case in result.report.baseline.cases:
        assert case.score_metrics['cost'] == 5
        assert case.observation.elapsed_seconds == 20
        assert len(case.dialogue) == 2 and case.stop_reason == 'goal_achieved'
        assert case.grade.score == 1 and case.grade.passed


@pytest.mark.asyncio
async def test_resource_objective_keeps_custom_quality_score_and_diagnosis_authoritative():
    from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner
    class ReportedRunner(DiagnosticRunner):
        async def run(self, *args):
            return (await super().run(*args)).model_copy(update={'usage_reported': True})
    result = await optimizer(ReportedRunner()).optimize(bundle(), context=context(), goal='Accuracy',
        suite=suite(), validation_case_count=1, grow_training=False, rounds=1,
        authoritative_grader=lambda case, observation: OptimizationGrade(score=.25, passed=False, rationale='Fixed'),
        builtin_scoring=BuiltinScoring(mode='quality_tokens'))
    for case in result.report.baseline.cases:
        assert case.grade.score == .25 and not case.grade.passed
        assert case.grade.diagnosis is not None and case.objective_score < .25
