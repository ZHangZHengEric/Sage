"""A completed trajectory is diagnosed once; authoritative per-turn scores stay intact."""
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from sagents.v2.optimization.contracts import OptimizationGrade, OptimizationObservation
from sagents.v2.optimization.scoring import ScorerDescriptor, ScoringResult
from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner, diagnosis
from tests.sagents.v2.test_package_optimizer import bundle, context, optimizer, suite


class Scorer:
    descriptor = ScorerDescriptor(id='turns', name='Turns', version='1')
    def __init__(self):
        self.histories = []
    async def score(self, request):
        self.histories.append(request.conversation)
        return ScoringResult(grade=OptimizationGrade(score=len(request.conversation) * .2,
            passed=False, rationale='Fixed external per-turn score'))


class Runner(DiagnosticRunner):
    def __init__(self):
        super().__init__()
        self.diagnoses = []
    @asynccontextmanager
    async def conversation(self, *args):
        turns = 0
        async def send(content):
            nonlocal turns
            turns += 1
            return OptimizationObservation(state='completed', output=f'target-turn-{turns}')
        yield SimpleNamespace(send=send)
    async def run(self, package, agent_id, content, ctx):
        payload = json.loads(content)
        title = payload.get('response_schema', {}).get('title')
        if title == 'OptimizationDialogueReply':
            return OptimizationObservation(state='completed', output=json.dumps({
                'can_continue': True, 'message': 'Continue the original task', 'rationale': 'Needs completion'}))
        if title == 'OptimizationDiagnosis':
            self.diagnoses.append(payload)
            return OptimizationObservation(state='completed', output=json.dumps(diagnosis()))
        return await super().run(package, agent_id, content, ctx)


def assert_complete_history(diagnoses):
    assert diagnoses
    for payload in diagnoses:
        text = json.dumps(payload)
        assert all(f'target-turn-{i}' in text for i in range(1, 4))


@pytest.mark.asyncio
async def test_optimizer_analyzes_the_whole_dialogue_once_and_keeps_each_turn_score():
    runner, scorer = Runner(), Scorer()
    dataset = suite().model_copy(update={'cases': tuple(c.model_copy(update={'mode': 'dialogue', 'max_turns': 3}) for c in suite().cases)})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy',
        suite=dataset, rounds=1, validation_case_count=1, grow_training=False, scorer=scorer)
    assert_complete_history(runner.diagnoses)
    assert len(scorer.histories) == 3 * len(runner.diagnoses)
    for case in result.report.baseline.cases:
        assert [turn.grade.score for turn in case.dialogue] == pytest.approx([.2, .4, .6])
        assert case.grade.score == pytest.approx(.6) and case.grade.diagnosis
        assert not case.dialogue[0].grade.diagnosis
        assert case.dialogue[-1].grade.diagnosis


@pytest.mark.asyncio
async def test_human_test_analyzes_the_whole_dialogue_once():
    from sagents.v2.optimization import OptimizationAgent
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    runner, scorer = Runner(), Scorer()
    evaluator = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
    measure = IsolatedTestEvaluator(runner=runner, evaluator=evaluator, driver=evaluator,
        context=context(), goal='Accuracy', scorer=scorer)
    case = suite().cases[0].model_copy(update={'mode': 'dialogue', 'max_turns': 3})
    result = await measure(bundle(), case)
    assert_complete_history(runner.diagnoses)
    assert len(runner.diagnoses) == 1 and len(scorer.histories) == 3
    assert result['grade']['score'] == pytest.approx(.6)
    assert result['grade']['diagnosis']
