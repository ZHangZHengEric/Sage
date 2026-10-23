import json

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.evidence import training_evidence_files
from sagents.v2.optimization.execution_records import conversation_messages, visible_dialogue
from tests.sagents.v2.test_optimization_evidence import measured


def test_repeats_have_independent_simple_execution_and_assessment_files():
    files, index = training_evidence_files([measured('case', [0, 1])])
    case = json.loads(files['training-evidence/mixed/index.json'])[0]
    refs = case['trials']
    assert len(refs) == 2
    assert refs[0]['execution'] != refs[1]['execution']
    assert refs[0]['assessment'] != refs[1]['assessment']
    for ref in refs:
        messages = json.loads(files[ref['execution']])
        assert isinstance(messages, list)
        assert all(set(message) <= {'role', 'content', 'tool', 'arguments', 'timestamp', 'error'} for message in messages)
        assert set(json.loads(files[ref['assessment']])) == {'score', 'passed', 'reason'}
    assert not any(path.endswith('/execution.json') for path in files)


def test_duplicate_snapshots_removed_but_distinct_repeated_tool_actions_preserved():
    def row(identity, data):
        return {'run_id': 'run', 'item_id': identity, 'data': data}
    call = {'kind': 'tool_call', 'tool_name': 'lookup', 'tool_call_id': 'one', 'arguments': {'id': 1}}
    result = {'kind': 'tool_result', 'tool_call_id': 'one', 'content': [{'kind': 'text', 'text': 'PRIVATE TOOL DATA'}]}
    answer = {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'Visible answer'}]}
    items = [row('one', call), row('two', result), row('one', call), row('three', call), row('four', answer)]
    observation = OptimizationObservation(state='completed', evidence={'final_items': items, 'usage': 'omit'})
    history = [{'user': 'Visible question', 'target': observation.model_dump(mode='json')}]
    messages = conversation_messages(observation, conversation=history)
    assert len([message for message in messages if 'arguments' in message]) == 2
    dialogue = visible_dialogue(observation, history)
    assert dialogue == [{'role': 'user', 'content': 'Visible question'}, {'role': 'assistant', 'content': 'Visible answer'}]
    assert 'PRIVATE TOOL DATA' not in json.dumps(dialogue)
