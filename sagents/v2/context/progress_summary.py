"""Bounded, rolling task facts; source bodies never become the progress ledger."""
from __future__ import annotations

import json
import re
from sagents.v2.context.summary import SummarizationRequest, summary_safe_block_text

FIELDS = ('summary', 'decisions', 'open_tasks', 'files_touched', 'commands_run', 'important_errors', 'user_requirements')


def task_snapshot(request: SummarizationRequest, narrative: dict | None = None) -> dict:
    previous = {}
    if request.previous_summary:
        try:
            previous = json.loads(request.previous_summary)
        except (ValueError, TypeError):
            # Migrate old wrappers once, without copying their nested history.
            text = re.sub(r'(?m)^Previous summary:\s*|^New history:\s*', '', request.previous_summary)
            previous = {'summary': text[:600]}
    if not isinstance(previous, dict):
        previous = {}
    result = {key: list(previous.get(key, [])) if isinstance(previous.get(key), list) else [] for key in FIELDS[1:]}
    result['summary'] = str(previous.get('summary', 'Historical task facts; continue the latest user request.'))[:800]
    if narrative:
        result.update(narrative)
    calls = {}
    outcomes = dict(previous.get('tool_outcomes', {})) if isinstance(previous.get('tool_outcomes'), dict) else {}
    todo = previous.get('todo_state_at_compaction_boundary')
    for message in request.messages:
        text = '\n'.join(summary_safe_block_text(b) for b in message.content)
        if message.role == 'user' and narrative is None:
            result['user_requirements'].append(text[:1000])
        for block in message.content:
            if getattr(block, 'kind', 'text') in ('image', 'audio', 'file', 'resource_ref'):
                result['decisions'].append(summary_safe_block_text(block))
        for call in message.tool_calls:
            calls[call.tool_call_id] = call
        if message.role != 'tool':
            continue
        call = calls.get(message.tool_call_id)
        if call is None:
            continue
        name, args = call.name, call.arguments
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = {}
        failed = text.startswith('tool.') or bool(message.metadata.get('error')) or (isinstance(payload, dict) and (payload.get('error') or payload.get('success') is False or payload.get('status') in ('error', 'failed')))
        target = next((str(args[k]) for k in ('file_path', 'path', 'command', 'query', 'skill_name') if args.get(k)), '')[:300]
        key = f'{name} {target}'
        fact = {'status': 'failed' if failed else 'completed'}
        if failed:
            fact['error'] = text[:400]
            result['important_errors'].append(f'{key}: {text[:300]}')
        if name in ('file_write', 'file_update') and not failed:
            result['files_touched'].append(target)
        if name in ('execute_shell_command', 'shell'):
            result['commands_run'].append(f'{target}: {fact["status"]}')
        if name == 'todo_write' and not failed:
            todo = args.get('tasks', args.get('todos', args))
        # Replace a resource's state rather than appending another read transcript.
        if narrative is None or name in ('file_write', 'file_update', 'todo_write', 'file_read', 'list_dir'):
            outcomes.pop(key, None)
            outcomes[key] = fact
    for key in FIELDS[1:]:
        values = result.get(key, [])
        result[key] = list(dict.fromkeys(str(v)[:1000] for v in values))[-16:]
    # Mutations survive subsequent inspection traffic.
    important = {k: v for k, v in outcomes.items() if k.startswith(('file_write ', 'file_update ', 'todo_write '))}
    reads = {k: v for k, v in outcomes.items() if k not in important}
    if outcomes:
        result['tool_outcomes'] = dict([*list(important.items())[-20:], *list(reads.items())[-8:]])
    if todo is not None:
        result['todo_state_at_compaction_boundary'] = todo
        if isinstance(todo, list) and narrative is None:
            result['open_tasks'] = [str(t.get('content', t.get('title', t.get('description', t))))[:500] for t in todo if isinstance(t, dict) and t.get('status') not in ('completed', 'done', 'cancelled')][-20:]
    return result


def bounded_snapshot(request: SummarizationRequest, narrative: dict | None = None) -> str:
    result = task_snapshot(request, narrative)
    def encode():
        return json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    if narrative is None:
        result = {k: v for k, v in result.items() if v and k != 'summary'} | ({'summary': result['summary']} if request.previous_summary else {})
        source_chars = sum(len(summary_safe_block_text(b)) for m in request.messages for b in m.content)
        if not request.previous_summary and source_chars < 128 and not result.get('files_touched') and not result.get('todo_state_at_compaction_boundary'):
            return '\n'.join([*result.get('user_requirements', []), *result.get('decisions', []), *result.get('tool_outcomes', {}).keys()]) or 'No pending work recorded.'
    maximum = max(1024, request.target_tokens * 3)
    # Preserve task state and writes ahead of disposable prose/read evidence.
    while len(encode()) > maximum:
        if result.get('tool_outcomes'):
            keys = list(result['tool_outcomes'])
            key = next((k for k in keys if not k.startswith(('file_write ', 'file_update ', 'todo_write '))), keys[0])
            del result['tool_outcomes'][key]
        elif any(result.get(k) for k in ('commands_run', 'important_errors', 'decisions')):
            next(result[k] for k in ('commands_run', 'important_errors', 'decisions') if result.get(k)).pop(0)
        elif len(result.get('summary', '')) > 80:
            result['summary'] = result['summary'][:80]
        elif any(len(result.get(k, [])) > 1 for k in ('user_requirements', 'files_touched', 'open_tasks')):
            next(result[k] for k in ('user_requirements', 'files_touched', 'open_tasks') if len(result.get(k, [])) > 1).pop(0)
        else:
            # Do not silently truncate task snapshots; let the reducer enforce its budget.
            break
    return encode()
