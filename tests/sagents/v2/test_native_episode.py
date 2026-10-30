from copy import deepcopy

import pytest

from sagents.v2.optimization.contracts import OptimizationCase, OptimizationObservation
from sagents.v2.optimization.native_episode import close_single_turn_episode, evaluation_episode_finished


def guarded_case():
    return OptimizationCase(id='task', input='Complete the fixed task', rubric='Official task goal')


@pytest.mark.asyncio
async def test_native_conversation_attests_default_workspace_for_each_run(tmp_path):
    import time
    from sagents.v2.optimization.runner import _NativeConversation
    from tests.sagents.v2.test_package_optimizer import bundle, context
    class Runner:
        calls = 0
        async def authorize(self, *args):
            pass
        async def _send(self, *args, **kwargs):
            self.calls += 1
            return OptimizationObservation(state='completed',output='{}',
                evidence={'session_id':'session','run_id':f'run-{self.calls}'})
    conversation = _NativeConversation(Runner(),None,bundle(),'assistant',context(),time.monotonic(),workspace=tmp_path,
        execution_workspace=tmp_path)
    for i in (1, 2):
        observation = await conversation.send('A task')
        info = observation.evidence['workspace_attestation']
        assert info['protocol'] == 'sage.rsi.workspace/v1'
        assert info['run_id'] == observation.evidence['run_id'] == f'run-{i}'
        assert tmp_path.resolve().as_posix() in info['roots']


def guarded_execution(*, canonical=False):
    call = {'item_id': 'call-item', 'run_id': 'run', 'step_id': 'step', 'status': 'completed',
            'data': {'kind': 'tool_call', 'tool_call_id': 'call', 'tool_name': 'mcp_world_step',
                     'arguments': {'action': 'look'}}}
    result = {'item_id': 'result-item', 'run_id': 'run', 'step_id': 'step', 'status': 'completed',
              'data': {'kind': 'tool_result', 'tool_call_id': 'call',
                       'content': [{'kind': 'text', 'text': 'Task remains incomplete'}],
                       'metadata': {'mcp_result_received': True}}}
    events = [
        {'type': 'tool.call.proposed', 'run_id': 'run', 'step_id': 'step', 'run_sequence': 1,
         'data': {'tool_call_id': 'call', 'tool_name': 'mcp_world_step', 'arguments': {'action': 'look'},
                  'operation_id': 'operation'}},
        {'type': 'tool.call.succeeded', 'run_id': 'run', 'step_id': 'step', 'run_sequence': 4,
         'data': {'tool_call_id': 'call', 'operation_id': 'operation', 'result_item_id': 'result-item',
                  'state': 'completed'}},
        {'type': 'interaction.requested', 'run_id': 'run', 'run_sequence': 5,
         'data': {'interaction_id': 'interaction', 'interaction_type': 'user_input',
                  'allowed_decisions': ['submit', 'cancel'], 'payload': {'reason_code': 'loop.repeated_pattern'}}},
        {'type': 'run.suspended', 'run_id': 'run', 'run_sequence': 6, 'data': {'reason': 'input_required'}},
    ]
    evidence = {'run_id': 'run', 'state': 'suspended', 'runtime_events_truncated': False,
                'suspension': {'run_id': 'run', 'interaction_id': 'interaction', 'reason': 'input_required'},
                'runtime_events': events}
    if canonical:
        evidence['final_items'] = [call, result]
    else:
        events[1:1] = [{'type': 'item.completed', 'run_id': 'run', 'run_sequence': index,
                        'data': {'item': item}} for index, item in enumerate([call, result], start=2)]
    return OptimizationObservation(state='suspended', output='', evidence=evidence)


def rejected_native_execution():
    original = guarded_execution(canonical=True)
    e = deepcopy(original.evidence)
    args = {'file_path':'index.html','operations':[]}
    error = {'code':'tool.file_update_not_applied','metadata':{'side_effect_state':'not_applied'}}
    e['final_items'][0]['data'].update(tool_name='file_update', arguments=args)
    e['final_items'][1].update(status='failed')
    e['final_items'][1]['data'].update(error=error, metadata={})
    e['runtime_events'][0]['data'].update(tool_name='file_update',arguments=args)
    e['runtime_events'][1]['type'] = 'tool.call.failed'
    e['runtime_events'][1]['data'].update(state='failed',error=deepcopy(error))
    return original.model_copy(update={'evidence':e,'output':'A recorded artifact'})


