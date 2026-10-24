"""Shared native replay for action environments; no model-supplied rewards."""
from __future__ import annotations
import json
from evaluation_datasets import _support


def evaluate(runtime, namespace, reference, request):
    if reference.get('format_version') != namespace.lower() + '.reference/v1':
        raise ValueError('Unsupported reference format')
    context = {'task_id': reference['task_id']}
    # Lookup prevents generated task text or caller-provided paths defining a new world.
    runtime.task(context)
    names = _support.public_names(namespace, [t['name'] for t in runtime.tools(context)])
    events = _support.native_events(request, allow_closed=True)
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    actions, expected = [], []
    terminal_reported, absorbed = False, 0
    for e in events:
        if e.get('kind') != 'tool_call':
            continue
        if e['tool_name'] not in names:
            if _support.native_skill_read(request, e, results[e['tool_call_id']]):
                continue
            raise ValueError('Only this benchmark MCP may be used')
        name, args = names[e['tool_name']], e['arguments']
        runtime.validate(name, args)
        result = results[e['tool_call_id']]
        if result.get('error'):
            raise ValueError('Rejected tool execution cannot be replayed as success')
        if name == 'step':
            if terminal_reported:
                absorbed += 1
            else:
                actions.append(args['action'])
        expected.append((len(actions), result))
        if getattr(runtime, 'ABSORBING_TERMINAL', False):
            reported = json.loads(_support.message_text(result))
            terminal_reported = terminal_reported or isinstance(reported, dict) and reported.get('done') is True
    snapshots, value = runtime.replay(context, actions)
    for index, result in expected:
        text = _support.message_text(result)
        # The MCP returns one JSON text block, using exactly this projection.
        if not text or json.loads(text) != snapshots[index]:
            raise ValueError('Native tool outcome differs from deterministic environment replay')
    return {'grade': {'score': value, 'passed': value == 1,
        'rationale': 'Recomputed in the pinned official environment'},
        'details': {'source': 'recomputed_native_execution', 'actions': len(actions),
                    **({'absorbed_step_calls': absorbed} if absorbed else {})}}


def tools(context=None):
    return [{'name': 'observe', 'description': 'Observe the current world without taking an action.',
        'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        {'name': 'step', 'description': 'Take one text action in the world.',
        'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
            'required': ['action'], 'additionalProperties': False}}]


def validate(name, args):
    if name == 'observe' and args == {}:
        return
    if name == 'step' and set(args) == {'action'} and isinstance(args['action'], str) and 0 < len(args['action']) <= 2000:
        return
    raise ValueError('Invalid action arguments')


def call(runtime, context, state, name, args):
    validate(name, args)
    actions = list(state['actions'])
    absorbing = getattr(runtime, 'ABSORBING_TERMINAL', False)
    terminal = state.get('_terminal_snapshot') if absorbing else None
    if terminal is None and absorbing and len(actions) >= getattr(runtime, 'LIMIT', float('inf')):
        # Upgrade a persisted terminal state before considering a 201st action.
        snapshots, _ = runtime.replay(context, actions)
        terminal = snapshots[-1] if snapshots[-1].get('done') is True else None
    if terminal is not None:
        return {**state, '_terminal_snapshot': terminal}, terminal, False
    if name == 'step':
        actions.append(args['action'])
    snapshots, _ = runtime.replay(context, actions)
    updated = {'actions': actions}
    if absorbing and snapshots[-1].get('done') is True:
        updated['_terminal_snapshot'] = snapshots[-1]
    return updated, snapshots[-1], False


def fixture_request(namespace, task_id, actions, snapshots):
    items = []
    for i, action in enumerate(actions):
        items.extend([{'item_id': f'c{i}', 'data': {'kind': 'tool_call', 'tool_call_id': str(i),
            'tool_name': f'mcp_{namespace}_step', 'arguments': {'action': action}}},
            {'item_id': f'r{i}', 'data': {'kind': 'tool_result', 'tool_call_id': str(i), 'error': None,
                'content': [{'kind': 'text', 'text': json.dumps(snapshots[i + 1], ensure_ascii=False)}]}}])
    items.append({'item_id': 'final', 'data': {'kind': 'message', 'role': 'assistant',
        'content': [{'kind': 'text', 'text': 'Done.'}]}})
    return {'goal': 'Complete the task', 'case': {'id': task_id, 'input': 'Complete the task',
        'rubric': 'Official environment reward', 'reference_answer': json.dumps({
            'format_version': namespace.lower() + '.reference/v1', 'task_id': task_id})},
        'observation': {'state': 'completed', 'evidence': {'final_items': items}}}
