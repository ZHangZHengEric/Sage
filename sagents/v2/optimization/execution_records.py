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


def message_content(blocks):
    values = []
    for block in blocks or []:
        if block.get('kind') == 'text':
            values.append(block.get('text', ''))
        elif block.get('kind') == 'json':
            values.append(block.get('value'))
        else:
            values.append({key: value for key, value in block.items() if value is not None})
    if all(isinstance(value, str) for value in values):
        return ''.join(values)
    return values[0] if len(values) == 1 else values


def conversation_messages(observation, *, conversation=(), initial_input=None):
    """Only visible messages and tool actions/results, in their actual order."""
    messages, seen, calls = [], set(), {}
    turns = list(conversation) or [{'user': initial_input, 'target': observation.model_dump(mode='json')}]
    for turn in turns:
        value = turn.get('target') or turn.get('observation') or {}
        native = value.get('evidence', {}).get('final_items') or []
        if turn.get('user') is not None and not any(
                row.get('data', {}).get('kind') == 'message'
                and row['data'].get('role') == 'user' for row in native):
            messages.append({'role': 'user', 'content': turn['user']})
        if not native:
            if value.get('output'):
                messages.append({'role': 'assistant', 'content': value['output']})
            elif value.get('evidence', {}).get('error'):
                error = value['evidence']['error']
                messages.append({'role': 'assistant', 'content': error.get('message') or error.get('code', 'Execution failed')})
            continue
        for row in native:
            item = row.get('data', {})
            identity = (row.get('run_id'), row.get('item_id'), json.dumps(item, ensure_ascii=False, sort_keys=True))
            if row.get('item_id') is not None and identity in seen:
                continue
            seen.add(identity)
            kind = item.get('kind')
            if kind == 'message' and item.get('role') in {'user', 'assistant'}:
                message = {'role': item['role'], 'content': message_content(item.get('content'))}
            elif kind == 'tool_call':
                calls[item.get('tool_call_id')] = item.get('tool_name')
                message = {'role': 'assistant', 'tool': item.get('tool_name'), 'arguments': item.get('arguments', {})}
            elif kind == 'tool_result':
                message = {'role': 'tool', 'tool': calls.get(item.get('tool_call_id')),
                           'content': message_content(item.get('content'))}
                if item.get('error'):
                    error = item['error']
                    message['error'] = {key: error[key] for key in ('code', 'message') if key in error} if isinstance(error, dict) else error
            else:
                continue
            if row.get('created_at'):
                message['timestamp'] = row['created_at']
            messages.append(message)
    return messages


def trial_conversation(case, trial):
    history = [{'user': turn.input, 'target': turn.observation.model_dump(mode='json')} for turn in trial.dialogue]
    observation = trial.dialogue[-1].observation if trial.dialogue else trial.observation
    return conversation_messages(observation, conversation=history, initial_input=case.input)


def trial_assessment(trial):
    grade = trial.grade
    return {'score': grade.score, 'passed': grade.passed,
        **({'scorer_details': grade.scorer_details} if grade.scorer_details else {}),
        **({'diagnosis': grade.diagnosis.model_dump(mode='json')} if grade.diagnosis else {'reason': grade.rationale})}


def visible_dialogue(observation, history):
    return [message for message in conversation_messages(observation, conversation=history)
            if message.get('role') in {'user', 'assistant'} and 'tool' not in message]
