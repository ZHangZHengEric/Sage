"""Model-facing RSI views. Human Desktop views retain their separate evidence.

Detailed MCP reads do not expand visibility: training evidence is available,
validation is anonymous scores only, and test observations are never returned.
"""
from __future__ import annotations

from copy import deepcopy

_PRIVATE = {'test_observations', 'agent_calls', 'internal_agents', 'call', 'tuner_call',
            'recommendation_block_reason', 'assets', 'config'}
_EVENT_FIELDS = {
    'operation_started': {'goal', 'agent_id', 'rounds', 'evaluation_repeats', 'max_concurrency', 'package', 'constraints', 'optimization_scope'},
    'suite_fixed': {'suite'},
    'test_generation_batch_completed': {'cases'},
    'training_cases_added': {'round', 'cases'},
    'training_challenge_completed': {'round', 'evaluation'},
    'case_completed': {'round', 'phase', 'trial', 'result'},
    'evaluation_completed': {'round', 'evaluation'},
    'round_completed': {'record'},
    'candidate_created': {'round', 'package', 'patch'},
    'semantic_review_completed': {'round', 'review'},
    'suite_review_completed': {'review'},
    'training_suite_review_completed': {'round', 'review'},
    'stability_check_completed': {'round', 'attempt', 'confirmation', 'passed', 'evaluation'},
    'optimization_stopped': {'reason', 'completed_rounds', 'stability_passes'},
    'result_completed': {'result'},
}


def validation_scores(cases):
    rows = [c for c in cases if c.get('case', {}).get('split') == 'validation']
    scores = [r.get('grade', {}).get('score') for r in rows]
    valid = all(isinstance(s, (int, float)) for s in scores)
    return {'score': sum(scores) / len(scores) if scores and valid else None,
            'total': len(rows), 'passed': sum(r.get('grade', {}).get('passed') is True for r in rows),
            'items': [{'index': i, 'score': r.get('grade', {}).get('score')} for i, r in enumerate(rows, 1)]}


def model_view(value):
    if isinstance(value, list):
        return [safe for item in value if (safe := model_view(item)) is not None]
    if not isinstance(value, dict):
        return deepcopy(value)
    if 'event' in value and 'data' in value:
        name, data = value['event'], value['data']
        # Raw target/user/evaluator events cannot be classified safely from a
        # paginated page alone. Their contents stay on Desktop; completed train
        # case evidence is delivered via case_completed/evaluation snapshots.
        fields = _EVENT_FIELDS.get(name, {'round', 'phase', 'trial', 'role'})
        safe = model_view({k: v for k, v in data.items() if k in fields})
        return {**{k: value[k] for k in ('sequence', 'event', 'timestamp') if k in value}, 'data': safe}
    case = value.get('case')
    if isinstance(case, dict) and 'split' in case:
        return deepcopy(value) if case['split'] == 'training' else None
    if 'split' in value:
        return deepcopy(value) if value['split'] == 'training' else None
    if 'issues' in value and 'approved' in value:
        # A suite-review rationale can quote hidden validation questions.
        return {'approved': value['approved']}
    safe = {}
    for key, child in value.items():
        if key in _PRIVATE or key.startswith(('human_test', 'final_')):
            continue
        if key == 'cases' and isinstance(child, list):
            if any('case' in r for r in child if isinstance(r, dict)):
                safe['validation'] = validation_scores(child)
            elif any(r.get('split') == 'validation' for r in child if isinstance(r, dict)):
                safe['validation_count'] = sum(r.get('split') == 'validation' for r in child)
            safe[key] = model_view(child)
        elif key == 'reason':
            # Old fixed-suite rejection messages may contain private case IDs.
            safe[key] = child if child in {'target_reached', 'stagnation', 'round_limit'} else 'See training evidence and anonymous validation scores'
        elif key.endswith('package') and isinstance(child, dict) and 'manifest' in child:
            package = deepcopy(child)
            package['manifest']['tests'] = {'scenarios': [], 'gates': {}}
            safe[key] = package
        else:
            cleaned = model_view(child)
            if cleaned is not None:
                safe[key] = cleaned
    return safe
