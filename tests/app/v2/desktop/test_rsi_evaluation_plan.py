import json

import pytest

from app.v2.desktop.backend.rsi_evaluation import EvaluationPlan
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request


@pytest.mark.asyncio
async def test_import_select_and_execute_plan_persists_and_keeps_baseline_unchanged(tmp_path, monkeypatch):
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        before = await service._agent(agent_id, 'alice')
        plan = EvaluationPlan.model_validate({'name': 'Imported evaluation', 'dataset': {
            'name': 'Arithmetic', 'cases': [
                {'id': 'train', 'input': '6*7?', 'rubric': '42', 'reference_answer': '42'},
                {'id': 'dev', 'input': '40+2?', 'rubric': '42', 'reference_answer': 'hidden-dev', 'split': 'validation'},
                {'id': 'test', 'input': '21*2?', 'rubric': '42', 'reference_answer': 'hidden-test', 'split': 'test'}]}})
        imported = await service.import_rsi_evaluation_plan(agent_id, plan, 'alice')
        repeated = await service.import_rsi_evaluation_plan(agent_id, plan, 'alice')
        assert imported == repeated and imported['validation_case_count'] == 1
        history = await service.rsi_history(agent_id, 'alice')
        assert len(history['evaluation_plans']) == 1
        assert 'hidden-dev' not in json.dumps(history) and 'hidden-test' not in json.dumps(history)
        request = start_request().model_copy(update={'suite': None, 'evaluation_plan_id': imported['id'], 'rounds': 1})
        run = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[run['id']]
        finished = await service.rsi_run(agent_id, run['id'], 'alice')
        assert finished['status'] == 'completed', finished.get('error')
        assert finished['test_observations'][0]['cases'][0]['id'] == 'test'
        assert (await service._agent(agent_id, 'alice')).config == before.config
        assert (await service.start_rsi(agent_id, request, 'alice'))['id'] == run['id']
        with pytest.raises(ValueError):
            await service.import_rsi_evaluation_plan(agent_id, plan, 'bob')
    finally:
        await service.close()
