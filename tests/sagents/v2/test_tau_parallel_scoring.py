"""Official replay accepts native parallel calls without changing reward rules."""
import copy
import itertools
import json

import pytest

from evaluation_datasets.tau_bench.runtime import activate
from evaluation_datasets.tau_bench.scorer import (
    ROOT, parallel_contract_request, recorded_messages, score,
)


def native_items(request):
    return request['observation']['evidence']['final_items']


def messages(request):
    activate()
    return recorded_messages(request, {
        'mcp_TauRetail_modify_user_address': 'modify_user_address',
        'mcp_TauRetail_get_user_details': 'get_user_details',
    })


def three_call_request(order):
    request = parallel_contract_request()
    user, first, second, second_result, first_result = native_items(request)
    db = json.loads((ROOT / 'data/tau2/domains/retail/db.json').read_text())
    user_id = second['data']['arguments']['user_id']
    read = {'data': {'kind': 'tool_call', 'tool_call_id': 'read',
        'tool_name': 'mcp_TauRetail_get_user_details', 'arguments': {'user_id': user_id}}}
    read_result = {'data': {'kind': 'tool_result', 'tool_call_id': 'read',
        'content': [{'kind': 'text', 'text': json.dumps(db['users'][user_id])}], 'error': None}}
    results = [first_result, second_result, read_result]
    native_items(request)[:] = [user, first, second, read, *(results[index] for index in order)]
    return request


@pytest.mark.parametrize('order', list(itertools.permutations(range(3))))
def test_parallel_result_permutations_keep_ids_arguments_results_and_official_reward(order):
    request = three_call_request(order)
    original = copy.deepcopy(request)
    converted = messages(request)
    assert [m.role for m in converted] == ['user', 'assistant', 'tool', 'tool', 'tool']
    calls = converted[1].tool_calls
    assert [c.id for c in calls] == ['update', 'update-second', 'read']
    assert [m.id for m in converted[2:]] == [c.id for c in calls]
    source_results = {i['data']['tool_call_id']: i['data'] for i in native_items(request)
                      if i['data']['kind'] == 'tool_result'}
    for call, result in zip(calls, converted[2:], strict=True):
        assert result.content == source_results[call.id]['content'][0]['text']
    assert score(request)['grade']['score'] == 1
    assert request == original


def test_parallel_normalization_does_not_turn_an_incorrect_database_state_into_a_pass():
    request = parallel_contract_request()
    reference = json.loads(request['case']['reference_answer'])
    # The execution updated two users, but this expected state only updates one.
    reference['evaluation_criteria']['actions'].pop()
    request['case']['reference_answer'] = json.dumps(reference)
    assert score(request)['grade']['score'] == 0


def test_sequential_batches_and_assistant_text_remain_in_their_original_turns():
    request = parallel_contract_request()
    user, first, second, second_result, first_result = native_items(request)
    text = {'data': {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'First update complete.'}]}}
    native_items(request)[:] = [user, first, first_result, text, second, second_result]
    converted = messages(request)
    assert [m.role for m in converted] == ['user', 'assistant', 'tool', 'assistant', 'assistant', 'tool']
    assert converted[3].content == 'First update complete.'
    assert [converted[i].tool_calls[0].id for i in (1, 4)] == ['update', 'update-second']
    assert score(request)['grade']['score'] == 1


def test_parallel_result_order_does_not_reorder_writes_to_the_same_user():
    request = parallel_contract_request()
    items = native_items(request)
    first_user = json.loads(items[-1]['data']['content'][0]['text'])
    arguments = {**items[1]['data']['arguments'], 'address1': 'Last issued update'}
    items[2]['data']['arguments'] = arguments
    items[3]['data']['content'][0]['text'] = json.dumps({**first_user,
        'address': {**first_user['address'], 'address1': arguments['address1']}})
    reference = json.loads(request['case']['reference_answer'])
    reference['evaluation_criteria']['actions'][1]['arguments'] = arguments
    request['case']['reference_answer'] = json.dumps(reference)
    # Completion order is reversed; replay must still use issuance order.
    assert score(request)['grade']['score'] == 1


def test_cumulative_native_observations_are_deduplicated_before_matching_parallel_results():
    request = three_call_request((2, 1, 0))
    items = native_items(request)
    for index, item in enumerate(items):
        item['item_id'] = f'item-{index}'
    first = {'state': 'completed', 'evidence': {'final_items': copy.deepcopy(items[:1])}}
    request['conversation'] = [{'target': first}, {'target': request['observation']}]
    converted = messages(request)
    assert len(converted) == 5
    assert score(request)['grade']['score'] == 1


@pytest.mark.parametrize('defect', ['missing', 'duplicate_result', 'duplicate_call', 'early_result', 'boundary'])
def test_ambiguous_or_incomplete_native_records_are_rejected_instead_of_fabricating_results(defect):
    request = parallel_contract_request()
    items = native_items(request)
    if defect == 'missing':
        items.pop()
    elif defect == 'duplicate_result':
        items.append(copy.deepcopy(items[-1]))
    elif defect == 'duplicate_call':
        items.insert(2, copy.deepcopy(items[1]))
    elif defect == 'early_result':
        items.insert(1, items.pop())
    else:
        items.insert(3, {'data': {'kind': 'message', 'role': 'user', 'content': [{'kind': 'text', 'text': 'Next user turn'}]}})
    with pytest.raises(ValueError, match='missing results|duplicate native tool'):
        messages(request)


def test_native_tool_error_and_unrelated_local_tool_records_are_preserved_or_filtered_correctly():
    request = parallel_contract_request()
    items = native_items(request)
    items[3]['data']['error'] = {'code': 'tool.failed'}
    items.insert(3, {'data': {'kind': 'tool_call', 'tool_call_id': 'local', 'tool_name': 'file_read', 'arguments': {'path': 'notes'}}})
    items.insert(4, {'data': {'kind': 'tool_result', 'tool_call_id': 'local', 'content': [{'kind': 'text', 'text': 'local output'}]}})
    converted = messages(request)
    assert [c.id for c in converted[1].tool_calls] == ['update', 'update-second']
    assert converted[-1].id == 'update-second' and converted[-1].error is True
    assert converted[-2].error is False
