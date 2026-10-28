"""Default/custom simulated users share one frozen host configuration."""
import json

import pytest
from pydantic import ValidationError

from app.v2.desktop.backend.rsi import RsiStart
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.optimization.contracts import OptimizationCase, OptimizationTestSuite
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request


@pytest.mark.parametrize('custom', [None, 'Ask for one fact at a time. Never change the supplied goal.'])
@pytest.mark.asyncio
async def test_host_uses_same_default_or_custom_user_for_all_splits(tmp_path, monkeypatch, custom):
    class Script(RsiModel):
        users = []
        async def _stream(self, request):
            messages = [m for m in request.messages if m.role == 'user']
            raw = ''.join(getattr(b, 'text', '') for b in messages[-1].content)
            if '<user_request>' in raw:
                raw = raw.split('<user_request>', 1)[1].rsplit('</user_request>', 1)[0].strip()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}
            if payload.get('response_schema', {}).get('title') == 'UserSimulationReply':
                self.users.append(request)
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='offline-user', text=json.dumps({'can_continue': False,
                        'message': '', 'stop_reason': 'completed', 'rationale': 'Scenario completed'}), finish_reason='stop'))
                return
            async for event in super()._stream(request):
                yield event
    model = Script()
    model.users = []
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        request = start_request()
        cases = tuple(c.model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user',
            'user_context': 'Only supplied facts.', 'max_turns': 2}) for c in request.suite.cases)
        request = request.model_copy(update={'rounds': 1, 'grow_training': False,
            'user_simulator_instructions': custom, 'suite': request.suite.model_copy(update={'cases': cases}),
            'human_test_suite': OptimizationTestSuite(cases=(OptimizationCase(id='human', input='PRIVATE QUESTION',
                rubric='PRIVATE RUBRIC', user_context='PRIVATE FACTS', split='test', mode='dialogue',
                dialogue_completion='user', max_turns=2),))})
        run = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[run['id']]
        final = await service.rsi_run(agent, run['id'], 'alice')
        assert final['status'] == 'completed', final.get('error_type')
        assert final['user_simulator'] == {'mode': 'custom' if custom else 'default'}
        assert final['user_simulator_instructions'] == custom
        assert model.users and len(model.users) >= 3
        for call in model.users:
            system = '\n'.join(getattr(b, 'text', '') for m in call.messages if m.role == 'system' for b in m.content)
            assert 'internal tool results, scores' in system
            assert (custom in system) if custom else ('User simulation instructions:' not in system)
        with service.rsi_store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM records WHERE kind="run"').fetchone()[0] == 1
        assert all(r['status'] == 'completed' for r in final['test_observations'])
    finally:
        await service.close()


def test_explicit_blank_user_policy_is_invalid_but_omitting_it_keeps_default():
    assert RsiStart(goal='Test', request_id='default').user_simulator_instructions is None
    with pytest.raises(ValidationError, match='user_simulator_instructions'):
        RsiStart(goal='Test', request_id='blank', user_simulator_instructions='   ')


@pytest.mark.asyncio
async def test_imported_user_is_owner_scoped_frozen_and_independently_selected(tmp_path, monkeypatch):
    from pathlib import Path
    from app.v2.desktop.backend.rsi_user_simulator import UserSimulatorImport
    from tests.sagents.v2.test_user_simulator import source
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        module = UserSimulatorImport(name='user.py', source=source())
        first = await service.import_rsi_user_simulator(agent, module, 'alice')
        assert first == await service.import_rsi_user_simulator(agent, module, 'alice')
        changed = await service.import_rsi_user_simulator(agent,
            module.model_copy(update={'source': source() + '\n# version 2\n'}), 'alice')
        assert first['id'] != changed['id']
        history = await service.rsi_history(agent, 'alice')
        assert history['user_simulators'] == [changed, first]
        assert all('path' not in m and 'dependency_manifest' not in m and 'source' not in m for m in history['user_simulators'])
        request = RsiStart(goal='Test', request_id='user', user_simulator_id=first['id'])
        selection = service._rsi_user_simulator_selection(request, 'alice', agent)
        assert selection['binding_hash'] == first['validation']['dependency_binding']
        for user, target in [('bob', agent), ('alice', 'another-agent')]:
            with pytest.raises(ValueError):
                service._rsi_user_simulator_selection(request, user, target)
        with pytest.raises(ValueError, match='choose a Python'):
            service._rsi_user_simulator_selection(request.model_copy(update={'user_simulator_instructions': 'extra'}), 'alice', agent)
        with pytest.raises(ValueError, match='binding changed'):
            service._rsi_user_simulator_selection(request.model_copy(update={'user_simulator_binding_id': 'wrong'}), 'alice', agent)
        Path(selection['path']).write_text('# modified frozen source')
        with pytest.raises(ValueError, match='source changed'):
            service._rsi_user_simulator_selection(request, 'alice', agent)
        with pytest.raises(ValueError):
            await service.import_rsi_user_simulator(agent,
                UserSimulatorImport(name='bad.py', source='def reply(request):\n return {}\n'), 'alice')
        assert not service._rsi_tasks  # No RSI run is started by importing/validation.
    finally:
        await service.close()


