import json

from evaluation_datasets.tau_bench.export_dataset import ROOT, build_dataset
from sagents.v2.optimization.dataset import OptimizationDataset


def test_export_is_reproducible_and_uses_the_standard_import_schema():
    dataset = build_dataset()
    assert dataset == build_dataset()
    assert OptimizationDataset.model_validate_json(dataset.model_dump_json()) == dataset
    assert len(dataset.cases) == 114
    assert {s: sum(c.split == s for c in dataset.cases) for s in ('training', 'validation', 'test')} == {
        'training': 62, 'validation': 12, 'test': 40}
    official = json.loads((ROOT / 'data/tau2/domains/retail/split_tasks.json').read_text())
    assert {c.id.removeprefix('tau-') for c in dataset.cases if c.split == 'test'} == set(official['test'])
    assert {c.id.removeprefix('tau-') for c in dataset.optimization_suite().cases} == set(official['train'])


def test_questions_and_machine_readable_reference_answers_preserve_official_source():
    tasks = {str(t['id']): t for t in json.loads((ROOT / 'data/tau2/domains/retail/tasks.json').read_text())}
    for case in build_dataset().cases:
        task = tasks[case.id.removeprefix('tau-')]
        assert case.input == 'Hello.'
        assert case.dialogue_completion == 'user'
        assert task['user_scenario']['instructions']['reason_for_call'] not in case.input
        assert json.loads(case.user_context) == task['user_scenario']
        reference = json.loads(case.reference_answer)
        assert reference['evaluation_criteria'] == task['evaluation_criteria']
        assert reference['initial_state'] == task['initial_state']
        assert 'evaluation_criteria' not in json.loads(case.user_context)


def test_committed_dataset_is_exactly_regenerable():
    assert (ROOT / 'rsi.dataset.json').read_text() == build_dataset().model_dump_json(indent=2) + '\n'