def test_loop_prefix_accepts_only_proven_not_applied_native_rejections():
    observation = rejected_native_execution()
    closed = close_single_turn_episode(observation, guarded_case())
    assert closed is not None and closed.state == 'suspended'
    assert closed.evidence['episode_termination']['rejected_not_applied_calls'] == 1


@pytest.mark.parametrize('defect', ['unknown_effect','missing_receipt','changed_error','external_tool'])
def test_rejected_loop_prefix_cannot_hide_uncertain_or_external_effects(defect):
    observation = rejected_native_execution()
    e = deepcopy(observation.evidence)
    if defect == 'unknown_effect':
        e['final_items'][1]['data']['error']['metadata']['side_effect_state'] = 'unknown'
    elif defect == 'missing_receipt':
        e['runtime_events'].pop(1)
    elif defect == 'changed_error':
        e['runtime_events'][1]['data']['error']['code'] = 'different'
    else:
        e['final_items'][0]['data']['tool_name'] = e['runtime_events'][0]['data']['tool_name'] = 'mcp_world_step'
    assert close_single_turn_episode(observation.model_copy(update={'evidence':e}), guarded_case()) is None


@pytest.mark.asyncio
async def test_pairwise_loop_limit_is_both_failed_without_fabricating_run_success():
    from sagents.v2.optimization.pairwise import PairwiseEvaluator
    async def judge(data, case):
        return {'winner':'tie','rationale':'Same rendered result'}
    engine = PairwiseEvaluator(binding='closed-prefix',judge=judge)
    observation = rejected_native_execution()
    await engine.grade(guarded_case(),observation,trial=1,is_reference=True)
    grade = await engine.grade(guarded_case(),observation,trial=1)
    assert grade.score == 0
    assert grade.scorer_details["pairwise"]["outcome"] == "both_failed"
    assert observation.state == 'suspended'


def test_website_can_replay_verified_loop_prefix_but_not_a_forged_closure():
    from evaluation_datasets.web_design.workspace import replay
    original = guarded_execution(canonical=True)
    e = deepcopy(original.evidence)
    args = {'file_path':'index.html','content':'<h1>Artifact</h1>','mode':'overwrite'}
    e['final_items'][0]['data'].update(tool_name='file_write',arguments=args)
    e['runtime_events'][0]['data'].update(tool_name='file_write',arguments=args)
    e['final_items'][1]['data'].update(content=[{'kind':'json','value':{
        'status':'success','file_path':'index.html','mode':'overwrite'}}],metadata={})
    request = {'case':guarded_case().model_dump(mode='json'),
        'observation':original.model_copy(update={'evidence':e}).model_dump(mode='json')}
    assert replay(request)[0]['index.html'] == '<h1>Artifact</h1>'
    request['observation']['evidence']['runtime_events'] = []
    with pytest.raises(ValueError,match='verified closed'):
        replay(request)


@pytest.mark.asyncio
async def test_failed_human_execution_is_archived_separately_from_completed_measurements(tmp_path):
    import json
    from contextlib import asynccontextmanager
    from pathlib import Path
    from sagents.v2.optimization.observer import IsolatedTestEvaluator, HumanTestExecutionFailure
    from tests.sagents.v2.test_package_optimizer import Runner, optimizer, bundle, context
    original = guarded_execution(canonical=True)
    evidence = deepcopy(original.evidence)
    evidence['runtime_events'][2]['data']['payload']['reason_code'] = 'user.clarification'
    observation = original.model_copy(update={'evidence':evidence})
    class Sessions:
        @asynccontextmanager
        async def conversation(self, *args):
            class Session:
                async def send(self, content):
                    return observation
            yield Session()
    roles = optimizer(Runner())
    evaluator = IsolatedTestEvaluator(runner=Sessions(),evaluator=roles.evaluator,driver=roles.test_driver,
        context=context(),goal='Fixed task',evidence_directory=tmp_path,checkpoint_binding_id='frozen')
    with pytest.raises(HumanTestExecutionFailure) as caught:
        await evaluator(bundle(),guarded_case())
    archive = Path(caught.value.rsi_failure_metadata['evidence_archive'])
    payload = json.loads(archive.read_text())['payload']
    assert payload['conversation'][0]['target']['state'] == 'suspended'
    assert payload['grade'] is None
    assert not (tmp_path/'.phase-checkpoints').exists()


