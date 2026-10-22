import json

import pytest

from examples.v2.tau_bench_comparison import compare, markdown


def evidence(root, reference=False):
    root.mkdir()
    metadata = {'reference_only': reference, 'commit': 'pinned', 'domain': 'retail', 'seed': 7,
        'max_steps': 200, 'target_turn_max_steps': 48, 'native_tools': ['read_file'],
        'domain_tools': ['get_order_details'], 'user_and_nl_judge_model': 'judge',
        'provider_ids': ['reference' if reference else 'target', 'teacher', 'judge'],
        'test_trials': 4, 'partition': {'test': ['task']}, 'target_model': 'reference' if reference else 'target'}
    rows = []
    for label in (['reference'] if reference else ['baseline', 'candidate']):
        rows.extend({'phase': 'test-' + label, 'task': 'task', 'trial': i, 'seed': 7+i,
            'package_hash': 'selected' if label == 'candidate' else 'same-default',
            'reward': int(label != 'candidate' or i != 3)} for i in range(4))
    for name, value in [('experiment', metadata), ('episodes', rows), ('suite', {'cases': []}),
                        ('frozen', {'baseline': 'same-default', 'candidate': 'same-default' if reference else 'selected'})]:
        (root / f'{name}.json').write_text(json.dumps(value))


def test_matched_report_preserves_regression_and_rejects_incomplete_or_changed_conditions(tmp_path):
    experiment, reference = tmp_path / 'rsi', tmp_path / 'reference'
    evidence(experiment)
    evidence(reference, reference=True)
    result = compare(experiment, reference)
    assert result['rsi_delta'] == {'pass^1': -.25, 'pass^4': -1}
    assert '-25.00' in markdown(result) and '0.00%' in markdown(result)
    rows = json.loads((reference / 'episodes.json').read_text())
    (reference / 'episodes.json').write_text(json.dumps(rows[:-1]))
    with pytest.raises(ValueError, match='incomplete'):
        compare(experiment, reference)
    (reference / 'episodes.json').write_text(json.dumps(rows))
    metadata = json.loads((reference / 'experiment.json').read_text())
    metadata['max_steps'] = 300
    (reference / 'experiment.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='max_steps'):
        compare(experiment, reference)


def test_unchanged_candidate_is_reported_as_repeat_not_rsi_improvement(tmp_path):
    experiment, reference = tmp_path / 'rsi', tmp_path / 'reference'
    evidence(experiment)
    evidence(reference, reference=True)
    frozen = json.loads((experiment / 'frozen.json').read_text())
    frozen['candidate'] = frozen['baseline']
    (experiment / 'frozen.json').write_text(json.dumps(frozen))
    rows = json.loads((experiment / 'episodes.json').read_text())
    for row in rows:
        row['package_hash'] = frozen['baseline']
    (experiment / 'episodes.json').write_text(json.dumps(rows))
    result = compare(experiment, reference)
    assert result['candidate_changed'] is False
    assert result['rsi_delta'] is None
    assert result['measurement_delta'] == {'pass^1': -.25, 'pass^4': -1}
    rendered = markdown(result)
    assert 'RSI 后' not in rendered
    assert '不能归因于 RSI 改进' in rendered
    assert '-25.00' in rendered


def test_transport_resume_adjustment_is_visible_in_comparison(tmp_path):
    experiment, reference = tmp_path / 'rsi', tmp_path / 'reference'
    evidence(experiment)
    evidence(reference, reference=True)
    (experiment / 'implementation-adjustments.json').write_text(json.dumps([
        {'change': 'Handle native user input pause', 'completed_final_measurements_preserved': 2}]))
    result = compare(experiment, reference)
    assert result['adapter_adjustments_disclosed'] is True
    assert result['audit'][0]['implementation_adjustments'][0]['completed_final_measurements_preserved'] == 2
    assert '不是全程使用单一适配器实现' in markdown(result)
