"""Official answer normalization and write-task table hashes, from native tools."""
import json
from evaluation_datasets import _support
from evaluation_datasets.agentbench_db import runtime
from sagents.v2.optimization.scoring import ScorerDescriptor

SCORER_CONTRACT = '''AgentBench DB standard subset on managed MySQL 8.0. Replay canonical
completed native SQL statements and compare their actual outcomes. The first
commit_final_answer ends the episode. SELECT uses the pinned official answer
normalizer; INSERT/UPDATE/DELETE use the official actual-table hash comparison,
not the submitted prose. Binary grade. At most 50 SQL statements. Missing Docker,
connection errors and replay mismatches are measurement failures, not agent zeroes.
No external database credentials, trajectories or prefilled scores are accepted.
The two import tests cover official SELECT normalization without requiring Docker;
run the real MySQL preflight separately before any RSI evaluation.'''
DESCRIPTOR = ScorerDescriptor(id='agentbench-db.official-replay', name='AgentBench DB official replay',
    version='native-v1-d1e4a10db08c87075c78972e48ecc182be03e2d5', contract=SCORER_CONTRACT)


def score(request):
    ref = json.loads(request['case']['reference_answer'])
    if ref.get('format_version') != 'agentbench-db.reference/v1':
        raise ValueError('Unsupported DB reference format')
    context = {'task_id': ref['task_id']}
    runtime.task(context)
    names = _support.public_names('AgentBenchDB', [t['name'] for t in runtime.tools(context)])
    events = _support.native_events(request)
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    queries, expected, answers = [], [], None
    for e in events:
        if e.get('kind') != 'tool_call':
            continue
        if e['tool_name'] not in names or answers is not None:
            raise ValueError('Unsupported tool or execution after final commit')
        name, args = names[e['tool_name']], e['arguments']
        runtime.validate(name, args)
        result = results[e['tool_call_id']]
        if result.get('error'):
            raise ValueError('Rejected tool execution cannot count as successful SQL')
        text = _support.message_text(result)
        if name == 'execute_sql':
            queries.append(args['query'])
            expected.append(text)
        else:
            if text != runtime.COMMITTED:
                raise ValueError('Final commit result does not match actual tool behavior')
            answers = args['answers']
    passed = runtime.evaluate(context, queries, answers, expected)
    return {'grade': {'score': int(passed), 'passed': passed,
        'rationale': 'Recomputed using the official DB result processor'},
        'details': {'source': 'recomputed_native_execution', 'queries': len(queries)}}


SCORER_TEST_CASES = json.loads((runtime.ROOT / 'fixtures.json').read_text())