@pytest.mark.parametrize('canonical', [False, True])
def test_closed_prefix_keeps_native_state_and_does_not_infer_success(canonical):
    original = guarded_execution(canonical=canonical)
    before = original.model_dump(mode='json')
    closed = close_single_turn_episode(original, guarded_case())
    assert closed.state == closed.evidence['state'] == 'suspended'
    assert closed.evidence['episode_termination']['native_state'] == 'suspended'
    assert closed.evidence['episode_termination']['tool_call_count'] == 1
    assert len(closed.evidence['final_items']) == 2
    assert original.model_dump(mode='json') == before
    assert close_single_turn_episode(closed, guarded_case()) == closed
    assert evaluation_episode_finished(closed, guarded_case())


@pytest.mark.parametrize('defect', ['dialogue', 'transport', 'truncated', 'missing_coverage', 'question',
    'approval', 'wrong_interaction', 'missing_receipt', 'operation', 'step', 'result', 'tool_error',
    'mcp_unconfirmed', 'pending_call', 'unbound_item', 'reverse_receipt', 'malformed', 'forged_label'])
def test_unverified_suspensions_never_become_finished_episodes(defect):
    original, case = guarded_execution(canonical=True), guarded_case()
    evidence = deepcopy(original.evidence)
    events = evidence['runtime_events']
    if defect == 'dialogue':
        case = case.model_copy(update={'mode': 'dialogue', 'max_turns': 3})
    elif defect == 'transport':
        evidence['error'] = {'code': 'model.timeout'}
    elif defect == 'truncated':
        evidence['runtime_events_truncated'] = True
    elif defect == 'missing_coverage':
        evidence.pop('runtime_events_truncated')
    elif defect == 'question':
        events[2]['data']['payload']['reason_code'] = 'user.clarification'
    elif defect == 'approval':
        evidence['suspension']['reason'] = 'approval_required'
    elif defect == 'wrong_interaction':
        evidence['suspension']['interaction_id'] = 'different'
    elif defect == 'missing_receipt':
        events.pop(1)
    elif defect == 'operation':
        events[1]['data']['operation_id'] = 'different'
    elif defect == 'step':
        events[1]['step_id'] = 'different'
    elif defect == 'result':
        events[1]['data']['result_item_id'] = 'different'
    elif defect == 'tool_error':
        evidence['final_items'][1]['data']['error'] = {'code': 'failed'}
    elif defect == 'mcp_unconfirmed':
        evidence['final_items'][1]['data']['metadata'].clear()
    elif defect == 'pending_call':
        events.append({**deepcopy(events[0]), 'data': {**events[0]['data'], 'tool_call_id': 'pending'}})
    elif defect == 'unbound_item':
        events.append({'type': 'item.completed', 'run_id': 'run', 'data': {'item': {
            **deepcopy(evidence['final_items'][0]), 'item_id': 'extra'}}})
    elif defect == 'reverse_receipt':
        events[1]['run_sequence'] = 0
    elif defect == 'malformed':
        evidence['final_items'] = [None]
    else:
        evidence['runtime_events'] = []
        evidence['episode_termination'] = {'protocol': 'sage.rsi.single-turn-episode-closure/v1',
                                          'episode_state': 'closed'}
    observation = original.model_copy(update={'evidence': evidence})
    assert close_single_turn_episode(observation, case) is None
    assert not evaluation_episode_finished(observation, case)


