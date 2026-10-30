"""Close unattended single-turn episodes without changing native Run state.

Only typed native loop guards with complete tool receipts qualify. Rejected
native calls must explicitly attest that no mutation was applied.
Closure authorizes measurement of the executed prefix, never task success.
The scorer still determines reward from the fixed task and observed effects.
"""
from __future__ import annotations

from sagents.v2.optimization.native_projection import observation_digest, project_mcp_execution_order

PROTOCOL = 'sage.rsi.single-turn-episode-closure/v1'
LOOP_REASONS = frozenset({'loop.repeated_pattern', 'loop.no_progress'})


def _unapplied_result(item):
    data = item.get('data') or {}
    error = data.get('error') or {}
    metadata = error.get('metadata') or {}
    return (item.get('status') == 'failed' and data.get('kind') == 'tool_result'
        and bool(error.get('code'))
        and metadata.get('side_effect_state') == 'not_applied'
        and (error.get('code') != 'tool.not_found' or metadata.get('tool_execution_started') is False))


def close_single_turn_episode(observation, case):
    """Return an annotated copy, or None when native evidence is insufficient.

    Both raw legacy item.completed events and canonical final_items captured by
    the runner are supported. A caller's closure label alone is never proof.
    Dialogue, approvals, transport failures and genuine user questions retain
    their existing suspension semantics.
    """
    if case.mode != 'single_turn' or observation.state != 'suspended':
        return None
    try:
        return _close(observation)
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def evaluation_episode_finished(observation, case):
    return observation.state == 'completed' or close_single_turn_episode(observation, case) is not None


def _close(observation):
    evidence = observation.evidence
    run = evidence.get('run_id')
    suspension = evidence.get('suspension') or {}
    if (not run or evidence.get('error') or evidence.get('runtime_events_truncated') is not False
            or evidence.get('state') != 'suspended'
            or suspension.get('run_id') != run or suspension.get('reason') != 'input_required'
            or not suspension.get('interaction_id')):
        return None
    events = evidence['runtime_events']
    interactions = [event for event in events
                    if event.get('run_id') == run and event.get('type') == 'interaction.requested'
                    and event.get('data', {}).get('interaction_id') == suspension['interaction_id']]
    if len(interactions) != 1:
        return None
    interaction = interactions[0]['data']
    reason = (interaction.get('payload') or {}).get('reason_code')
    if (reason not in LOOP_REASONS or interaction.get('interaction_type') not in {'user_input', 'loop_recovery'}
            or set(interaction.get('allowed_decisions', ())) != {'submit', 'cancel'}):
        return None
    if not any(event.get('type') == 'run.suspended' and event.get('run_id') == run
               and event.get('data', {}).get('reason') == 'input_required' for event in events):
        return None
    raw_items = [event['data']['item'] for event in events
                 if event.get('run_id') == run and event.get('type') == 'item.completed']
    canonical = evidence.get('final_items')
    source = canonical if canonical else raw_items
    items, seen, calls, results = [], {}, {}, {}
    for item in source:
        if item.get('run_id') != run or (item.get('status') != 'completed' and not _unapplied_result(item)):
            return None
        identity = item.get('item_id')
        if not isinstance(identity, str) or not identity or identity in seen and seen[identity] != item:
            return None
        if identity in seen:
            continue
        seen[identity] = item
        items.append(item)
        data = item['data']
        if data.get('kind') in {'tool_call', 'tool_result'}:
            target = calls if data['kind'] == 'tool_call' else results
            call_id = data['tool_call_id']
            if not isinstance(call_id, str) or not call_id or call_id in target:
                return None
            target[call_id] = item
    # Retained raw events must agree with canonical envelopes when both exist.
    if any(seen.get(item.get('item_id')) != item for item in raw_items):
        return None
    if not calls or calls.keys() != results.keys():
        return None
    proposed, succeeded = {}, {}
    for event in events:
        if event.get('run_id') != run:
            continue
        if event.get('type') == 'tool.call.cancelled':
            return None
        if event.get('type') not in {'tool.call.proposed', 'tool.call.succeeded', 'tool.call.failed'}:
            continue
        target = proposed if event['type'] == 'tool.call.proposed' else succeeded
        identity = event['data']['tool_call_id']
        if identity in target:
            return None
        target[identity] = event
    if proposed.keys() != calls.keys() or succeeded.keys() != calls.keys():
        return None
    for identity, call in calls.items():
        result, start, end = results[identity], proposed[identity], succeeded[identity]
        args = call['data']['arguments']
        if not isinstance(args, dict) or not call.get('step_id'):
            return None
        name = call['data']['tool_name']
        unapplied = _unapplied_result(result)
        if unapplied and name not in {'file_write', 'file_update', 'file_read', 'list_dir', 'turn_status'}:
            if name.startswith('mcp_') or result['data']['error']['code'] != 'tool.not_found':
                return None
        if unapplied:
            if (end.get('type') != 'tool.call.failed' or end['data'].get('state') != 'failed'
                    or end['data'].get('error') != result['data']['error']):
                return None
        elif (end.get('type') != 'tool.call.succeeded' or end['data'].get('state') != 'completed'
                or end['data'].get('error') or result['data'].get('error')):
            return None
        if name == 'load_skill':
            if not evidence.get('session_id'):
                return None
            args = {**args, 'session_id': evidence['session_id']}
        if (any(value.get('step_id') != call['step_id'] for value in (result, start, end))
                or start['data'].get('tool_name') != name
                or start['data'].get('arguments') != args
                or not start['data'].get('operation_id')
                or start['data']['operation_id'] != end['data'].get('operation_id')
                or end['data'].get('result_item_id') != result['item_id']
                or start.get('run_sequence', 0) >= end.get('run_sequence', 0)):
            return None
        if (name.startswith('mcp_')
                and result['data'].get('metadata', {}).get('mcp_result_received') is not True):
            return None
    receipt = {
        'protocol': PROTOCOL, 'native_state': 'suspended', 'episode_state': 'closed',
        'reason': reason, 'interaction_id': suspension['interaction_id'],
        'tool_call_count': len(calls),
        'rejected_not_applied_calls': sum(_unapplied_result(item) for item in results.values()),
        'coverage': 'complete native tool receipts; no inferred actions',
    }
    previous = evidence.get('episode_termination') or {}
    if all(previous.get(key) == value for key, value in receipt.items()):
        receipt['source_observation_hash'] = previous.get('source_observation_hash')
    else:
        receipt['source_observation_hash'] = observation_digest(observation)
    annotated = observation.model_copy(update={'evidence': {**evidence,
        'final_items': items, 'episode_termination': receipt}})
    return project_mcp_execution_order(annotated)
