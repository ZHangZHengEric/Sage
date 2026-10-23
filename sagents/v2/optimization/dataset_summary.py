"""Deterministic, human-facing summaries of validated data; no model inference."""
from collections import Counter


def summarize_dataset(dataset, *, environment_tool_count=None, environment_checked=False):
    cases = dataset.cases
    dialogue = [case for case in cases if case.mode == 'dialogue']
    splits = Counter(case.split for case in cases)
    modes = Counter(case.mode for case in cases)
    tags = Counter(tag for case in cases for tag in set(case.coverage_tags))
    environment = dataset.environment
    checks = [{'name': key, 'status': 'passed'} for key in
        ('protocol', 'required_fields', 'unique_case_ids', 'splits')]
    checks.append({'name': 'environment_binding', 'status':
        'passed' if environment_checked else 'not_checked' if environment else 'not_required'})
    warnings = []
    empty_context = [case.id for case in dialogue if not case.user_context.strip()]
    if empty_context:
        warnings.append({'code': 'empty_dialogue_context', 'case_ids': empty_context,
            'message': 'Dialogue user_context is empty; review information availability. This is advisory, not a data-error judgment.'})
    return dict(protocol='sage.rsi.dataset-validation/v1', status='passed',
        name=dataset.name, format_version=dataset.format_version, case_count=len(cases),
        split_counts={split: splits[split] for split in ('training', 'validation', 'test')},
        mode_counts={mode: modes[mode] for mode in ('single_turn', 'dialogue')},
        dialogue=dict(count=len(dialogue), min_turns=min((case.max_turns for case in dialogue), default=None),
                      max_turns=max((case.max_turns for case in dialogue), default=None),
                      user_completion_count=sum(case.dialogue_completion == 'user' for case in dialogue)),
        reference_count=sum(case.reference_answer is not None for case in cases),
        coverage_tags=[{'tag': tag, 'count': count} for tag, count in tags.most_common(30)],
        environment=None if environment is None else dict(protocol=environment.protocol,
            mcp_servers=list(environment.mcp_servers), checked=environment_checked, tool_count=environment_tool_count),
        checks=checks, warnings=warnings,
        examples=[{'id': case.id, 'split': split, 'input': case.input[:200], 'mode': case.mode}
                  for split in ('training', 'validation', 'test')
                  for case in [c for c in cases if c.split == split][:2]],
        scorer_status='separate_validation_required',
        semantic_review='diagnostic_only_for_imported_data')
