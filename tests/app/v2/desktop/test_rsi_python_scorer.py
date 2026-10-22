import json

import pytest
from pydantic import ValidationError

from app.v2.desktop.backend.rsi_evaluation import ScorerImport, ScorerSelection
from tests.sagents.v2.test_python_scorer import request as scoring_request
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request, authored_evaluation_response


@pytest.mark.asyncio
async def test_import_freezes_source_and_binds_owner_agent_and_hash(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        source = ScorerImport(name='accuracy.py', source="def score(request):\n return {'score': .8, 'passed': True, 'rationale': 'Correct'}\n")
        source = source.model_copy(update={"source": source.source + "\nSCORER_TEST_CASES = " + repr([{'request': scoring_request().model_dump(mode='json'), 'expected_score': .8, 'expected_passed': True}])})
        imported = await service.import_rsi_scorer(agent, source, 'alice')
        assert imported == await service.import_rsi_scorer(agent, source, 'alice')
        history = await service.rsi_history(agent, 'alice')
        assert history['scorers'] == [imported]
        assert 'def score' not in json.dumps(history) and 'scorer.py' not in json.dumps(history)
        request = start_request().model_copy(update={'scorer': ScorerSelection(mode='python', module_id=imported['id'], descriptor=imported['descriptor'])})
        selection = await service._rsi_scorer_selection(request, 'alice', agent)
        assert selection.binding_id == imported['source_hash']
        with pytest.raises(ValueError):
            await service._rsi_scorer_selection(request, 'bob', agent)
        stored = service.rsi_store.get(imported['id'], 'alice', agent, 'scorer')
        from pathlib import Path
        Path(stored['path']).write_text('changed')
        with pytest.raises(ValueError, match='changed'):
            await service._rsi_scorer_selection(request, 'alice', agent)
    finally:
        await service.close()


@pytest.mark.parametrize('source', ['not python !!!', 'x = 1', 'class X:\n def score(self): pass'])
def test_scorer_import_requires_exported_function(source):
    with pytest.raises(ValidationError):
        ScorerImport(name='invalid.py', source=source)


@pytest.mark.asyncio
@pytest.mark.parametrize('suffix', ['', '\nSCORER_TEST_CASES = [{"request": {}, "expected_score": 1, "expected_passed": True}]'])
async def test_unvalidated_scorer_is_never_selectable(tmp_path, monkeypatch, suffix):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        with pytest.raises(ValueError, match='validation failed'):
            await service.import_rsi_scorer(agent, ScorerImport(name='broken.py', source='def score(request):\n return {}\n' + suffix), 'alice')
        assert (await service.rsi_history(agent, 'alice'))['scorers'] == []
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_native_rsi_supplies_shared_model_api_without_replacing_scorer_logic(tmp_path, monkeypatch):
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis
    class Model(RsiModel):
        async def _stream(self, request):
            raw = ''.join(getattr(b, 'text', '') for m in request.messages if m.role == 'user' for b in m.content)
            if '<user_request>' in raw:
                raw = raw.rsplit('<user_request>', 1)[1].split('</user_request>', 1)[0].strip()
            try:
                title = json.loads(raw).get('response_schema', {}).get('title')
            except ValueError:
                title = None
            if title in {'OptimizationDiagnosis', 'OptimizationDiagnosisSummary'}:
                value = diagnosis() if title == 'OptimizationDiagnosis' else {'summary': 'Scorer fixed score; analyzed execution', 'priorities': []}
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='analysis', text=json.dumps(value), finish_reason='stop') if not json.loads(raw).get('data', {}).get('protocol') == 'sage.rsi.evaluation-files/v1' else authored_evaluation_response(request, json.loads(raw), value))
                return
            async for event in super()._stream(request):
                yield event
    service, agent = await setup_service(tmp_path, monkeypatch, Model())
    try:
        source = '''import os
SCORER_CONTRACT = 'Fixed fixture score; execution analysis must not replace it.'
from sagents.v2.optimization.scorer_runtime import get_model_api
def score(request):
    if 'SAGE_RSI_SCORER_MODEL_API' in os.environ:
        api = get_model_api()
        assert api.model == 'test'
        assert api.protocol == 'openai-responses'
        assert api.api_key.get_secret_value()
    return {'score': .75, 'passed': True, 'rationale': 'Custom scorer owns this result'}
SCORER_TEST_CASES = ''' + repr([{'request': scoring_request().model_dump(mode='json'), 'expected_score': .75, 'expected_passed': True}])
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='model-api.py', source=source), 'alice')
        assert imported['descriptor']['contract'].startswith('Fixed fixture score')
        request = start_request().model_copy(update={'rounds': 1, 'grow_training': False, 'scorer_id': imported['id']})
        started = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error')
        cases = run['result']['report']['baseline']['cases']
        assert all(case['grade']['score'] == .75 and case['grade']['passed'] for case in cases)
        assert all(case['grade']['diagnosis'] for case in cases)
        assert 'secret-test-key' not in json.dumps(run)
        assert 'SAGE_RSI_SCORER_MODEL_API' not in json.dumps(run['result']['report']['agent_calls'])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_native_evaluator_reads_files_writes_json_and_repairs_invalid_evidence_without_rerunning_target(tmp_path, monkeypatch):
    from sagents.v2.model.contracts import ModelEventKind, ModelStreamEvent
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis
    class FileEvaluator(RsiModel):
        bad_written = False
        evaluator_calls = 0
        async def _stream(self, request):
            raw = ''.join(b.text for m in request.messages if m.role == 'user' for b in m.content if hasattr(b, 'text'))
            if '<user_request>' in raw:
                raw = raw.rsplit('<user_request>', 1)[1].split('</user_request>', 1)[0].strip()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            if payload.get('data', {}).get('protocol') == 'sage.rsi.evaluation-files/v1':
                assert {t.name for t in request.tools} == {'file_read', 'file_write'}
                assert '40 plus 2?' not in raw
                title = payload['response_schema']['title']
                if title == 'OptimizationDiagnosis':
                    answer = diagnosis(999999 if not self.bad_written else 0)
                elif title == 'OptimizationDiagnosisSummary':
                    answer = {'summary': 'Prioritize actual training evidence', 'priorities': []}
                else:
                    answer = {'score': .9, 'passed': True, 'rationale': 'File-based evaluation'}
                response = authored_evaluation_response(request, payload, answer)
                if response.tool_calls and response.tool_calls[0].name == 'file_write':
                    self.evaluator_calls += 1
                    self.bad_written = True
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)
                return
            async for event in super()._stream(request):
                yield event
    model = FileEvaluator()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        source = "def score(request):\n return {'score': .75, 'passed': True, 'rationale': 'Fixed authority'}\nSCORER_TEST_CASES = " + repr([
            {'request': scoring_request().model_dump(mode='json'), 'expected_score': .75, 'expected_passed': True}])
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='fixed.py', source=source), 'alice')
        started = await service.start_rsi(agent, start_request().model_copy(update={
            'rounds': 1, 'grow_training': False, 'scorer_id': imported['id']}), 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error_type')
        events = run['events']
        target_calls = [e['data'] for e in events if e['event'] == 'target_call_started']
        assert len(target_calls) == 4  # Two baseline and two candidate cases.
        assert len({(c['round'], c['case_id'], c['trial'], c['turn']) for c in target_calls}) == 4
        assert any(e['event'] == 'agent_response_repair_requested' for e in events)
        assert all(c['grade']['score'] == .75 for c in run['result']['report']['baseline']['cases'])
        root = service.runtime_root / 'rsi' / started['id'] / 'evaluations'
        validations = [json.loads(p.read_text()) for p in root.rglob('validation.json')]
        assert any(not item['valid'] for item in validations)
        assert any(item['valid'] for item in validations)
        assert list(root.rglob('assessment.json')) and list(root.rglob('record.json'))
        assert (root.parent / 'README.md').is_file()
        assert all('evaluation_context' in json.loads(p.read_text()) for p in root.rglob('record.json'))
    finally:
        await service.close()
