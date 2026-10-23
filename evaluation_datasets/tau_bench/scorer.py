"""Imported Python scorer: recompute the pinned official reward from native records.

No precomputed reward, trajectory path, MCP scoring tool or dedicated execution
host is required. Dataset references carry criteria; SAgents supplies recorded
messages/tool calls/results. Model judging is performed by the official evaluator inside this module.
"""
from __future__ import annotations

import json

from evaluation_datasets.tau_bench.runtime import ROOT, activate
from sagents.v2.optimization.scoring import ScorerDescriptor, ScoringRequest, ScoringResult
from sagents.v2.optimization.contracts import OptimizationGrade
from sagents.v2.tool.plugins.mcp import McpToolPlugin

SCORER_CONTRACT = """The pinned official evaluator is the sole numerical authority.
Reference format tau2.retail.reference/v1 supplies initial_state and evaluation_criteria.
Replay the native recorded official business calls in a fresh environment initialized
with initial_state. Separately replay reference actions to obtain expected state.
DB success is the official comparison of these states, not exact read-call order,
count or trace matching. Reference actions are evaluator-only expected outcomes,
not user permissions; the executing agent must still obtain required confirmations.
Null/empty natural-language assertions contribute success (1) under official logic.
Nonempty assertions use the exact official prompts and official JSON parsing.
Reward components are combined exactly by the task's reward_basis; action or
communication checks outside that basis are informational, not extra failure rules.
The official reward is binary; a score of 1 passes, 0 fails. No added partial credit.
Some policy-permitted alternate choices may fail a fixed benchmark's expected state;
this is the benchmark's declared criterion, not an undefined scoring mechanism.
Dialogue is controlled by the standard RSI user driver and turn limit; score the
complete recorded history available at each checkpoint. Conversation termination follows the standard case dialogue_completion setting;
a passing intermediate state reward must not truncate a user-completed dialogue. The scorer cannot invent or supply missing customer preferences.
Do not expose reference actions, dev questions or expected outcomes to the target,
user driver or tuner beyond authorized training evidence.
""".strip()

DESCRIPTOR = ScorerDescriptor(id='tau-bench.official-reward', name='τ-bench official reward',
    version='native-records-v1-fc0055dc4e0a316c3f83133267fbd6faaa770992', contract=SCORER_CONTRACT)


def text_content(blocks):
    text = ''.join(block.get('text', '') for block in blocks if block.get('kind') == 'text')
    if text:
        return text
    values = [block['value'] for block in blocks if block.get('kind') == 'json']
    return json.dumps(values[0], ensure_ascii=False) if len(values) == 1 else ''


def recorded_messages(request, tool_names):
    """Use canonical completed Run items, preserving actual turn/tool ordering."""
    from tau2.data_model.message import AssistantMessage, UserMessage, ToolMessage, ToolCall
    messages, seen, selected_calls = [], set(), set()
    turns = request.get('conversation') or [{'target': request['observation']}]
    for turn in turns:
        observation = turn.get('target') or turn.get('observation')
        if not isinstance(observation, dict):
            raise ValueError('conversation is missing a native execution record')
        items = observation.get('evidence', {}).get('final_items')
        if not isinstance(items, list) or not items:
            raise ValueError('scoring requires canonical native final_items; precomputed rewards are insufficient')
        for envelope in items:
            identity = envelope.get('item_id')
            if identity is not None:
                if identity in seen:
                    continue
                seen.add(identity)
            item = envelope.get('data', {})
            kind = item.get('kind')
            if kind == 'message' and item.get('role') in {'user', 'assistant'}:
                model = UserMessage if item['role'] == 'user' else AssistantMessage
                messages.append(model(role=item['role'], content=text_content(item.get('content', []))))
            elif kind == 'tool_call' and item.get('tool_name') in tool_names:
                selected_calls.add(item['tool_call_id'])
                messages.append(AssistantMessage(role='assistant', tool_calls=[ToolCall(
                    id=item['tool_call_id'], name=tool_names[item['tool_name']], arguments=item['arguments'])]))
            elif kind == 'tool_result' and item.get('tool_call_id') in selected_calls:
                messages.append(ToolMessage(role='tool', id=item['tool_call_id'],
                    content=text_content(item.get('content', [])), error=item.get('error') is not None))
    if not messages:
        raise ValueError('native execution has no supported recorded messages')
    return messages


def generate_official_assertion(*, model, messages, call_name=None, **kwargs):
    """Official prompts through a ready Sage ModelProvider; no API/SDK setup."""
    import asyncio
    from tau2.data_model.message import AssistantMessage
    from sagents.v2.contracts.common import new_id
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
    from sagents.v2.optimization.scorer_runtime import get_model_provider
    provider = get_model_provider()
    parameters = {'temperature': kwargs.get('temperature')}
    adjustments = []
    async def invoke():
        request = ModelRequest(request_id=new_id('official-assertion'), run_id='scorer',
            model_binding=provider.model_binding,
            messages=tuple(ModelMessage(role=m.role, content=(TextBlock(text=m.content or ''),)) for m in messages),
            **parameters)
        response = None
        async for event in provider.stream(request):
            if event.kind == ModelEventKind.COMPLETED:
                response = event.response
        if response is None or not response.text or response.tool_calls:
            raise ValueError('Official assertion model returned no completed text')
        return response
    try:
        response = asyncio.run(invoke())
    except SageV2Error as error:
        message = str(error).lower()
        if (parameters.get('temperature') is None or error.info.retryable
                or 'temperature' not in message or not any(word in message for word in ('invalid', 'unsupported', 'not supported'))):
            raise
        parameters.pop('temperature')
        adjustments.append('ModelProvider rejected official temperature; omitted temperature')
        response = asyncio.run(invoke())
    return AssistantMessage(role='assistant', content=response.text, raw_data={
        'scorer_model': provider.model_binding, 'scorer_protocol': 'sage-model-provider',
        'transport_adjustments': adjustments})


