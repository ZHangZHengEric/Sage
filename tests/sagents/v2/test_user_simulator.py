"""Offline user protocol, isolated worker, and official tau request parity."""
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sagents.v2.optimization.contracts import OptimizationCase
from sagents.v2.optimization.user_simulator import (
    UserSimulationReply, UserSimulationRequest, UserSimulatorDescriptor,
)
from sagents.v2.optimization.python_user_simulator import PythonUserSimulator, UserSimulationExecutionError

CONTINUE = {'can_continue': True, 'message': 'Refund to the original payment method.', 'rationale': 'Known preference'}
STOP = {'can_continue': False, 'message': '', 'stop_reason': 'completed', 'rationale': 'No more requests'}


def request(**updates):
    data = {'case': {'id': 'user-test', 'split': 'training', 'input': 'Please help.', 'user_context': 'Known facts'},
        'conversation': [{'role': 'user', 'content': 'Please help.'}, {'role': 'assistant', 'content': 'How?'}],
        'turns_remaining': 2}
    return UserSimulationRequest.model_validate({**data, **updates})


def source(body=None):
    return ('import json\n'
        f'CONTINUE = {CONTINUE!r}\nSTOP = {STOP!r}\n'
        + (body or "def reply(request):\n    return STOP if request['state'].get('done') else CONTINUE\n")
        + '\nUSER_SIMULATOR_TEST_CASES = ' + repr([
            {'request': request().model_dump(mode='json'), 'expected_reply': CONTINUE},
            {'request': request(state={'done': True}).model_dump(mode='json'), 'expected_reply': STOP},
        ]) + '\n')


def worker(tmp_path, code, **kwargs):
    path = tmp_path / 'user.py'
    path.write_text(code)
    return PythonUserSimulator(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        descriptor=UserSimulatorDescriptor(id='offline-user', name='Offline', version='1'), **kwargs)


def test_only_visible_input_and_user_context_are_passed():
    case = OptimizationCase(id='case', input='Public question', user_context='User facts',
        rubric='SECRET RUBRIC', reference_answer='SECRET ANSWER',
        environment_context={'password': 'SECRET ENV'})
    visible = UserSimulationRequest.from_dialogue(case, {'conversation': [
        {'role': 'assistant', 'content': 'Public reply'}], 'turns_remaining': 2, 'rubric': 'SECRET RUBRIC'}, 2)
    assert 'SECRET' not in visible.model_dump_json()
    assert visible.trial == 2
    with pytest.raises(ValidationError):
        request(conversation=[{'role': 'tool', 'content': 'Private tool output'}])


@pytest.mark.parametrize('bad', [
    {**CONTINUE, 'message': ' '}, {**CONTINUE, 'can_continue': 'true'},
    {**CONTINUE, 'stop_reason': 'completed'}, {**STOP, 'stop_reason': None},
    {**STOP, 'stop_reason': 'passed'}, {**STOP, 'rationale': ' '},
    {**STOP, 'score': 1}, {**STOP, 'state': {'x': 'x' * 65536}},
])
def test_invalid_decisions_fail_closed(bad):
    with pytest.raises(ValidationError):
        UserSimulationReply.model_validate(bad, strict=True)


@pytest.mark.asyncio
async def test_python_function_contract_and_per_call_state(tmp_path):
    user = worker(tmp_path, source())
    validation = await user.validate()
    assert validation['status'] == 'passed' and validation['cases'] == 2
    assert (await user.reply(request())).can_continue
    assert not (await user.reply(request(state={'done': True}))).can_continue
    assert (await user.reply(request())).can_continue  # No cross-trial state.
    user.path.write_text(source() + '\n# mutated\n')
    with pytest.raises(UserSimulationExecutionError, match='source changed'):
        await user.reply(request())


@pytest.mark.asyncio
async def test_async_base_class_entrypoint(tmp_path):
    code = source('''from sagents.v2.optimization.user_simulator import UserSimulator, UserSimulationReply
class CustomUser(UserSimulator):
    async def reply(self, request):
        return UserSimulationReply.model_validate(STOP if request.state.get('done') else CONTINUE)
USER_SIMULATOR = CustomUser()
''')
    user = worker(tmp_path, code)
    assert (await user.validate())['cases'] == 2
    assert (await user.reply(request())).message == CONTINUE['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    "def reply(request):\n    return {'can_continue': True, 'message': ' ', 'rationale': 'Bad'}\n",
    "def reply(request):\n    raise RuntimeError('PRIVATE INTERNAL TEXT')\n",
])
async def test_invalid_user_code_never_becomes_a_stop_or_score(tmp_path, body):
    user = worker(tmp_path, source(body))
    with pytest.raises(UserSimulationExecutionError) as error:
        await user.reply(request())
    assert error.value.rsi_requires_feedback and 'PRIVATE INTERNAL TEXT' not in str(error.value)
    with pytest.raises(UserSimulationExecutionError):
        await user.validate()


