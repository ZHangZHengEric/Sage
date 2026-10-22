"""Native diagnosis retains behavioral evidence without lifecycle replay bloat."""
import copy
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.diagnostics import execution_chunks, execution_entries


def item(identity, data):
    return {'item_id': identity, 'run_id': 'run', 'data': data}


def test_native_view_preserves_distinct_calls_revisions_failures_and_unknown_events():
    call = {'kind': 'tool_call', 'tool_call_id': 'call-1', 'tool_name': 'update', 'arguments': {'value': 7}}
    other = {**call, 'tool_call_id': 'call-2'}
    result = {'kind': 'tool_result', 'tool_call_id': 'call-1', 'content': [{'kind': 'text', 'text': 'actual result'}]}
    records = [item('call-1', call), item('result', result), item('call-2', other)]
    events = [
        {'type': 'checkpoint.committed', 'data': {'state': 'completed'}},
        {'type': 'step.completed', 'data': {'state': 'failed', 'error': {'code': 'tool.error', 'message': 'Actual error'}}},
        {'type': 'continuation.decided', 'data': {'attempt': 2, 'retry_at': 'later'}},
        {'type': 'custom.event', 'data': {'important': 'custom context'}},
        {'type': 'item.completed', 'data': {'item': records[1]}},
        {'type': 'item.completed', 'data': {'item': item('extra', {'kind': 'message', 'role': 'assistant', 'content': 'uncommitted'})}},
    ]
    observation = OptimizationObservation(state='completed', output='Done', evidence={
        'final_items': records, 'runtime_events': events, 'runtime_events_truncated': True,
        'generated_tool_audit': {'passed': False, 'failures': ['Actual audit failure']}})
    history = [{'user': 'Please update this', 'target': observation.model_dump(mode='json')}]
    original = copy.deepcopy(history)
    entries = execution_entries(observation, conversation=history)
    native = [entry['item'] for entry in entries if entry['kind'] == 'native_item']
    assert native == records
    assert len([e for e in entries if e['kind'] == 'target_output']) == 1
    text = json.dumps(entries)
    for value in ['Please update this', 'actual result', 'Actual error', 'custom context', 'uncommitted', 'Actual audit failure', 'later']:
        assert value in text
    assert any(e['kind'] == 'coverage_warning' for e in entries)
    assert any(e.get('omitted_lifecycle_notifications') == 2 for e in entries)
    assert history == original
    revised = observation.model_copy(update={'evidence': {**observation.evidence,
        'final_items': [item('result', {**result, 'error': 'corrected recorded status'})]}})
    combined = execution_entries(revised, conversation=history)
    assert len([e for e in combined if e['kind'] == 'native_item']) == 4


def test_non_native_execution_keeps_every_record_and_custom_json_output():
    value = OptimizationObservation(state='failed', output=json.dumps({'conversation': [{'tool': 'custom', 'result': 42}]}),
        evidence={'runtime_events': [{'type': 'custom', 'data': {'error': 'failure'}}], 'additional': 'context'})
    entries = execution_entries(value)
    assert entries == [{'kind': 'target_observation', **value.model_dump(mode='json')}]


def test_large_successful_lifecycle_envelopes_do_not_fragment_a_short_actual_dialogue():
    records = [item('message', {'kind': 'message', 'role': 'assistant', 'content': [{'kind': 'text', 'text': 'Result'}]})]
    observation = OptimizationObservation(state='completed', output='Result', evidence={
        'final_items': records,
        'runtime_events': [{'type': 'checkpoint.committed', 'data': {'state': 'completed'},
                            'routing_metadata': 'transport' * 2000} for _ in range(30)]})
    entries = execution_entries(observation)
    assert len(execution_chunks(entries)) == 1
    assert len(json.dumps(entries)) < 1500
    assert entries[1]['item'] == records[0]


def test_identical_payload_on_a_different_event_item_is_not_deduplicated():
    payload = {'kind': 'message', 'role': 'assistant', 'content': 'same content'}
    observation = OptimizationObservation(state='completed', output='same content', evidence={
        'final_items': [item('one', payload), {'data': payload}, {'data': payload}],
        'runtime_events': [{'type': 'item.completed', 'data': {'item': item('two', payload)}}]})
    view = execution_entries(observation)
    assert len([entry for entry in view if entry['kind'] == 'native_item']) == 3
    events = [entry for entry in view if entry['kind'] == 'native_runtime_event']
    assert events[0]['data']['item']['item_id'] == 'two'


async def _verify_diagnosis_policy_tracks_the_executed_package(mode):
    from tests.sagents.v2.test_optimization_diagnostics import DiagnosticRunner
    from tests.sagents.v2.test_package_optimizer import bundle, context, optimizer, suite
    from sagents.v2.optimization.contracts import OptimizationGrade

    class Capture(DiagnosticRunner):
        def __init__(self):
            super().__init__()
            self.proposals = [{'rationale': 'Reusable correction', 'instruction_guidance': 'guidance-1'}]
            self.policies = []
            self.executed = []
        async def run(self, package, agent_id, content, ctx):
            if package.manifest.metadata.id == 'test.target':
                self.executed.append(package.resolved_manifest().agents[agent_id].instructions.inline)
            elif package.manifest.metadata.id == 'test.evaluator':
                request = json.loads(content)
                if request['response_schema']['title'] == 'OptimizationDiagnosis':
                    self.policies.append(request['data']['policy'])
            return await super().run(package, agent_id, content, ctx)

    runner = Capture()
    async def score(case, observation):
        value = .4 if observation.output == 'base' else .8
        return OptimizationGrade(score=value, passed=value == 1, rationale='Fixed external authority')
    dataset = suite()
    if mode == 'dialogue':
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        @asynccontextmanager
        async def conversation(package, agent_id, ctx):
            async def send(content):
                return await runner.run(package, agent_id, content, ctx)
            yield SimpleNamespace(send=send)
        runner.conversation = conversation
        dataset = dataset.model_copy(update={'cases': tuple(c.model_copy(update={'mode': 'dialogue', 'max_turns': 1}) for c in dataset.cases)})
    result = await optimizer(runner).optimize(bundle(), context=context(), goal='Accuracy', suite=dataset,
        rounds=1, validation_case_count=1, grow_training=False, authoritative_grader=score)
    assert result.report.rounds[0].accepted
    assert runner.policies == runner.executed
    assert runner.policies[0] != runner.policies[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['single', 'dialogue'])
async def test_diagnosis_uses_candidate_instructions_instead_of_baseline(mode):
    await _verify_diagnosis_policy_tracks_the_executed_package(mode)
