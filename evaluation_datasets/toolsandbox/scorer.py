"""Rebuild the official world-state trajectory from native execution records."""
from __future__ import annotations

import json

from evaluation_datasets import _support
from evaluation_datasets.toolsandbox import runtime
from sagents.v2.optimization.scoring import ScorerDescriptor

SCORER_CONTRACT = '''The pinned official ToolSandbox milestone/minefield evaluator owns
the numeric similarity score in [0,1]. Pass requires a score of 1; lower similarity
is retained as partial credit. Replay canonical completed native tool calls and
user/assistant messages in a fresh official scenario. Do not trust prefilled scores
or caller-supplied state files. A minefield violation nullifies milestone similarity
using official logic. Time is frozen for both scenario construction and execution.
This adapter covers offline, unaugmented base scenarios only. Sage drives user
dialogue and has its own turn budget; this is not the upstream full leaderboard
or an exact reproduction of its user simulator. Do not invent unsupported
scenario references for newly generated training cases.'''
DESCRIPTOR = ScorerDescriptor(id='toolsandbox.official-milestones', name='ToolSandbox official milestones',
    version='native-v1-c8571d7854316d2e1c5f288e59fe1e34e53f6dd1', contract=SCORER_CONTRACT)


def score(request):
    reference = json.loads(request['case']['reference_answer'])
    if reference.get('format_version') != 'toolsandbox.reference/v1':
        raise ValueError('Unsupported ToolSandbox reference format')
    runtime.activate()
    name = reference['scenario']
    names = _support.public_names('ToolSandbox', [t['name'] for t in runtime.tools({'scenario': name})])
    events = _support.native_events(request)
    result = runtime.evaluate(name, events, names)
    value = result['similarity']
    return {'grade': {'score': value, 'passed': value == 1,
        'rationale': 'Recomputed official ToolSandbox milestone and minefield similarities'},
        'details': {'source': 'recomputed_native_execution', 'official_result': result}}


def fixture_request(success):
    items = [{'data': {'kind': 'message', 'role': 'user',
        'content': [{'kind': 'text', 'text': 'Turn off cellular'}]}}]
    if success:
        items.extend([{'data': {'kind': 'tool_call', 'tool_call_id': 'set',
            'tool_name': 'mcp_ToolSandbox_set_cellular_service_status', 'arguments': {'on': False}}},
            {'data': {'kind': 'tool_result', 'tool_call_id': 'set', 'content': [], 'error': None}}])
    items.append({'data': {'kind': 'message', 'role': 'assistant',
        'content': [{'kind': 'text', 'text': 'Cellular service is turned off' if success else 'I cannot help'}]}})
    return {'goal': 'Complete official offline task', 'case': {'id': 'contract', 'input': 'Turn off cellular',
        'rubric': 'Official milestones', 'reference_answer': json.dumps({
            'format_version': 'toolsandbox.reference/v1', 'scenario': 'cellular_off'})},
        'observation': {'state': 'completed', 'evidence': {'final_items': items}}}


SCORER_TEST_CASES = [{'request': fixture_request(value), 'expected_score': int(value),
    'expected_passed': value} for value in (False, True)]
