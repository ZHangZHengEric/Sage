"""Semantic execution events saved alongside canonical conversation items."""
from __future__ import annotations

import json

LIFECYCLE = {'checkpoint.committed', 'run.accepted', 'run.queued', 'run.started',
             'step.started', 'step.completed', 'continuation.decided'}


def compact_execution_event(event, final_items):
    data = event.get('data', {})
    important = (bool(data.get('error')) or data.get('state') in
        {'failed', 'cancelled', 'interrupted', 'waiting', 'suspended'}
        or data.get('retry_at') is not None
        or isinstance(data.get('attempt'), (int, float)) and data['attempt'] > 1)
    if event.get('type') in LIFECYCLE and not important:
        return None
    item = data.get('item')
    if event.get('type') == 'item.completed' and isinstance(item, dict) and item.get('item_id') and not important:
        if any(row.get('item_id') == item['item_id'] and row.get('run_id') == item.get('run_id')
               and row.get('data') == item.get('data') for row in final_items if isinstance(row, dict)):
            return None
    keys = {'type', 'event_id', 'occurred_at', 'run_id', 'run_sequence', 'turn_id', 'step_id',
            'item_id', 'interaction_id', 'flow_execution_id', 'node_execution_id', 'data'}
    return {key: value for key, value in event.items() if key in keys and value is not None}


def compact_training_execution(result):
    """Model-facing record file; canonical items and all trial results remain."""
    from sagents.v2.optimization.diagnostics import execution_entries
    rows = []
    for index, trial in enumerate(result.trials or (result,), 1):
        history = [{'user': turn.input, 'target': turn.observation.model_dump(mode='json')} for turn in trial.dialogue]
        observation = trial.dialogue[-1].observation if trial.dialogue else trial.observation
        rows.append({'trial': index, 'grade': trial.grade.model_dump(mode='json'),
            'execution': execution_entries(observation, conversation=history),
            'stop_reason': getattr(trial, 'stop_reason', None),
            'elapsed_seconds': trial.observation.elapsed_seconds})
    case = result.case.model_dump(mode='json')
    case.pop('reference_answer', None)
    return json.dumps({'protocol': 'sage.rsi.execution-record/v1', 'case': case,
        'grade': result.grade.model_dump(mode='json'), 'trials': rows,
        'contrast': result.contrast.model_dump(mode='json') if result.contrast else None}, ensure_ascii=False, indent=2)