@pytest.mark.asyncio
async def test_human_checkpoint_scores_closed_prefix_without_repeating_target():
    from contextlib import asynccontextmanager
    from sagents.v2.optimization.observer import IsolatedTestEvaluator, SharedCallLimitRunner, SharedCallPool
    from sagents.v2.optimization.contracts import OptimizationGrade
    from tests.sagents.v2.test_package_optimizer import optimizer, Runner, bundle, context
    sends = []

    class Sessions:
        @asynccontextmanager
        async def conversation(self, *args):
            class Session:
                async def send(self, content):
                    sends.append(content)
                    return guarded_execution(canonical=True)
            yield Session()

    class Evaluator(IsolatedTestEvaluator):
        async def _grade_execution(self, package, case, observation, history):
            assert observation.state == history[0]['target']['state'] == 'suspended'
            assert observation.evidence['episode_termination']['episode_state'] == 'closed'
            return OptimizationGrade(score=0, passed=False, rationale='Fixed task remains incomplete')

        async def _finish_measurement(self, package, case, observation, history, grade):
            return {'grade': grade.model_dump(mode='json'), 'conversation': history}

    roles = optimizer(Runner())
    evaluator = Evaluator(runner=SharedCallLimitRunner(Sessions(), SharedCallPool(1)),
        evaluator=roles.evaluator, driver=roles.test_driver, context=context(), goal='Fixed task')
    result = await evaluator(bundle(), guarded_case())
    assert len(sends) == 1
    assert result['grade']['score'] == 0
    assert result['conversation'][0]['target']['state'] == 'suspended'


@pytest.mark.asyncio
async def test_optimizer_counts_native_loop_limit_as_case_failure():
    import json
    from sagents.v2.optimization.contracts import OptimizationSuite
    from tests.sagents.v2.test_package_optimizer import Runner, optimizer, bundle, context

    class GuardedRunner(Runner):
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.target':
                return guarded_execution(canonical=True)
            if package.manifest.metadata.id == 'test.evaluator':
                data = json.loads(content)['data']
                assert data['observation']['state'] == 'suspended'
                assert data['observation']['evidence']['episode_termination']['episode_state'] == 'closed'
                return OptimizationObservation(state='completed', output=json.dumps({
                    'score': 0, 'passed': False, 'rationale': 'Fixed goal was not completed'}))
            return await super().run(package, agent_id, content, ctx)

    result = await optimizer(GuardedRunner()).optimize(bundle(), context=context(), goal='Fixed task',
        rounds=1, validation_case_count=None, final_max_cases=0, suite=OptimizationSuite(cases=(guarded_case(),
            guarded_case().model_copy(update={'id': 'second', 'input': 'A separate fixed task', 'split': 'validation'}))))
    observed = result.report.baseline.cases[0]
    assert observed.observation.state == 'suspended'
    assert observed.grade.rationale == 'Target execution failed: loop.repeated_pattern'


def test_adaptive_selection_uses_score_of_valid_closed_episode():
    from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationEvaluation, OptimizationGrade
    from sagents.v2.optimization.optimizer import AgentPackageOptimizer
    case = guarded_case()
    def evaluation(score):
        return OptimizationEvaluation(package_hash='package', cases=tuple(OptimizationCaseResult(
            case=current, observation=close_single_turn_episode(guarded_execution(canonical=True), current),
            grade=OptimizationGrade(score=score, passed=False, rationale='Fixed rubric'), objective_score=score)
            for current in (case, case.model_copy(update={'id': 'dev', 'split': 'validation'}))))
    accepted, reason = AgentPackageOptimizer._select_adaptive(evaluation(.1), evaluation(.2), .01)
    assert accepted, reason
    assert not AgentPackageOptimizer._at_target(evaluation(.2), type('Stopping', (), {'target_score': 1})())


