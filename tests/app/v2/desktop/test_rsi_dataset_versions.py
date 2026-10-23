"""Dataset revisions are human-owned artifacts, independent of running jobs."""
import asyncio
import copy
import json

import httpx
import pytest

from app.v2.desktop.backend.rsi import RsiStart, frozen_rsi_request
from sagents.v2.optimization.dataset_versions import DatasetRevisionRequest
from sagents.v2.optimization.dataset import OptimizationDataset
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request
from tests.sagents.v2.test_dataset_preflight_policy import dataset


@pytest.mark.asyncio
async def test_human_exclusion_creates_new_version_without_mutating_running_snapshot(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    model = RsiModel(entered=entered, release=release)
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        registered = await service.import_rsi_dataset(agent, dataset(), 'alice')
        request = RsiStart(goal='Improve arithmetic', request_id='dataset-original', rounds=1,
            initial_training_case_count=1, training_cases_per_round=0, dataset_version_id=registered['id'])
        original = await service.start_rsi(agent, request, 'alice')
        await asyncio.wait_for(entered.wait(), 10)
        root = service.runtime_root / 'rsi' / original['id']
        frozen_bytes = (root / 'resume-context.json').read_bytes()
        frozen = json.loads(frozen_bytes)
        assert len(frozen_rsi_request(frozen, original).dataset.cases) == 4
        revised = await service.revise_rsi_dataset(agent, registered['id'], DatasetRevisionRequest(
            expected_version=registered['id'], confirmed=True, exclusions=[{
                'case_id': 'second-dev', 'reason_code': 'missing_information',
                'reason': 'Required input absent', 'evidence': ['Quoted fixture lacks required input'],
            }]), 'alice')
        assert revised['manifest']['label'] == 'revised'
        assert revised['manifest']['active_count'] == 3
        assert (root / 'resume-context.json').read_bytes() == frozen_bytes
        original_record = service.rsi_store.get(original['id'], 'alice', agent, 'run')
        assert original_record['dataset_manifest']['active_count'] == 4
        assert original_record['dataset_manifest']['exclusions'] == []
        assert len((await service.rsi_dataset(agent, registered['id'], 'alice'))['dataset']['cases']) == 4
        assert revised['manifest']['exclusions'][0]['operator'] == 'alice'
        history = await service.rsi_history(agent, 'alice')
        assert {item['id'] for item in history['dataset_versions']} == {registered['id'], revised['id']}
        with pytest.raises(ValueError):
            await service.rsi_dataset(agent, revised['id'], 'bob')
        for mutate in ('policy', 'membership', 'exclusions'):
            drift = copy.deepcopy(frozen)
            if mutate == 'policy': drift['request']['preflight_policy']['generated_repairs'] = 5
            elif mutate == 'membership': drift['request']['dataset']['cases'].pop()
            else: drift['dataset_manifest']['exclusions'] = revised['manifest']['exclusions']
            with pytest.raises(ValueError, match='changed|membership'):
                frozen_rsi_request(drift, original_record)
        await service.cancel_rsi(agent, original['id'], 'alice')
        release.set()
        replacement = await service.start_rsi(agent, RsiStart(goal='Improve arithmetic',
            request_id='dataset-revised', rounds=1, initial_training_case_count=1,
            training_cases_per_round=0, dataset_version_id=revised['id']), 'alice')
        assert replacement['dataset_manifest']['label'] == 'revised'
        assert replacement['dataset_manifest']['active_count'] == 3
        assert replacement['dataset_manifest']['counts']['test']['original'] == 1
        await service._rsi_tasks[replacement['id']]
        latest = await service.rsi_run(agent, replacement['id'], 'alice')
        assert latest['status'] == 'completed', latest.get('error_type')
        assert latest['result']['report']['dataset_manifest']['label'] == 'revised'
        original_record = service.rsi_store.get(original['id'], 'alice', agent, 'run')
        assert original_record['dataset_manifest']['active_count'] == 4
    finally:
        release.set()
        await service.close()


@pytest.mark.asyncio
async def test_dataset_http_import_localizes_hard_errors_and_confirmation_cannot_be_forged(tmp_path, monkeypatch):
    from app.v2.desktop.backend.app import create_app
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    monkeypatch.setattr('app.v2.desktop.backend.app.get_desktop_user_id', lambda request: 'alice')
    app = create_app(service=service, auth_token='human-capability')
    path = f'/api/v2/agents/{agent}/rsi/datasets'
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                headers={'Authorization': 'Bearer human-capability'}) as client:
            raw = dataset().model_dump(mode='json')
            broken = copy.deepcopy(raw); broken['cases'][1]['id'] = broken['cases'][0]['id']
            response = await client.post(path, json=broken)
            assert response.status_code == 400 and 'duplicate' in response.text
            broken = copy.deepcopy(raw); del broken['cases'][0]['split']
            response = await client.post(path, json=broken)
            assert response.status_code == 400 and 'cases[0]' in response.text and 'split' in response.text
            response = await client.post(path, json=raw)
            assert response.status_code == 200
            version = response.json()['data']
            assert version['validation']['status'] == 'passed'
            assert version['validation']['split_counts'] == {'training': 1, 'validation': 2, 'test': 1}
            assert version['validation']['scorer_status'] == 'separate_validation_required'
            assert version['validated_at']
            assert not model.requests
            saved = await service.rsi_dataset(agent, version['id'], 'alice')
            assert saved['validation'] == version['validation']
            assert 'validation' not in service.rsi_store.summaries('alice', agent, 'dataset')[0]
            revision_path = f"{path}/{version['id']}/revisions"
            proposal = {'expected_version': version['id'], 'confirmed': False, 'exclusions': [{
                'case_id': 'second-dev', 'reason_code': 'invalid_fixture', 'reason': 'A concrete fixture defect', 'evidence': ['Fixture field'],
            }]}
            assert (await client.post(revision_path, json=proposal)).status_code == 422
            proposal['confirmed'] = True; proposal['operator'] = 'tuner'
            assert (await client.post(revision_path, json=proposal)).status_code == 422
            del proposal['operator']; proposal['exclusions'][0]['reason_code'] = 'low_score'
            assert (await client.post(revision_path, json=proposal)).status_code == 422
            assert not model.requests  # No semantic model is part of hard import validation.
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_bad_environment_binding_is_a_hard_start_error_before_any_model_call(tmp_path, monkeypatch):
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        raw = dataset().model_dump(mode='json')
        raw['environment'] = {'protocol': 'sage.rsi.case/v1', 'mcp_servers': ['missing-server']}
        with pytest.raises(ValueError, match='dataset.environment.*missing-server'):
            await service.import_rsi_dataset(agent, OptimizationDataset.model_validate(raw), 'alice')
        assert not service.rsi_store.summaries('alice', agent, 'dataset')
        with pytest.raises(ValueError, match='dataset.environment.*missing-server'):
            await service.start_rsi(agent, RsiStart(goal='Run', request_id='invalid-env', dataset=raw), 'alice')
        assert not model.requests
        assert not service.rsi_store.summaries('alice', agent, 'run')
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_import_summary_records_verified_environment_without_semantic_model_calls(tmp_path, monkeypatch):
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    class Environment:
        async def definitions(self):
            return ['tool-one', 'tool-two']
    async def environment(request, user_id):
        return Environment()
    monkeypatch.setattr(service, '_rsi_case_environment', environment)
    try:
        raw = dataset().model_dump(mode='json')
        raw['environment'] = {'protocol': 'sage.rsi.case/v1', 'mcp_servers': ['GenericEnvironment']}
        registered = await service.import_rsi_dataset(agent, OptimizationDataset.model_validate(raw), 'alice')
        report = registered['validation']
        assert report['checks'][-1]['status'] == 'passed'
        assert report['environment']['checked'] is True
        assert report['environment']['tool_count'] == 2
        assert not model.requests
    finally:
        await service.close()
