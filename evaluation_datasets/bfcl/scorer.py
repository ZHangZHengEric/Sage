"""Official BFCL scorer, replayed from completed native tool records."""
from __future__ import annotations

import ast
import inspect
import json

from evaluation_datasets.bfcl import runtime
from evaluation_datasets._support import native_events, public_names
from sagents.v2.optimization.scoring import ScorerDescriptor

SCORER_CONTRACT = '''Pinned BFCL official multi_turn_checker and irrelevance checker own the
binary score. Every user turn must follow the exported official script verbatim.
Script drift is an invalid measurement, not an agent failure or a fallback score.
Replay recorded completed tool calls in independent official model and reference
backends. Compare state after each turn and cumulative execution responses using
official logic. No partial credit or final-answer LLM judging. Missing/invalid
native evidence raises an error. Reference answers are never target instructions.
This Sage user driver is not the upstream orchestrator; scores describe the
declared base/miss_param/long_context subset, not the full BFCL V4 overall score.'''
DESCRIPTOR = ScorerDescriptor(id='bfcl.official-multi-turn', name='BFCL official multi-turn',
    version='native-v1-' + '6ea57973c7a6097fd7c5915698c54c17c5b1b6c8', contract=SCORER_CONTRACT)


def score(request):
    reference = json.loads(request['case']['reference_answer'])
    if reference.get('format_version') != 'bfcl.reference/v1':
        raise ValueError('Unsupported BFCL reference format')
    selected = runtime.task(reference['task_id'])
    turns = request.get('conversation') or []
    script = ['\n'.join(m['content'] for m in turn if m['role'] == 'user') for turn in selected['question']]
    if [t.get('user') for t in turns] != script:
        return {'not_applicable_reason': 'BFCL user driver did not deliver the complete official script verbatim'}
    names = public_names('BFCL', [f['name'] for f in runtime.tools({'task_id': selected['id']})])
    decoded, seen = [], set()
    # Validate the complete record before reading individual, possibly cumulative turns.
    events = native_events(request)
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    outcomes = []
    for turn in turns:
        calls = []
        for event in native_events({'observation': turn['target']}):
            if event.get('kind') != 'tool_call' or event['tool_call_id'] in seen:
                continue
            seen.add(event['tool_call_id'])
            if event.get('tool_name') not in names:
                raise ValueError('Native execution used a tool outside the BFCL case')
            code = runtime.function_call(names[event['tool_name']], event['arguments'])
            calls.append(code)
            outcomes.append((code, results[event['tool_call_id']].get('error') is not None))
        decoded.append([calls] if calls else [])
    runtime.validate_outcomes(selected, outcomes)
    result = runtime.evaluate(selected, decoded)
    passed = result['valid']
    return {'grade': {'score': int(passed), 'passed': passed,
        'rationale': 'Replayed official BFCL per-turn state and execution-response evaluation'},
        'details': {'source': 'recomputed_native_execution', 'official_result': result}}


def fixture_request(*, success=True):
    """Real upstream task and reference calls, used only by offline import self-tests."""
    selected = runtime.task('multi_turn_base_0')
    from bfcl_eval.eval_checker.multi_turn_eval.func_source_code.gorilla_file_system import GorillaFileSystem
    turns = []
    count = 0
    for question, calls in zip(selected['question'], selected['ground_truth'], strict=True):
        items = [{'data': {'kind': 'message', 'role': 'user', 'content': [{'kind': 'text', 'text': question[0]['content']}]}}]
        for code in calls if success else []:
            expr = ast.parse(code, mode='eval').body
            name = expr.func.id
            signature = inspect.signature(getattr(GorillaFileSystem(), name))
            bound = signature.bind(*[ast.literal_eval(a) for a in expr.args],
                **{a.arg: ast.literal_eval(a.value) for a in expr.keywords})
            call_id = str(count)
            count += 1
            items.extend([{'data': {'kind': 'tool_call', 'tool_call_id': call_id,
                'tool_name': 'mcp_BFCL_' + name, 'arguments': dict(bound.arguments)}},
                {'data': {'kind': 'tool_result', 'tool_call_id': call_id, 'error': None, 'content': []}}])
        turns.append({'user': question[0]['content'], 'target': {'state': 'completed', 'evidence': {'final_items': items}}})
    return {'goal': 'Complete the official task', 'case': {'id': 'contract', 'input': turns[0]['user'],
        'rubric': 'Official BFCL reward', 'reference_answer': json.dumps({
            'format_version': 'bfcl.reference/v1', 'task_id': selected['id']})},
        'observation': turns[-1]['target'], 'conversation': turns}


SCORER_TEST_CASES = [{'request': fixture_request(success=success),
    'expected_score': int(success), 'expected_passed': success} for success in (False, True)]
