"""Official scoring uses real termination and transaction ordering receipts."""
import copy
import json

import pytest


def test_tau_truncated_dialogue_receives_official_zero():
    from evaluation_datasets.tau_bench.scorer import contract_request, score
    request = contract_request(True)
    request['observation']['evidence']['dialogue_stop_reason'] = 'turn_limit'
    request['case'].update(mode='dialogue', dialogue_completion='user', max_turns=1)
    assert score(request)['grade']['score'] == 0
    request['dialogue_stop_reason'] = 'user_finished'
    assert score(request)['grade']['score'] == 1
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.data_model.tasks import Task
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    simulation = SimulationRun(id='offline', task_id='offline', start_time='start', end_time='end',
        duration=0, termination_reason=TerminationReason.MAX_STEPS, messages=[])
    reward = evaluate_simulation(simulation=simulation, task=Task(id='offline',
        user_scenario={'instructions': 'Offline'}), domain='retail',
        evaluation_type=EvaluationType.ALL, solo_mode=False)
    assert reward.reward == 0


def test_parallel_writes_replay_the_actual_commit_order(tmp_path):
    from evaluation_datasets.tau_bench.scorer import contract_request, score
    from evaluation_datasets.tau_bench.mcp_server import RetailState
    request = contract_request(True)
    items = request['observation']['evidence']['final_items']
    first = copy.deepcopy(items[1])
    second = copy.deepcopy(first)
    second['data']['tool_call_id'] = 'second'
    second['data']['arguments']['address1'] = 'Second issued'
    state = RetailState(tmp_path / 'retail.sqlite3')
    name = 'modify_user_address'
    # Independent MCP connections can acquire SQLite's lock in reverse issue order.
    second_result, second_receipt = state.call(name, second['data']['arguments'], with_receipt=True)
    first_result, first_receipt = state.call(name, first['data']['arguments'], with_receipt=True)
    def result(call, value, receipt):
        return {'data': {'kind': 'tool_result', 'tool_call_id': call['data']['tool_call_id'],
            'metadata': {'mcp_meta': {'sage.rsi.execution': receipt}},
            'error': None, 'content': [{'kind': 'text', 'text': json.dumps(value)}]}}
    items[:] = [items[0], first, second, result(second, second_result, second_receipt), result(first, first_result, first_receipt)]
    reference = json.loads(request['case']['reference_answer'])
    action = reference['evaluation_criteria']['actions'][0]
    reference['evaluation_criteria']['actions'] = [
        {**action, 'action_id': 'second', 'arguments': second['data']['arguments']}, action]
    request['case']['reference_answer'] = json.dumps(reference)
    actual = state.call('get_user_details', {'user_id': first['data']['arguments']['user_id']})
    assert actual['address']['address1'] == first['data']['arguments']['address1']
    assert score(request)['grade']['score'] == 1  # Receipts preserve the actual correct final state.
    items[1:3] = [second, first]  # Replay the actual commit order instead.
    assert score(request)['grade']['score'] == 1


@pytest.mark.parametrize('receipt', [None, {'protocol': 'wrong', 'sequence': 1},
    {'protocol': 'sage.rsi.execution-order/v1', 'sequence': True}])
def test_mixed_or_malformed_receipts_are_rejected(receipt):
    from evaluation_datasets.tau_bench.scorer import parallel_contract_request, score
    request = parallel_contract_request()
    items = request['observation']['evidence']['final_items']
    items[-1]['data']['metadata'] = {'mcp_meta': {'sage.rsi.execution': {
        'protocol': 'sage.rsi.execution-order/v1', 'sequence': 1}}}
    if receipt is not None:
        items[-2]['data']['metadata'] = {'mcp_meta': {'sage.rsi.execution': receipt}}
    with pytest.raises(ValueError, match='execution-order'):
        score(request)


def test_failed_operations_have_a_receipt_without_committing_state(tmp_path):
    from evaluation_datasets.tau_bench.runtime import activate
    from evaluation_datasets.tau_bench.mcp_server import RetailState
    activate()
    state = RetailState(tmp_path / 'retail.sqlite3')
    with pytest.raises(Exception) as caught:
        state.call('get_user_details', {'user_id': 'does-not-exist'}, with_receipt=True)
    receipt = caught.value.rsi_execution_receipt
    assert receipt['sequence'] == 1
    value, next_receipt = state.call('calculate', {'expression': '1+1'}, with_receipt=True)
    assert next_receipt['sequence'] == 2
    assert str(value) in {'2', '2.0'}


def test_legacy_host_request_keeps_its_existing_result_with_an_explicit_marker():
    from evaluation_datasets.tau_bench.scorer import contract_request, score
    request = contract_request(True)
    request['case'].update(mode='dialogue', dialogue_completion='user')
    legacy = score(request)
    assert legacy['grade']['score'] == 1
    assert legacy['details']['termination_reason_source'] == 'legacy_assumed_user_stop'
    request['dialogue_stop_reason'] = 'turn_limit'
    current = score(request)
    assert current['grade']['score'] == 0
    assert current['details']['termination_reason'] == 'max_steps'
    assert current['details']['termination_reason_source'] == 'host'


@pytest.mark.parametrize('typed', [True, False])
def test_mcp_receipts_are_preserved_without_changing_business_content(typed):
    from mcp.types import CallToolResult, TextContent
    from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolCall
    receipt = {'protocol': 'sage.rsi.execution-order/v1', 'sequence': 3}
    response = CallToolResult(content=[TextContent(type='text', text='Original business result')],
        _meta={'sage.rsi.execution': receipt})
    if not typed:
        response = response.model_dump(mode='json', by_alias=True)
    server = McpServerConfig(name='receipt-test', protocol='stdio', command='not-executed')
    plugin = McpToolPlugin((server,))
    call = ToolCall(tool_call_id='call', operation_id='op', idempotency_key='key',
        owner_run_id='offline', tool_name='mcp_receipt_test_read', arguments={})
    result = plugin._project_result(call, server, 'read', response)
    assert result.metadata['mcp_meta']['sage.rsi.execution'] == receipt
    assert len(result.content) == 1 and result.content[0].text == 'Original business result'