@pytest.mark.parametrize('official_score', [0, 1])
def test_official_replay_accepts_native_guard_and_alone_determines_reward(official_score):
    import json
    from evaluation_datasets import _interactive
    from sagents.v2.tool.plugins.mcp import McpToolPlugin
    observation = guarded_execution(canonical=True)
    evidence = observation.evidence
    name = McpToolPlugin._public_name('World', 'step')
    evidence['final_items'][0]['data']['tool_name'] = name
    evidence['runtime_events'][0]['data']['tool_name'] = name
    snapshot = {'done': bool(official_score)}
    evidence['final_items'][1]['data']['content'][0]['text'] = json.dumps(snapshot)
    request = {'case': guarded_case().model_dump(mode='json'), 'observation': observation.model_dump(mode='json')}
    before = deepcopy(request)

    class World:
        task = staticmethod(lambda context: context)
        tools = staticmethod(_interactive.tools)
        validate = staticmethod(_interactive.validate)

        @staticmethod
        def replay(context, actions):
            assert actions == ['look']
            return [{}, snapshot], official_score

    scored = _interactive.evaluate(World, 'World', {'format_version': 'world.reference/v1', 'task_id': 'task'}, request)
    assert scored['grade']['score'] == official_score
    assert scored['details']['actions'] == 1
    assert request == before
    evidence['runtime_events'].pop(1)
    request['observation'] = observation.model_dump(mode='json')
    with pytest.raises(ValueError, match='native observations'):
        _interactive.evaluate(World, 'World', {'format_version': 'world.reference/v1', 'task_id': 'task'}, request)


@pytest.mark.asyncio
@pytest.mark.parametrize('byte_limit', [2097152, 1])
async def test_native_runner_captures_suspended_items_and_fails_closed_on_truncation(byte_limit):
    import time
    from types import SimpleNamespace
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.optimization.runner import IsolatedOptimizationRunner
    from tests.sagents.v2.test_package_optimizer import bundle, context
    original = guarded_execution()

    def namespace(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{key: namespace(v) for key, v in value.items()})
        if isinstance(value, list):
            return [namespace(v) for v in value]
        return value

    events = []
    for row in original.evidence['runtime_events']:
        row = deepcopy(row)
        kind = ('item' if row['type'] == 'item.completed' else 'tool'
                if row['type'].startswith('tool.') else 'interaction'
                if row['type'].startswith('interaction.') else 'run')
        row['data']['kind'] = kind
        if kind == 'run':
            row['data']['error'] = None
        event = namespace(row)
        event.model_dump = lambda mode, row=row: deepcopy(row)
        if kind == 'item':
            event.data.item.model_dump = lambda mode, row=row: deepcopy(row['data']['item'])
        events.append(event)

    class Store:
        async def read_events(self, run_id, *, after_sequence, limit):
            return [event for event in events if event.run_sequence > after_sequence][:limit]

        async def get_suspension(self, identity):
            return SimpleNamespace(model_dump=lambda mode: deepcopy(original.evidence['suspension']))

        async def get_run_result(self, identity):
            pytest.fail('A suspended run has no terminal RunResult')

    class Stream:
        async def wait(self):
            return SimpleNamespace(state=RunState.SUSPENDED, run_id='run', suspension_id='suspension',
                last_run_sequence=6, model_dump=lambda mode: {
                    'run_id': 'run', 'session_id': 'session', 'state': 'suspended', 'last_run_sequence': 6})

        async def detach(self):
            pass

    class Agent:
        runtime = SimpleNamespace(session_store=Store())

        async def run_stream(self, *args, **kwargs):
            return Stream()

    package = bundle()
    app = SimpleNamespace(entrypoint=Agent, loaded_agents=[SimpleNamespace(
        package_id=package.manifest.metadata.id, id='assistant', composition_hash='hash')])
    runner = IsolatedOptimizationRunner(builder_factory=None, authorize=None, max_evidence_bytes=byte_limit)
    observation = await runner._send(app, 'assistant', 'task', context(), None, time.monotonic(), package)
    assert observation.state == 'suspended'
    if byte_limit == 1:
        assert observation.evidence['runtime_events_truncated']
        assert close_single_turn_episode(observation, guarded_case()) is None
    else:
        assert len(observation.evidence['final_items']) == 2
        assert not any(event['type'] == 'item.completed' for event in observation.evidence['runtime_events'])
        assert close_single_turn_episode(observation, guarded_case()) is not None
