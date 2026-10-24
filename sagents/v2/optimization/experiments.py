"""Training-only validation of hypotheses declared before candidate measurement."""
from __future__ import annotations


def validate_experiment(experiment, parent, measured_cases, *, required=True):
    if experiment is None:
        if required:
            raise ValueError('A changed candidate requires a predeclared experiment with one mechanism and falsification conditions')
        return
    if experiment.parent_hash != parent.content_hash:
        raise ValueError('Experiment parent_hash differs from the retained version')
    training = {item.case.id for item in measured_cases if item.case.split == 'training'}
    if not set((*experiment.training_case_ids, *experiment.protection_case_ids)) <= training:
        raise ValueError('Experiment may cite only measured training case IDs; validation/test evidence is unavailable')
    successes = {item.case.id for item in measured_cases if item.case.split == 'training'
                 and (item.grade.passed or any(trial.grade.passed for trial in item.trials))}
    if not set(experiment.protection_case_ids) <= successes:
        raise ValueError('Protection cases require a recorded passing retained execution')
    fields = ('mechanism', 'applicability', 'existing_rule_gap', 'expected_observation',
              'support_condition', 'falsification_condition', 'inconclusive_condition')
    if any(not getattr(experiment, field).strip() for field in fields):
        raise ValueError('Experiment conditions must be nonblank')
    if experiment.support_condition.strip() == experiment.falsification_condition.strip():
        raise ValueError('Support and falsification conditions must distinguish different observations')
    if any(not text.strip() for text in (*experiment.change_locations, *experiment.protected_behaviors)):
        raise ValueError('Experiment must name change locations and protected behaviors')


def candidate_changes(parent, candidate):
    """Actual diff coordinates, independently saved alongside the experiment."""
    changes = [f'files/{name}' for name in sorted(set(parent.files) | set(candidate.files))
               if parent.files.get(name) != candidate.files.get(name)]
    before, after = parent.manifest.model_dump(mode='json'), candidate.manifest.model_dump(mode='json')
    for agent in sorted(set(before['agents']) | set(after['agents'])):
        old, new = before['agents'].get(agent, {}), after['agents'].get(agent, {})
        changes.extend(f'manifest.agents.{agent}.{field}' for field in sorted(set(old) | set(new))
                       if old.get(field) != new.get(field))
    return changes