@pytest.mark.asyncio
async def test_import_requires_continue_and_stop_and_has_no_live_model(tmp_path, monkeypatch):
    monkeypatch.setenv('SAGE_RSI_SCORER_MODEL_API', 'ambient-credential-must-not-be-used')
    code = source().replace("STOP if request['state'].get('done') else CONTINUE", 'CONTINUE')
    user = worker(tmp_path, code)
    with pytest.raises(UserSimulationExecutionError, match='expected_reply'):
        await user.validate()
    code = source('''from sagents.v2.optimization.user_simulator_runtime import get_model_provider
def reply(request):
    get_model_provider()
    return CONTINUE
''')
    with pytest.raises(UserSimulationExecutionError, match='No user simulator model API'):
        await worker(tmp_path, code).validate()


@pytest.mark.asyncio
async def test_timeout_kills_worker(tmp_path):
    user = worker(tmp_path, source('def reply(request):\n    import time\n    time.sleep(10)\n'), timeout=.2)
    with pytest.raises(TimeoutError):
        await user.reply(request())


@pytest.mark.asyncio
async def test_builtin_user_uses_provider_and_strict_schema_without_hidden_context():
    from sagents.v2.optimization.default_user_simulator import DefaultUserSimulator
    from sagents.v2.optimization.scorer_runtime import _test_model
    provider = _test_model([{'response_id': 'offline', 'text': json.dumps(STOP), 'finish_reason': 'stop'}])
    @asynccontextmanager
    async def factory(value):
        assert value == request()
        yield provider
    user = DefaultUserSimulator(factory)
    assert (await user.reply(request())).stop_reason == 'completed'
    call = provider.requests[0]
    payload = json.loads(call.messages[-1].content[0].text)
    assert payload['response_schema']['title'] == 'UserSimulationReply'
    assert payload['data']['case']['user_context'] == 'Known facts'
    assert not call.tools and call.response_schema is None


@pytest.mark.asyncio
async def test_tau_upload_self_tests_and_exact_official_prompt_roles(tmp_path):
    from evaluation_datasets.tau_bench import user_simulator as tau
    from sagents.v2.optimization.scorer_runtime import _test_model, _TEST_MODEL
    tau.activate()
    from tau2.data_model.tasks import UserScenario
    from tau2.data_model.message import AssistantMessage, UserMessage
    from tau2.user.user_simulator import UserSimulator
    # Local imports call activate in official_messages, before using tau2.
    data = tau._REQUEST
    messages = tau.official_messages(data)
    official = UserSimulator(llm='fixture', instructions=str(UserScenario.model_validate(tau._SCENARIO)))
    state = official.get_init_state([UserMessage(role='user', content='Hello.')])
    model_requests = []
    import tau2.user.user_simulator as official_module
    original_generate = official_module.generate
    def capture(**kwargs):
        model_requests.append(kwargs)
        return AssistantMessage(role='assistant', content='###STOP###')
    official_module.generate = capture
    try:
        official.generate_next_message(AssistantMessage(role='assistant', content='How can I help?'), state)
    finally:
        official_module.generate = original_generate
    expected = model_requests[0]['messages']
    assert [(m.role, m.content[0].text) for m in messages] == [(m.role, m.content) for m in expected]
    provider = _test_model([{'response_id': 'fixture', 'text': '###STOP###', 'finish_reason': 'stop'}])
    token = _TEST_MODEL.set(provider)
    try:
        assert (await tau.reply(data))['stop_reason'] == 'completed'
    finally:
        _TEST_MODEL.reset(token)
    native = provider.requests[0]
    assert native.temperature == 0 and not native.tools and native.response_schema is None
    assert 'can_continue' not in native.messages[0].content[0].text
    root = Path(tau.__file__)
    user = worker(tmp_path, root.read_text())  # Same source as the uploaded file, not its original path.
    report = await user.validate()
    assert report['status'] == 'passed' and report['cases'] == 4
    assert any('simulation_guidelines.md' in name for name in user.dependency_manifest['files'])


