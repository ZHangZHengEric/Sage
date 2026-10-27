"""External RSI MCP user-review projection, separate from internal tuning inputs.

The user-delegated reviewer can inspect train/dev executions, grades, diagnoses
and selection metrics. Test observations, raw mixed-split calls and credentials
remain excluded. Internal tuning isolation is enforced in the SDK, not here.
"""
from __future__ import annotations

from copy import deepcopy

_PRIVATE = {'test_observations', 'benchmark_measurement', 'agent_calls', 'internal_agents', 'call', 'tuner_call',
            'recommendation_block_reason', 'assets', 'config', 'reference_answer',
            'dataset_manifest', 'generated_dataset_manifest', 'dataset_diagnostics', 'dataset_version', 'dataset_versions', 'dataset_validation',
            'exclusions', 'active_case_ids'}
_EVENT_FIELDS = {
    'operation_started': {'goal', 'agent_id', 'rounds', 'evaluation_repeats', 'max_concurrency', 'package', 'constraints', 'optimization_scope', 'builtin_scoring'},
    'suite_fixed': {'suite'},
    'test_generation_batch_completed': {'cases'},
    'training_cases_added': {'round', 'cases'},
    'training_challenge_completed': {'round', 'evaluation'},
    'training_diagnosis_completed': {'round', 'summary'},
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


def review_view(value):
    if isinstance(value, list):
        return [safe for item in value if (safe := review_view(item)) is not None]
    if not isinstance(value, dict):
        return deepcopy(value)
    if 'event' in value and 'data' in value:
        name, data = value['event'], value['data']
        # Raw target/user/evaluator events cannot be classified safely from a
        # paginated page alone. Their contents stay on Desktop; completed train/dev
        # case evidence is delivered via case_completed/evaluation snapshots.
        fields = _EVENT_FIELDS.get(name, {'round', 'phase', 'trial', 'role'})
        safe = review_view({k: v for k, v in data.items() if k in fields})
        return {**{k: value[k] for k in ('sequence', 'event', 'timestamp') if k in value}, 'data': safe}
    case = value.get('case')
    if isinstance(case, dict) and 'split' in case:
        if case['split'] not in {'training', 'validation'}:
            return None
        reviewed = deepcopy(value)
        reviewed['case'].pop('reference_answer', None)
        return reviewed
    if 'split' in value:
        if value['split'] not in {'training', 'validation'}:
            return None
        reviewed = deepcopy(value)
        reviewed.pop('reference_answer', None)
        return reviewed
    if 'issues' in value and 'approved' in value:
        # Mixed-split preflight rationale may quote excluded test evidence.
        return {'approved': value['approved']}
    safe = {}
    for key, child in value.items():
        if key in _PRIVATE or key.startswith(('human_test', 'final_')):
            continue
        if key == 'cases' and isinstance(child, list):
            if any(r.get('split') == 'validation' for r in child if isinstance(r, dict)):
                safe['validation_count'] = sum(r.get('split') == 'validation' for r in child)
            safe[key] = review_view(child)
        elif key == 'reason':
            # Legacy final-exam reasons may contain hidden test case IDs.
            # Dev diagnoses remain available in each case grade/assessment.
            safe[key] = child if child in {'target_reached', 'stagnation', 'round_limit',
                'regression', 'training_passed', 'unmeasured_round', 'no_regression'} else 'See train/dev evaluation evidence; mixed-split free-text reasons are omitted'
        elif key.endswith('package') and isinstance(child, dict) and 'manifest' in child:
            package = deepcopy(child)
            package['manifest']['tests'] = {'scenarios': [], 'gates': {}}
            safe[key] = package
        else:
            cleaned = review_view(child)
            if cleaned is not None:
                safe[key] = cleaned
    return safe
