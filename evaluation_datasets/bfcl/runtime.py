"""Official simulated backends with JSON call-log persistence (never pickle)."""
from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

from evaluation_datasets._support import activate as activate_source

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'vendor/bfcl_eval/data'
CATEGORIES = ('base', 'miss_param', 'long_context')


def activate():
    return activate_source(ROOT, 'vendor')


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@lru_cache(maxsize=1)
def tasks():
    activate()
    result = {}
    for category in CATEGORIES:
        questions = jsonl(DATA / f'BFCL_v4_multi_turn_{category}.json')
        answers = {r['id']: r['ground_truth'] for r in jsonl(
            DATA / f'possible_answer/BFCL_v4_multi_turn_{category}.json')}
        for question in questions:
            result[question['id']] = {**question, 'ground_truth': answers[question['id']]}
    return result


def task(task_id):
    if task_id not in tasks():
        raise ValueError('Unknown or unsupported BFCL task')
    return copy.deepcopy(tasks()[task_id])


def schema(value):
    """BFCL uses Python type names; MCP needs JSON Schema type names."""
    if isinstance(value, list):
        return [schema(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: schema(v) for k, v in value.items()}
    if isinstance(result.get('type'), str):
        result['type'] = {'dict': 'object', 'float': 'number'}.get(result['type'], result['type'])
    return result


def tools(context=None):
    activate()
    from bfcl_eval.constants.executable_backend_config import MULTI_TURN_FUNC_DOC_FILE_MAPPING
    selected = task(context['task_id']) if context else None
    classes = selected['involved_classes'] if selected else sorted({
        c for t in tasks().values() for c in t['involved_classes']})
    result = {}
    for cls in classes:
        for function in jsonl(DATA / 'multi_turn_func_doc' / MULTI_TURN_FUNC_DOC_FILE_MAPPING[cls]):
            result[function['name']] = {k: schema(function[k]) for k in ('name', 'description', 'parameters')}
    return list(result.values())


def initial(context):
    task(context['task_id'])
    return {'calls': []}


def function_call(name, arguments):
    if not isinstance(arguments, dict) or any(not isinstance(k, str) or not k.isidentifier() for k in arguments):
        raise ValueError('Tool arguments must have Python identifier keys')
    return name + '(' + ', '.join(f'{key}={value!r}' for key, value in arguments.items()) + ')'


def cleanup(token):
    from bfcl_eval.eval_checker.multi_turn_eval import multi_turn_utils
    for key in list(vars(multi_turn_utils)):
        if key.startswith(token + '_') and key.endswith('_instance'):
            delattr(multi_turn_utils, key)


def call(context, state, name, arguments):
    from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import execute_multi_turn_func_call
    selected = task(context['task_id'])
    if name not in {f['name'] for f in tools(context)}:
        raise ValueError('Unavailable BFCL tool')
    code = function_call(name, arguments)
    history = [*state['calls'], code]
    token = 'sage' + uuid4().hex
    try:
        results, _ = execute_multi_turn_func_call(history, selected['initial_config'],
            selected['involved_classes'], token, selected['id'],
            long_context='long_context' in selected['id'])
    finally:
        cleanup(token)
    output = results[-1]
    return {'calls': history}, output, output.startswith('Error during execution:')


def evaluate(selected, decoded):
    activate()
    from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_checker import (
        multi_turn_checker, multi_turn_irrelevance_checker)
    token = 'sage' + uuid4().hex
    try:
        result = multi_turn_checker(decoded, selected['ground_truth'], selected,
            selected['id'].rsplit('_', 1)[0], token)
        if result['valid']:
            result = multi_turn_irrelevance_checker(decoded, selected['ground_truth'])
        return result
    finally:
        cleanup(token)


def validate_outcomes(selected, calls):
    """A denied/failed MCP call must not become a successful replayed action."""
    from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import execute_multi_turn_func_call
    if not calls:
        return
    token = 'sage' + uuid4().hex
    try:
        results, _ = execute_multi_turn_func_call([code for code, _ in calls],
            selected['initial_config'], selected['involved_classes'], token, selected['id'],
            long_context='long_context' in selected['id'])
        if any(output.startswith('Error during execution:') != failed
               for output, (_, failed) in zip(results, calls, strict=True)):
            raise ValueError('Native tool outcome differs from official replay; invalid measurement')
    finally:
        cleanup(token)


def preflight():
    manifest = activate()
    # Loading every backend detects missing dependencies before model work.
    import importlib
    from bfcl_eval.constants.executable_backend_config import CLASS_FILE_PATH_MAPPING
    classes = sorted({c for t in tasks().values() for c in t['involved_classes']})
    for name in classes:
        getattr(importlib.import_module(CLASS_FILE_PATH_MAPPING[name]), name)()
    return {'commit': manifest['commit'], 'tasks': len(tasks()), 'tools': len(tools()),
            'classes': classes, 'categories': list(CATEGORIES)}
