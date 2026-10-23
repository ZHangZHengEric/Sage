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
        assert list(root.rglob('assessment.json')) and list(root.rglob('context.json'))
        assert (root.parent / 'README.md').is_file()
        assert all('evaluation_context' in json.loads(p.read_text()) for p in root.rglob('context.json'))
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('interruption', ['none', 'main', 'human_evaluation', 'human_execution', 'human_scoring', 'main_loop', 'human_loop', 'main_partial', 'main_artifact_loop', 'human_artifact_loop', 'main_artifact_missing_receipt', 'human_artifact_missing_receipt', 'main_artifact_invalid_json', 'human_artifact_invalid_json'])
async def test_user_completed_dialogues_score_once_in_native_train_dev_and_human_test(tmp_path, monkeypatch, interruption):
    import asyncio
    from sagents.v2 import IsolatedOptimizationRunner
    from sagents.v2.optimization.runner import OPTIMIZATION_CASE, _NativeConversation
    from sagents.v2.optimization.recovery import OptimizationTransientFailure
    from sagents.v2.optimization.contracts import OptimizationObservation
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    from sagents.v2.optimization.contracts import OptimizationTestSuite
    from sagents.v2.optimization.python_scorer import PythonExecutionScorer
    from tests.sagents.v2.test_optimization_diagnostics import diagnosis

    class Model(RsiModel):
        async def _stream(self, request):
            raw = ''.join(getattr(b, 'text', '') for m in request.messages if m.role == 'user' for b in m.content)
            if '<user_request>' in raw:
                raw = raw.rsplit('<user_request>', 1)[1].split('</user_request>', 1)[0].strip()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            title = payload.get('response_schema', {}).get('title')
            if title == 'OptimizationDialogueReply':
                continuation = len(payload['data']['conversation']) < 4
                value = {'can_continue': continuation, 'message': 'Please verify the arithmetic.' if continuation else '',
                    'rationale': 'Follow-up verification requested' if continuation else 'Scenario complete'}
            elif title == 'OptimizationDiagnosis':
                value = diagnosis()
            elif title == 'OptimizationDiagnosisSummary':
                value = {'summary': 'Preserve the fixed scorer score and verify arithmetic.', 'priorities': []}
            else:
                if title is None:
                    target_calls.append(raw)
                async for event in super()._stream(request):
                    yield event
                return
            response = authored_evaluation_response(request, payload, value)
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response or ModelResponse(
                response_id='analysis', text=json.dumps(value), finish_reason='stop'))

    histories, target_calls, failures = [], [], []
    evaluation_invocations = []
    baseline_scored = asyncio.Event()
    original = PythonExecutionScorer.score
    async def measured(scorer, request):
        if interruption == 'human_scoring' and request.case.split == 'test' and not failures:
            failures.append(True)
            raise OptimizationTransientFailure('Scorer model transport interrupted')
        result = await original(scorer, request)
        histories.append(len(request.conversation))
        if len(histories) >= 2:
            baseline_scored.set()
        return result
    monkeypatch.setattr(PythonExecutionScorer, 'score', measured)
    original_run = IsolatedOptimizationRunner.run
    async def interrupted(runner, package, selected, content, context):
        case = OPTIMIZATION_CASE.get()
        if case is not None and package.manifest.metadata.id == 'desktop.rsi.evaluator':
            evaluation_invocations.append(case.split)
        selected_failure = (case is not None and ((interruption in {'main', 'main_loop'} and case.split != 'test')
                            or (interruption in {'human_evaluation', 'human_loop'} and case.split == 'test')))
        if selected_failure and package.manifest.metadata.id == 'desktop.rsi.evaluator':
            await baseline_scored.wait()
            if not failures:
                failures.append(True)
                if interruption.endswith('_loop'):
                    return OptimizationObservation(state='suspended', evidence={'runtime_events': [
                        {'type': 'interaction.requested', 'data': {'interaction_type': 'user_input', 'payload': {
                            'reason_code': 'loop.repeated_pattern'}}}]})
                return OptimizationObservation(state='suspended', evidence={'runtime_events': [
                    {'type': 'interaction.requested', 'data': {'payload': {'error': {
                        'code': 'model.stream_incomplete', 'category': 'provider_transient', 'retryable': True}}}}]})
        return await original_run(runner, package, selected, content, context)
    monkeypatch.setattr(IsolatedOptimizationRunner, 'run', interrupted)
    original_send = _NativeConversation.send
    async def interrupted_send(session, content):
        case = OPTIMIZATION_CASE.get()
        if (interruption == 'main_partial' and case is not None and case.split == 'training'
                and session.session_id is not None and not failures
                and not session.package.manifest.metadata.id.startswith('desktop.rsi.')):
            failures.append(True)
            return OptimizationObservation(state='failed', evidence={'error': {
                'code': 'model.provider_transient', 'category': 'provider_transient', 'retryable': True}})
        if (interruption == 'human_execution' and case is not None and case.split == 'test'
                and not session.package.manifest.metadata.id.startswith('desktop.rsi.') and not failures):
            failures.append(True)
            return OptimizationObservation(state='failed', evidence={'error': {
                'code': 'model.provider_transient', 'category': 'provider_transient', 'retryable': True}})
        observation = await original_send(session, content)
        if (interruption.startswith(('main_artifact', 'human_artifact')) and case is not None
                and session.package.manifest.metadata.id == 'desktop.rsi.evaluator' and not failures
                and ((interruption.startswith('main_artifact') and case.split != 'test')
                    or (interruption.startswith('human_artifact') and case.split == 'test'))):
            failures.append(True)
            evidence = dict(observation.evidence)
            canonical = evidence.pop('final_items', [])
            evidence['runtime_events'] = [*evidence.get('runtime_events', []),
                *[{'type': 'item.completed', 'data': {'item': row}} for row in canonical],
                {'type': 'interaction.requested', 'data': {'interaction_type': 'user_input',
                    'payload': {'reason_code': 'loop.repeated_pattern'}}}]
            if interruption.endswith('missing_receipt'):
                evidence['runtime_events'] = [event for event in evidence['runtime_events']
                    if not (event.get('type') == 'item.completed'
                        and event.get('data', {}).get('item', {}).get('data', {}).get('kind') == 'tool_result')]
            if interruption.endswith('invalid_json'):
                (session.workspace/'evaluation/assessment.json').write_text('{}')
            return observation.model_copy(update={'state': 'suspended', 'evidence': evidence})
        return observation
    monkeypatch.setattr(_NativeConversation, 'send', interrupted_send)
    service, agent = await setup_service(tmp_path, monkeypatch, Model())
    async def retry_wait(seconds):
        pass
    monkeypatch.setattr(service, '_rsi_retry_wait', retry_wait)
    try:
        source = "def score(request):\n return {'score': .75, 'passed': True, 'rationale': 'Fixed scorer'}\n"
        source += 'SCORER_TEST_CASES = ' + repr([{'request': scoring_request().model_dump(mode='json'),
            'expected_score': .75, 'expected_passed': True}])
        imported = await service.import_rsi_scorer(agent, ScorerImport(name='final-score.py', source=source), 'alice')
        request = start_request()
        cases = tuple(case.model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user', 'max_turns': 3,
            'user_context': 'Ask for arithmetic verification, then finish.'}) for case in request.suite.cases)
        hidden = cases[0].model_copy(update={'id': 'human-only', 'split': 'test',
            'input': 'Check the arithmetic.', 'user_context': 'PRIVATE HUMAN TEST SCENARIO: ask for verification, then finish.'})
        request = request.model_copy(update={'rounds': 1, 'grow_training': False, 'scorer_id': imported['id'],
            'suite': request.suite.model_copy(update={'cases': cases}),
            'max_concurrency': 1 if interruption == 'main_partial' else request.max_concurrency,
            'human_test_count': 1, 'human_test_suite': OptimizationTestSuite(cases=(hidden,))})
        started = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error_type')
        assert len(histories) == 6 and set(histories) == {2}
        assert run.get('automatic_recoveries', 0) == 0
        # main_partial fails a target send after its first successful turn.
        # Only that disposable case reopens; other cases and saved scores stay intact.
        assert len(target_calls) == (13 if interruption == 'main_partial' else 12)
        if 'artifact' in interruption:
            assert len(evaluation_invocations) == (7 if interruption.endswith(('missing_receipt', 'invalid_json')) else 6)
        for case in run['result']['report']['baseline']['cases']:
            assert len(case['dialogue']) == 2
            assert case['dialogue'][0]['grade'] is None
            assert case['dialogue'][1]['grade']['score'] == .75
            assert case['grade']['diagnosis']
        assert all(record['status'] == 'completed' for record in run['test_observations'])
        if interruption.startswith('human_') and interruption != 'human_loop' and not interruption.startswith('human_artifact'):
            phase = interruption.removeprefix('human_')
            trial = run['test_observations'][0]['cases'][0]['trials'][0]
            assert trial['infrastructure_retries'][phase] == 1
        assert 'PRIVATE HUMAN TEST SCENARIO' not in json.dumps(run['result']['report']['agent_calls'])
    finally:
        await service.close()
