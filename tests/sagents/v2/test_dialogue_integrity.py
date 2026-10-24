"""Regression tests for dialogue completion, selection and independent recovery."""
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from sagents.v2.optimization.contracts import (
    OptimizationCaseResult, OptimizationEvaluation, OptimizationGrade,
    OptimizationObservation, OptimizationStoppingPolicy,
)
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from tests.sagents.v2.test_package_optimizer import Runner, bundle, context, optimizer, suite
from tests.sagents.v2.test_optimization_recovery import safe_optimizer


class Dialogue(Runner):
    def __init__(self, *, blank=False, interrupt_at=None):
        super().__init__(scores={'base': 1, 'guidance-1': 1})
        self.sends, self.blank, self.interrupt_at = 0, blank, interrupt_at
    @asynccontextmanager
    async def conversation(self, *args):
        async def send(content):
            self.sends += 1
            if self.sends == self.interrupt_at:
                raise ConnectionError('isolated interrupted confirmation')
            return OptimizationObservation(state='completed', output='base')
        yield SimpleNamespace(send=send)
    async def run(self, package, agent_id, content, ctx):
        data = json.loads(content)
        if data.get('response_schema', {}).get('title') == 'OptimizationDialogueReply':
            return OptimizationObservation(state='completed', output=json.dumps({
                'can_continue': self.blank, 'message': '', 'rationale': 'Continue' if self.blank else 'Finished'}))
        return await super().run(package, agent_id, content, ctx)


def dialogues():
    return suite().model_copy(update={'cases': tuple(c.model_copy(update={
        'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 3,
        'user_context': 'Ask follow-up questions as needed'}) for c in suite().cases)})


@pytest.mark.asyncio
async def test_blank_continue_is_rejected_instead_of_recording_a_finished_user():
    with pytest.raises(ValueError, match='nonempty message'):
        await optimizer(Dialogue(blank=True)).optimize(bundle(), context=context(), goal='Conversions',
            suite=dialogues(), rounds=1, validation_case_count=None, final_max_cases=0)


@pytest.mark.asyncio
async def test_interrupted_stability_executes_fresh_dialogues_after_recovery(tmp_path):
    options = dict(context=context(), goal='Conversions', suite=dialogues(), rounds=2,
        validation_case_count=None, final_max_cases=0, grow_training=False,
        stopping_policy=OptimizationStoppingPolicy(stability_passes=2), recovery_binding_id='offline-fixed')
    first = Dialogue(interrupt_at=3)
    source = tmp_path / 'first.jsonl'
    with pytest.raises(ConnectionError):
        await safe_optimizer(first).optimize(bundle(), journal_path=source, **options)
    assert first.sends == 3  # Baseline pair, then the first independent confirmation failed.
    second = Dialogue()
    result = await safe_optimizer(second).optimize(bundle(), journal_path=tmp_path/'resume.jsonl',
        resume_from=source, restart_incomplete=True, **options)
    assert result.report.termination.reason == 'target_reached'
    assert result.report.termination.stability_passes == 2
    assert second.sends == 2  # Only the original baseline is reused; confirmation is fresh.


def test_all_selection_paths_reject_failed_tool_audit_with_external_score():
    def evaluation(score, audit):
        return OptimizationEvaluation(package_hash=str(score), cases=tuple(OptimizationCaseResult(
            case=c, observation=OptimizationObservation(state='completed',
                evidence={'generated_tool_audit': {'passed': audit}}),
            grade=OptimizationGrade(score=score, passed=True, rationale='External score')) for c in suite().cases))
    old, new = evaluation(.4, True), evaluation(.8, False)
    assert not AgentPackageOptimizer._select(old, new, .01)[0]
    assert not AgentPackageOptimizer._select_adaptive(old, new, .01)[0]



def test_explicit_user_driver_preserves_custom_instructions_and_default_is_clean():
    from sagents.v2.optimization.contracts import OptimizationAgent
    from sagents.v2.optimization.principles import DIALOGUE_USER_PRINCIPLES, dialogue_user
    custom = OptimizationAgent(package=bundle('custom-user'), agent_id='assistant')
    default = optimizer(Runner())
    assert default.test_driver.package.resolved_manifest().agents['assistant'].instructions.inline == DIALOGUE_USER_PRINCIPLES
    explicit = AgentPackageOptimizer(runner=Runner(), evaluator=default.evaluator,
        tuner=default.tuner, test_driver=custom)
    text = explicit.test_driver.package.resolved_manifest().agents['assistant'].instructions.inline
    assert text.startswith(DIALOGUE_USER_PRINCIPLES)
    assert 'Do unit conversions. Never send messages.' in text
    assert dialogue_user(explicit.test_driver, preserve_instructions=True) == explicit.test_driver
    assert 'reference_answer' not in text


@pytest.mark.asyncio
@pytest.mark.parametrize('human', [False, True])
@pytest.mark.parametrize('continue_user,expected', [(True, 'turn_limit'), (False, 'user_finished')])
async def test_train_dev_and_human_scorers_receive_the_real_termination(human, continue_user, expected):
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner as Base, EarlyPassScorer
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from sagents.v2.optimization.contracts import OptimizationAgent
    class Script(Base):
        async def run(self, package, agent_id, content, ctx):
            payload = json.loads(content)
            if payload.get('response_schema', {}).get('title') == 'OptimizationDialogueReply':
                return OptimizationObservation(state='completed', output=json.dumps({
                    'can_continue': continue_user, 'message': 'Continue' if continue_user else '', 'rationale': 'Fixed fixture'}))
            return await super().run(package, agent_id, content, ctx)
    class Scorer(EarlyPassScorer):
        def __init__(self):
            super().__init__()
            self.reasons = []
        async def score(self, request):
            self.reasons.append(request.dialogue_stop_reason)
            assert request.conversation[-1]['stop_reason'] == expected
            return await super().score(request)
    runner, scorer = Script(), Scorer()
    if human:
        agent = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
        evaluator = IsolatedTestEvaluator(runner=runner, evaluator=agent, driver=agent,
            context=context(), goal='Conversions', scorer=scorer)
        await evaluator(bundle(), dialogues().cases[0])
    else:
        await optimizer(runner).optimize(bundle(), context=context(), goal='Conversions',
            suite=dialogues(), rounds=1, validation_case_count=1, grow_training=False,
            final_max_cases=0, scorer=scorer)
    assert scorer.reasons and set(scorer.reasons) == {expected}