@pytest.mark.parametrize('code', ['x = 1', 'def score(request): pass', 'not python!',
    'def reply(request): pass\nUSER_SIMULATOR = object()'])
def test_upload_requires_exactly_one_user_entrypoint(code):
    from app.v2.desktop.backend.rsi_user_simulator import UserSimulatorImport
    with pytest.raises(ValidationError):
        UserSimulatorImport(name='bad.py', source=code)


@pytest.mark.asyncio
async def test_uploaded_python_is_used_by_native_training_dev_and_human_test(tmp_path, monkeypatch):
    from app.v2.desktop.backend.rsi_user_simulator import UserSimulatorImport
    from tests.sagents.v2.test_user_simulator import source, CONTINUE
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        code = source().replace(repr(CONTINUE), repr({**CONTINUE, 'state': {'done': True}}))
        module = await service.import_rsi_user_simulator(agent, UserSimulatorImport(name='user.py', source=code), 'alice')
        options = start_request()
        cases = tuple(c.model_copy(update={'mode': 'dialogue', 'dialogue_completion': 'user',
            'max_turns': 3}) for c in options.suite.cases)
        options = options.model_copy(update={'rounds': 1, 'grow_training': False,
            'user_simulator_id': module['id'], 'suite': options.suite.model_copy(update={'cases': cases}),
            'human_test_suite': OptimizationTestSuite(cases=(OptimizationCase(id='human-user', input='Private user question',
                user_context='Private user background', rubric='42', split='test', mode='dialogue',
                dialogue_completion='user', max_turns=3),))})
        admitted = await service.start_rsi(agent, options, 'alice')
        await service._rsi_tasks[admitted['id']]
        result = await service.rsi_run(agent, admitted['id'], 'alice')
        assert result['status'] == 'completed', result.get('error_type')
        assert result['user_simulator']['mode'] == 'python'
        assert result['user_simulator']['id'] == module['id']
        assert result['user_simulator_id'] == module['id']
        assert all(len(c['dialogue']) == 2 and c['stop_reason'] == 'user_finished'
            for c in result['result']['report']['baseline']['cases'])
        assert result['test_observations'] and all(r['status'] == 'completed' for r in result['test_observations'])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_imported_user_persists_selected_python_and_rejects_runtime_rebinding(tmp_path, monkeypatch):
    import sys
    from app.v2.desktop.backend.rsi_user_simulator import UserSimulatorImport
    from sagents.v2.optimization.python_user_simulator import PythonUserSimulator
    from tests.sagents.v2.test_user_simulator import source, request as simulation_request
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        module = UserSimulatorImport(name='user.py', source=source())
        host = await service.import_rsi_user_simulator(agent, module, 'alice')
        selected = await service.import_rsi_user_simulator(agent,
            module.model_copy(update={'python_executable': sys.executable}), 'alice')
        assert host['id'] != selected['id']
        selection_request = RsiStart(goal='Test', request_id='selected', user_simulator_id=selected['id'])
        stored = service._rsi_user_simulator_selection(selection_request, 'alice', agent)
        assert stored['python_executable'] == sys.executable
        assert stored['dependency_manifest']['environment']['executable'] == sys.executable
        runtime = PythonUserSimulator(path=stored['path'], source_hash=stored['source_hash'],
            descriptor=stored['descriptor'], dependency_manifest=stored['dependency_manifest'],
            python_executable=stored['python_executable'])
        assert (await runtime.reply(simulation_request())).can_continue
        assert 'python_executable' not in selected
        stored['python_executable'] = '/different/python'
        service.rsi_store.put(stored, 'alice', agent, 'user_simulator')
        with pytest.raises(ValueError, match='Python runtime changed'):
            service._rsi_user_simulator_selection(selection_request, 'alice', agent)
    finally:
        await service.close()