@pytest.mark.asyncio
@pytest.mark.parametrize('human', [False, True])
async def test_plugin_state_is_local_to_case_trial_and_stopping_reaches_scorer(human):
    import asyncio
    from sagents.v2.optimization.contracts import OptimizationAgent
    from sagents.v2.optimization.observer import IsolatedTestEvaluator
    from sagents.v2.optimization.user_simulator import UserSimulator
    from tests.sagents.v2.test_dialogue_diagnosis_timing import Runner, EarlyPassScorer
    from tests.sagents.v2.test_dialogue_integrity import dialogues
    from tests.sagents.v2.test_package_optimizer import bundle, context, optimizer, suite
    class User(UserSimulator):
        descriptor = UserSimulatorDescriptor(id='fixed', name='Fixed', version='1')
        def __init__(self): self.calls = []
        async def reply(self, value):
            await asyncio.sleep(0)
            self.calls.append(value)
            if value.state:
                return UserSimulationReply(**{**STOP, 'stop_reason': 'transferred'})
            return UserSimulationReply(**CONTINUE, state={'done': True})
    class Scorer(EarlyPassScorer):
        def __init__(self):
            super().__init__()
            self.reasons = []
        async def score(self, value):
            self.reasons.append(value.dialogue_stop_reason)
            return await super().score(value)
    user, scorer, runner = User(), Scorer(), Runner()
    if human:
        role = OptimizationAgent(package=bundle('evaluator'), agent_id='assistant')
        measure = IsolatedTestEvaluator(runner=runner, evaluator=role, driver=role,
            context=context(), goal='Fixture', scorer=scorer, user_simulator=user)
        await asyncio.gather(*(measure(bundle(), c) for c in dialogues().cases))
        calls = len(user.calls)
        await measure(bundle(), suite().cases[0])
        assert len(user.calls) == calls  # Single-turn bypasses simulator entirely.
        assert scorer.reasons[:-1] == ['user_transferred'] * (len(scorer.reasons) - 1)
    else:
        opt = optimizer(runner)
        opt.user_simulator = user
        result = await opt.optimize(bundle(), context=context(), goal='Fixture', suite=dialogues(),
            rounds=1, validation_case_count=1, grow_training=False, final_max_cases=0,
            scorer=scorer, evaluation_repeats=2)
        assert all(len(t.dialogue) == 2 for c in result.report.baseline.cases for t in c.trials)
        assert set(scorer.reasons) == {'user_transferred'}
    assert user.calls and all(c.state in ({}, {'done': True}) for c in user.calls)
    for c in user.calls:
        assert c.state == ({} if len(c.conversation) == 2 else {'done': True})


@pytest.mark.asyncio
async def test_builtin_repairs_only_invalid_decisions_and_never_reexecutes_target():
    from sagents.v2.optimization.default_user_simulator import DefaultUserSimulator
    from sagents.v2.optimization.scorer_runtime import _test_model
    provider = _test_model([
        {'response_id': 'bad', 'text': '{}', 'finish_reason': 'stop'},
        {'response_id': 'fixed', 'text': json.dumps(STOP), 'finish_reason': 'stop'}])
    @asynccontextmanager
    async def factory(value):
        yield provider
    assert not (await DefaultUserSimulator(factory).reply(request())).can_continue
    assert len(provider.requests) == 2
    assert provider.requests[0].messages == provider.requests[1].messages[:2]


@pytest.mark.asyncio
async def test_generated_cases_request_opening_background_and_explicit_conversation_mode():
    from sagents.v2 import AgentPackageTestGenerator
    from sagents.v2.optimization.contracts import OptimizationAgent
    from tests.sagents.v2.test_package_optimizer import Runner, bundle, context
    runner = Runner()
    generator = AgentPackageTestGenerator(runner=runner,
        designer=OptimizationAgent(package=bundle('evaluator'), agent_id='assistant'))
    generated = await generator.generate_with_record(bundle(), context=context(), max_cases=2)
    payload = json.loads(generated.call.request)
    text = payload['task']
    assert 'actual first user message' in text and 'Always explicitly set mode' in text
    assert 'dialogue_completion=user' in text and 'user_context' in text
    assert not runner.target_hashes
