"""Regression coverage for world identity, stability gates and scheduling time."""
from contextlib import asynccontextmanager
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from sagents.v2.optimization.contracts import (
    OptimizationCase, OptimizationCaseResult, OptimizationEvaluation,
    OptimizationGrade, OptimizationObservation, OptimizationStoppingPolicy,
    case_prompt_identity,
)
from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.optimization.observer import HumanTestObserver, SharedCallLimitRunner
from sagents.v2.optimization.optimizer import AgentPackageOptimizer
from tests.sagents.v2.test_package_optimizer import bundle


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['alfworld', 'scienceworld'])
async def test_official_world_variations_do_not_invalidate_the_holdout(name):
    root = Path(__file__).resolve().parents[3] / 'evaluation_datasets' / name
    dataset = OptimizationDataset.model_validate_json((root / 'rsi.dataset.json').read_text())
    measured = []
    async def evaluate(package, case):
        measured.append(case.id)
        return {'grade': {'score': 1, 'passed': True, 'rationale': 'isolated test double'}}
    observer = HumanTestObserver(baseline=bundle(), suite=dataset.human_test_suite(),
        evaluate=evaluate, publish=lambda _: None)
    observer.observe({'event': 'suite_fixed', 'data': {'suite': dataset.optimization_suite().model_dump(mode='json')}})
    observer.observe({'event': 'evaluation_completed', 'data': {'round': 0, 'evaluation': {'cases': []}}})
    await observer.finish()
    record, = observer.records
    assert record['status'] == 'completed' and record['valid']
    assert record['scores']['test'] == 1
    assert set(measured) == {c.id for c in dataset.human_test_suite().cases}


def test_world_identity_is_not_just_a_case_id_or_json_key_order():
    original = OptimizationCase(id='train', input='Put the bowl away', rubric='Goal',
        environment_context={'task': 'one', 'seed': 2})
    renamed = original.model_copy(update={'id': 'renamed', 'split': 'test',
        'environment_context': {'seed': 2, 'task': 'one'}})
    different = renamed.model_copy(update={'environment_context': {'task': 'one', 'seed': 3}})
    assert case_prompt_identity(original) == case_prompt_identity(renamed)
    assert case_prompt_identity(original) != case_prompt_identity(different)


@pytest.mark.parametrize('audit,expected', [(None, True), ({'passed': True}, True), ({'passed': False}, False)])
def test_stable_success_and_selection_share_the_tool_audit_gate(audit, expected):
    cases = tuple(OptimizationCaseResult(
        case=OptimizationCase(id=split, input=split, rubric='fixed', split=split),
        observation=OptimizationObservation(state='completed',
            evidence={'generated_tool_audit': audit} if audit is not None else {}),
        grade=OptimizationGrade(score=1, passed=True, rationale='authoritative success'))
        for split in ('training', 'validation'))
    evaluation = OptimizationEvaluation(package_hash='original', cases=cases)
    assert AgentPackageOptimizer._at_target(evaluation, OptimizationStoppingPolicy()) is expected


@pytest.mark.asyncio
async def test_dialogue_latency_excludes_queueing_but_keeps_setup_and_execution(monkeypatch):
    import asyncio
    runner_module = importlib.import_module('sagents.v2.optimization.runner')
    observer_module = importlib.import_module('sagents.v2.optimization.observer')
    clock = [10.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(runner_module, 'time', timer)
    monkeypatch.setattr(observer_module, 'time', timer)
    opened = asyncio.Event()
    class Native:
        @asynccontextmanager
        async def conversation(self):
            started = clock[0]
            clock[0] += 2  # Materialization/setup belongs to the invocation.
            session = runner_module._NativeConversation(self, None, bundle(), 'assistant', None, started)
            opened.set()
            yield session
        async def authorize(self, *args):
            pass
        async def _send(self, app, agent, content, context, session, started, package, **kwargs):
            clock[0] += 3
            return OptimizationObservation(state='completed', elapsed_seconds=clock[0] - started,
                evidence={'session_id': 'fixture'})
    semaphore = asyncio.Semaphore(0)
    runner = SharedCallLimitRunner(Native(), semaphore)
    async def dispatch():
        async with runner.conversation() as conversation:
            first = await conversation.send('first')
            second = await conversation.send('second')
            return first, second
    pending = asyncio.create_task(dispatch())
    await opened.wait()
    clock[0] += 100  # Another independent workload occupies the shared slot.
    semaphore.release()
    first, second = await pending
    assert first.elapsed_seconds == 5
    assert second.elapsed_seconds == 3
    assert runner_module.OPTIMIZATION_QUEUE_WAIT.get() == 0
