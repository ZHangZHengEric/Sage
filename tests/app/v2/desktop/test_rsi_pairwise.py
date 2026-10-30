import pytest

from app.v2.desktop.backend.rsi import RsiStart
from app.v2.desktop.backend.rsi_evaluation import ScorerImport, ScorerSelection
from sagents.v2.optimization.builtin_scoring import BuiltinScoring
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request
from tests.sagents.v2.test_comparison_plugin import plugin_source


@pytest.mark.asyncio
async def test_imported_comparison_plugin_is_admitted_only_for_pairwise_mode(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        source = ScorerImport(name='comparison.py', source=plugin_source())
        assert source.is_comparison()
        imported = await service.import_rsi_scorer(agent, source, 'alice')
        assert imported['validation']['protocol'] == 'sage.rsi.comparison/v1'
        selection = ScorerSelection(mode='python', module_id=imported['id'], descriptor=imported['descriptor'])
        request = start_request().model_copy(update={'scorer': selection})
        with pytest.raises(ValueError, match='pairwise mode'):
            await service._rsi_scorer_selection(request, 'alice', agent)
        paired = request.model_copy(update={'builtin_scoring': BuiltinScoring(mode='pairwise')})
        admitted = await service._rsi_scorer_selection(paired, 'alice', agent)
        assert admitted.binding_id == imported['validation']['dependency_binding']
    finally:
        await service.close()


def test_pairwise_requests_use_mean_and_reject_dialogues():
    from tests.sagents.v2.test_package_optimizer import suite
    request = RsiStart(goal='Clarity', request_id='pairwise', builtin_scoring={'mode': 'pairwise'},
        evaluation_repeats=3, evaluation_aggregation='minimum', suite=suite())
    assert request.evaluation_aggregation == 'mean'
    dialogue = suite().model_copy(update={'cases': tuple(c.model_copy(update={'mode': 'dialogue'}) for c in suite().cases)})
    with pytest.raises(ValueError, match='single-turn'):
        RsiStart(goal='Clarity', request_id='bad', builtin_scoring={'mode': 'pairwise'}, suite=dialogue)


@pytest.mark.asyncio
async def test_desktop_pairwise_run_uses_plugin_for_repeated_training_and_hidden_tests(tmp_path, monkeypatch):
    from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='compare.py', source=plugin_source()), 'alice')
        request = start_request().model_copy(update={'rounds': 1, 'grow_training': False,
            'builtin_scoring': BuiltinScoring(mode='pairwise'), 'scorer_id': imported['id'],
            'evaluation_repeats': 2, 'human_test_repeats': 2,
            'human_test_suite': OptimizationTestSuite(cases=(OptimizationCase(id='hidden', input='Hidden novel comparison task',
                rubric='Prefer useful result', split='test'),))})
        run = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[run['id']]
        final = await service.rsi_run(agent, run['id'], 'alice')
        assert final['status'] == 'completed', final.get('error_type')
        report = final['result']['report']
        assert report['evaluation_aggregation'] == 'mean'
        assert report['goal_verified'] is None
        assert report['baseline']['cases'][0]['trials'][0]['grade']['score'] == .5
        records = final['test_observations']
        assert records and all(r['status'] == 'completed' for r in records)
        for record in records:
            assert len(record['cases'][0]['trials']) == 2
            if record['round']:
                assert record['pairwise']['pairs'] == (0 if record['package_hash'] == records[0]['package_hash'] else 2)
                assert record['pairwise']['complete']
        assert 'Hidden novel comparison task' not in str(report['agent_calls'])
    finally:
        await service.close()


def test_absolute_scorer_with_compare_helper_keeps_original_protocol():
    module = ScorerImport(name='score.py', source='def compare(a, b): return a == b\ndef score(request): return {}\n')
    assert not module.is_comparison()
