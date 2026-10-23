from sagents.v2.optimization.dataset import DatasetEnvironment
from sagents.v2.optimization.dataset_summary import summarize_dataset
from tests.sagents.v2.test_dataset_preflight_policy import dataset


def test_summary_counts_splits_modes_turn_limits_and_advisory_without_model_calls():
    original = dataset()
    cases = list(original.cases)
    cases[0] = cases[0].model_copy(update={
        'mode': 'dialogue', 'max_turns': 8, 'user_context': '',
        'coverage_tags': ('policy', 'policy'), 'reference_answer': 'Reference',
    })
    data = original.model_copy(update={'cases': tuple(cases)})
    report = summarize_dataset(data)
    assert report['status'] == 'passed'
    assert report['case_count'] == 4
    assert report['split_counts'] == {'training': 1, 'validation': 2, 'test': 1}
    assert report['mode_counts'] == {'single_turn': 3, 'dialogue': 1}
    assert report['dialogue']['min_turns'] == report['dialogue']['max_turns'] == 8
    assert report['reference_count'] >= 1
    assert {'tag': 'policy', 'count': 1} in report['coverage_tags']
    assert report['warnings'][0]['case_ids'] == [cases[0].id]
    assert report['checks'][-1]['status'] == 'not_required'
    assert report['scorer_status'] == 'separate_validation_required'
    assert {row['split'] for row in report['examples']} == {'training', 'validation', 'test'}
    assert original.cases[0].mode == 'single_turn'


def test_environment_summary_distinguishes_unchecked_binding_and_verified_tools():
    data = dataset().model_copy(update={'environment': DatasetEnvironment(mcp_servers=('GenericEnvironment',))})
    assert summarize_dataset(data)['checks'][-1]['status'] == 'not_checked'
    checked = summarize_dataset(data, environment_checked=True, environment_tool_count=16)
    assert checked['checks'][-1]['status'] == 'passed'
    assert checked['environment']['tool_count'] == 16
    assert checked['environment']['mcp_servers'] == ['GenericEnvironment']