def score(request: dict) -> dict:
    reference_text = request['case'].get('reference_answer')
    if not reference_text:
        raise ValueError('official scoring requires the dataset reference_answer')
    reference = json.loads(reference_text)
    if reference.get('format_version') != 'tau2.retail.reference/v1':
        raise ValueError('unsupported official retail reference format')
    if request['observation']['state'] != 'completed':
        raise ValueError('official scoring requires a completed native execution')
    activate()
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.data_model.tasks import Task
    from tau2.domains.retail.environment import get_environment
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    import tau2.evaluator.evaluator_nl_assertions as nl
    environment = get_environment()
    namespace = reference.get('mcp_server', 'TauRetail')
    names = {McpToolPlugin._public_name(namespace, tool.name): tool.name for tool in environment.get_tools()}
    messages = recorded_messages(request, names)
    task = Task(id=reference['task_id'], user_scenario={'instructions': 'Scoring reference'},
        initial_state=reference.get('initial_state'), evaluation_criteria=reference['evaluation_criteria'])
    simulation = SimulationRun(id='native-scoring', task_id=task.id, start_time='native', end_time='native',
        duration=0, termination_reason=TerminationReason.USER_STOP, messages=messages)
    # Only model transport is adapted here. The pinned official evaluator owns
    # assertion prompts, parsing, DB replay, reward_basis and reward composition.
    original = nl.generate
    model_calls = []
    def generate(**kwargs):
        response = generate_official_assertion(**kwargs)
        if response.raw_data:
            model_calls.append(response.raw_data)
        return response
    nl.generate = generate
    try:
        reward = evaluate_simulation(simulation=simulation, task=task, evaluation_type=EvaluationType.ALL,
            solo_mode=False, domain='retail', strict_replay=True).model_dump(mode='json')
    finally:
        nl.generate = original
    grade = OptimizationGrade(score=reward['reward'], passed=reward['reward'] == 1,
        rationale='Recomputed official reward from native messages and tool execution records')
    return ScoringResult(grade=grade, details={'official_reward': reward,
        'source': 'recomputed_native_execution', 'recorded_messages': len(messages),
        'model_calls': model_calls}).model_dump(mode='json')


class TauBenchScorer:
    """In-process use is for tests; Desktop imports score() in an isolated worker."""
    descriptor = DESCRIPTOR

    async def score(self, request: ScoringRequest) -> ScoringResult:
        import asyncio
        return ScoringResult.model_validate(await asyncio.to_thread(score, request.model_dump(mode='json')))


def contract_request(executed):
    db = json.loads((ROOT / 'data/tau2/domains/retail/db.json').read_text())
    user_id, user = next(iter(db['users'].items()))
    address = {**user['address'], 'address1': 'Contract test address'}
    arguments = {'user_id': user_id, **address}
    expected = {**user, 'address': address}
    reference = {'format_version': 'tau2.retail.reference/v1', 'task_id': 'contract',
        'initial_state': None, 'evaluation_criteria': {'actions': [{'action_id': 'address',
            'name': 'modify_user_address', 'arguments': arguments}], 'reward_basis': ['DB']}}
    items = [{'data': {'kind': 'message', 'role': 'user', 'content': [{'kind': 'text', 'text': 'Update the address.'}]}}]
    if executed:
        items.extend([{'data': {'kind': 'tool_call', 'tool_call_id': 'update',
            'tool_name': 'mcp_TauRetail_modify_user_address', 'arguments': arguments}},
            {'data': {'kind': 'tool_result', 'tool_call_id': 'update', 'error': None,
                'content': [{'kind': 'text', 'text': json.dumps(expected)}]}}])
    return {'goal': 'Complete authorized address update', 'case': {'id': 'contract', 'input': 'Update address',
        'rubric': 'Official database outcome', 'reference_answer': json.dumps(reference)},
        'observation': {'state': 'completed', 'evidence': {'final_items': items}}}


SCORER_TEST_CASES = [
    {'request': contract_request(False), 'expected_score': 0, 'expected_passed': False},
    {'request': contract_request(True), 'expected_score': 1, 'expected_passed': True},
]


# Exercise the official NL prompt/parsing/reward path without network access.
for met in (False, True):
    import copy
    request = copy.deepcopy(contract_request(False))
    reference = json.loads(request['case']['reference_answer'])
    reference['evaluation_criteria'] = {'actions': [], 'reward_basis': ['DB', 'NL_ASSERTION'],
        'nl_assertions': ['The assistant offered to help.']}
    request['case']['reference_answer'] = json.dumps(reference)
    request['observation']['evidence']['final_items'].append({'data': {'kind': 'message', 'role': 'assistant',
        'content': [{'kind': 'text', 'text': 'I can help.' if met else 'I will not help.'}]}})
    SCORER_TEST_CASES.append({'request': request, 'model_responses': [{'response_id': 'fixture-assertion',
        'text': json.dumps({'results': [{'expectedOutcome': 'The assistant offered to help.',
            'reasoning': 'Offline official parser fixture', 'metExpectation': met}]}), 'finish_reason': 'stop'}],
        'expected_score': int(met), 'expected_passed': met})
