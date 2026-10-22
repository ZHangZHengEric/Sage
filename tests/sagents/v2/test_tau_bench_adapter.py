"""Optional τ-bench integration tests; install the pinned benchmark separately."""

import asyncio
import json
import os

import pytest

from examples.v2.optimizer_tau_bench import partition_tasks, task_case
from examples.v2.tau_bench_report import inspect_tuning_request, paired_scores


def test_partitions_are_reproducible_and_holdout_is_disjoint():
    splits = {"train": [str(i) for i in range(20)], "test": [str(i) for i in range(20, 25)]}
    kwargs = dict(seed=17, initial_count=3, validation_count=2, test_count=0)
    parts = partition_tasks(splits, **kwargs)
    assert parts == partition_tasks(splits, **kwargs)
    sets = [set(v) for v in parts.values()]
    assert sum(map(len, sets)) == len(set.union(*sets)) == 25
    assert len(parts["test"]) == 5
    assert json.loads(task_case("13", "training").input) == {"tau_task_id": "13"}
    with pytest.raises(ValueError, match="overlap"):
        partition_tasks({"train": ["1", "2", "3"], "test": ["1"]}, **kwargs)


def test_tuning_audit_rejects_hidden_cases_and_feedback():
    import copy
    summary = {"score": 0.5, "passed": 1, "total": 2,
               "items": [{"index": 1, "score": 1}, {"index": 2, "score": 0}]}
    request = {"data": {"validation": summary, "validation_history": [{"round": 1, **summary}],
                        "training": [{"case": {"input": '{"tau_task_id": "train-one"}'}}]}}
    val = '{"tau_task_id": "hidden-val"}'
    assert inspect_tuning_request(request, [val], ["heldout"])
    leaked = copy.deepcopy(request)
    leaked["data"]["training"].append({"case": {"input": val}})
    assert not inspect_tuning_request(leaked, [val], ["heldout"])
    leaked = copy.deepcopy(request)
    leaked["data"]["validation"]["items"][0]["rationale"] = "hidden feedback"
    assert not inspect_tuning_request(leaked, [val], ["heldout"])
    leaked = copy.deepcopy(request)
    leaked["data"]["previous_attempts"] = [{"input": '{"tau_task_id": "heldout"}'}]
    assert not inspect_tuning_request(leaked, [val], ["heldout"])


def test_paired_scores_count_regressions_and_refuse_duplicate_trials():
    rows = [{"phase": "test-" + side, "task": task, "reward": score}
            for side, values in (("baseline", (0, 1, 1, 0)), ("candidate", (1, 0, 1, 1)))
            for task, score in zip(("a", "b", "c", "d"), values)]
    result = paired_scores(rows, ["a", "b", "c", "d"])
    assert result["complete"]
    assert result["delta_percentage_points"] == 25
    assert result["improved_tasks"] == 2 and result["regressed_tasks"] == 1
    with pytest.raises(ValueError, match="duplicate"):
        paired_scores([*rows, rows[0]], ["a", "b", "c", "d"])


def tau():
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    pytest.importorskip("tau2")
    from examples.v2.tau_bench_adapter import TauToolBridge
    return TauToolBridge


@pytest.mark.asyncio
async def test_native_user_input_pause_delivers_question_and_resumes_same_run(tmp_path):
    Bridge = tau()
    from tau2.data_model.message import UserMessage
    from examples.v2.optimizer_tau_bench import package
    from examples.v2.host.registrations import provided, runtime_for
    from sagents.v2 import IsolatedOptimizationRunner, ApplicationConfiguration
    from sagents.v2.contracts.principals import ActorRef, RequestContext
    from sagents.v2.model.contracts import ModelToolCall, ModelResponse, ModelStreamEvent
    from tests.sagents.v2.test_standard_execution_configuration import response
    from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
    from tests.sagents.v2.model_fixture import TEST_MODELS
    from app.v2.desktop.backend.catalog import default_agent_config
    from sagents.v2.tool.provider import ToolProvider
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy

    model = ScriptedModelProvider((
        ScriptedModelStep(events=(ModelStreamEvent(kind='completed', response=ModelResponse(
            response_id='question', text='Which color?', finish_reason='tool_calls',
            tool_calls=(ModelToolCall(tool_call_id='ask', name='turn_status',
                arguments={'status': 'need_user_input', 'note': 'Choose a color.'}),),
        )),)),
        response(text='Selected blue.'),
        response(text='Anything else?'),
    ))

    def factory(bundle, root, context):
        runtime = runtime_for(root / 'state', bundle.manifest.runtime, capabilities={
                'model.provider': {'plugin': 'tau.pause.model'},
                'agent.tool-policy': {'plugin': 'tau.pause.policy'},
                'tool.selection-policy': {'plugin': 'sage.tool-selection.direct'},
                'execution.binding': {'plugin': 'sage.execution.binding.local-workspace',
                    'config': {'workspace': str(root / 'work'), 'policy': {'process': {'enabled': False}}}},
            })
        runtime = runtime.model_copy(update={'capabilities': {**runtime.capabilities,
            'tool.provider': (CapabilitySelection(plugin='sage.tool.official'), CapabilitySelection(plugin='tau.pause.tools'))}})
        return ApplicationConfiguration((
            provided('tau.pause.model', lambda ctx, deps: model, 'model.provider'),
            provided('tau.pause.tools', lambda ctx, deps: ToolProvider(bridge, bridge), 'tool.provider'),
            provided('tau.pause.policy', lambda ctx, deps: DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE), 'agent.tool-policy'),
        ), runtime, TEST_MODELS)

    async def authorize(*args):
        pass

    runner = IsolatedOptimizationRunner(builder_factory=factory, authorize=authorize,
        root=tmp_path, resume_user_input=True)
    context = RequestContext(actor=ActorRef(principal_id='tester', principal_type='user'))
    bridge = Bridge([])
    async with runner.conversation(package('test.pause', 'Ask a question', default_agent_config()['availableTools']), 'assistant', context) as session:
        first = await bridge.advance(session, UserMessage(role='user', content='Choose my color'), [])
        assert first.content == 'Which color?'
        assert bridge.observations[0].state == 'suspended'
        second = await bridge.advance(session, UserMessage(role='user', content='Blue'), [])
        assert second.content == 'Selected blue.'
        assert bridge.observations[1].state == 'completed'
        assert bridge.observations[0].evidence['run_id'] == bridge.observations[1].evidence['run_id']
        assert any(m.role == 'user' and any('Blue' in (getattr(b, 'text', '') or '') for b in m.content)
                   for m in model.requests[1].messages)
        third = await bridge.advance(session, UserMessage(role='user', content='Thanks'), [])
        assert third.content == 'Anything else?'
        assert bridge.observations[2].evidence['run_id'] != bridge.observations[1].evidence['run_id']
        assert bridge.observations[2].evidence['session_id'] == bridge.observations[1].evidence['session_id']
    await bridge.close()


@pytest.mark.asyncio
async def test_adapter_does_not_treat_approval_or_empty_pause_as_user_question():
    Bridge = tau()
    from tau2.data_model.message import UserMessage
    from sagents.v2.optimization.contracts import OptimizationObservation
    for evidence, output in (({}, 'Approval required'), ({'awaiting_user_input': True}, '')):
        class Session:
            async def send(self, content):
                return OptimizationObservation(state='suspended', output=output, evidence=evidence)
        bridge = Bridge([])
        with pytest.raises(RuntimeError, match='suspended'):
            await bridge.advance(Session(), UserMessage(role='user', content='Continue'), [])
        await bridge.close()


@pytest.mark.asyncio
async def test_domain_call_waits_for_official_result_without_mutating_twice():
    Bridge = tau()
    from tau2.environment.tool import Tool
    from tau2.data_model.message import ToolMessage, UserMessage
    from sagents.v2.tool.contracts import ToolCall
    from sagents.v2.optimization.contracts import OptimizationObservation
    mutations = []

    def mutate(value: str) -> str:
        """Record the requested value."""
        mutations.append(value)
        return value

    bridge = Bridge([Tool(mutate)])
    call = ToolCall(tool_call_id="call-1", tool_name="mutate", arguments={"value": "yes"},
                    operation_id="op-1", idempotency_key="idem-1", owner_run_id="run-1")

    class Session:
        async def send(self, content):
            result = await bridge.execute(call, None)
            assert result.content[0].text == '"yes"'
            return OptimizationObservation(state="completed", output="Done")

    message = await bridge.advance(Session(), UserMessage(role="user", content="start"), [])
    assert mutations == []
    tc = message.tool_calls[0]
    # This is the official environment side of the transport boundary.
    value = mutate(**tc.arguments)
    result = await bridge.advance(Session(), ToolMessage(role="tool", id=tc.id,
        content=json.dumps(value), requestor="assistant", error=False), [])
    assert result.content == "Done"
    assert mutations == ["yes"]
    assert not bridge.pending
    await bridge.close()


@pytest.mark.asyncio
async def test_sage_native_runtime_and_domain_transport_share_one_tool_ledger(tmp_path):
    Bridge = tau()
    from tau2.environment.tool import Tool
    from tau2.data_model.message import ToolMessage, UserMessage
    from examples.v2.optimizer_tau_bench import package
    from examples.v2.host.registrations import provided, runtime_for
    from sagents.v2 import IsolatedOptimizationRunner, ApplicationConfiguration
    from sagents.v2.contracts.principals import ActorRef, RequestContext
    from sagents.v2.model.contracts import ModelToolCall
    from tests.sagents.v2.test_standard_execution_configuration import response
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from sagents.v2.tool.provider import ToolProvider
    from tests.sagents.v2.model_fixture import TEST_MODELS

    def lookup(user_id: str) -> str:
        """Look up an example user."""
        return user_id

    bridge = Bridge([Tool(lookup)])
    model = ScriptedModelProvider((
        response(ModelToolCall(tool_call_id="native-call", name="lookup", arguments={"user_id": "alice"})),
        response(text="Found Alice"),
    ))

    def factory(bundle, root, context):
        return ApplicationConfiguration((
            provided("tau.test.model", lambda ctx, deps: model, "model.provider"),
            provided("tau.test.tools", lambda ctx, deps: ToolProvider(bridge, bridge), "tool.provider"),
        ), runtime_for(root / "state", capabilities={
            "model.provider": {"plugin": "tau.test.model"},
            "tool.provider": {"plugin": "tau.test.tools"},
            "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
            "execution.binding": {"plugin": "sage.execution.binding.local-workspace", "config": {"workspace": str(root / "work"), "policy": {"process": {"enabled": False}}}},
        }), TEST_MODELS)

    async def authorize(*args):
        pass

    runner = IsolatedOptimizationRunner(builder_factory=factory, authorize=authorize, root=tmp_path)
    context = RequestContext(actor=ActorRef(principal_id="tester", principal_type="user"))
    async with runner.conversation(package("test.tau", "Use lookup", ("lookup",)), "assistant", context) as session:
        outgoing = await bridge.advance(session, UserMessage(role="user", content="Find Alice"), [])
        assert outgoing.tool_calls[0].name == "lookup"
        result = await bridge.advance(session, ToolMessage(role="tool", id="native-call", content='"alice"', requestor="assistant", error=False), [])
        assert result.content == "Found Alice"
        events = bridge.observations[0].evidence["runtime_events"]
        assert any(e["data"].get("tool_name") == "lookup" for e in events)
    await bridge.close()


@pytest.mark.asyncio
async def test_parallel_calls_are_stamped_on_delivery_for_official_replay():
    Bridge = tau()
    from examples.v2.tau_bench_adapter import SageTauAgent
    from tau2.environment.tool import Tool
    from tau2.data_model.message import ToolMessage, UserMessage
    from sagents.v2.tool.contracts import ToolCall
    from sagents.v2.optimization.contracts import OptimizationObservation

    def lookup(value: str) -> str:
        """Look up a value."""
        return value

    bridge = Bridge([Tool(lookup)])

    class Session:
        async def send(self, content):
            await asyncio.gather(*(bridge.execute(ToolCall(tool_call_id=f"c-{i}",
                tool_name="lookup", arguments={"value": str(i)}, operation_id=f"o-{i}",
                idempotency_key=f"i-{i}", owner_run_id="run"), None) for i in range(2)))
            return OptimizationObservation(state="completed", output="done")

    agent = SageTauAgent(bridge=bridge, session=Session(), loop=asyncio.get_running_loop(),
                         domain_policy="policy", tools=[])

    def official_transport():
        state = agent.get_init_state()
        incoming = UserMessage(role="user", content="start")
        trajectory = []
        for _ in range(2):
            outgoing, state = agent.generate_next_message(incoming, state)
            trajectory.append(outgoing)
            tc = outgoing.tool_calls[0]
            incoming = ToolMessage(role="tool", id=tc.id, content='"ok"', requestor="assistant", error=False)
            trajectory.append(incoming)
        final, _ = agent.generate_next_message(incoming, state)
        trajectory.append(final)
        assert sorted(trajectory, key=lambda m: m.timestamp) == trajectory
        assert [m.role for m in trajectory] == ["assistant", "tool", "assistant", "tool", "assistant"]
    await asyncio.to_thread(official_transport)
    await bridge.close()


@pytest.mark.asyncio
async def test_closing_bridge_releases_waiter_and_cancels_domain_call():
    Bridge = tau()
    from tau2.environment.tool import Tool
    from tau2.data_model.message import UserMessage
    from sagents.v2.tool.contracts import ToolCall

    def lookup(value: str) -> str:
        """Look up a value."""
        return value

    bridge = Bridge([Tool(lookup)])

    class Session:
        async def send(self, content):
            return await bridge.execute(ToolCall(tool_call_id="c", tool_name="lookup",
                arguments={"value": "x"}, operation_id="o", idempotency_key="i", owner_run_id="r"), None)

    await bridge.advance(Session(), UserMessage(role="user", content="start"), [])
    await bridge.close()
    assert bridge.turn_task.cancelled()
    assert not bridge.pending
    with pytest.raises(RuntimeError, match="closed"):
        await bridge.advance(Session(), UserMessage(role="user", content="again"), [])


@pytest.mark.asyncio
async def test_actual_host_exposes_default_tools_but_cannot_read_outside_workspace(tmp_path, monkeypatch):
    Bridge = tau()
    from examples.v2.optimizer_tau_bench import CURRENT_BRIDGE, TauExperiment, package
    from app.v2.desktop.backend.catalog import DesktopModelProviderRecord, default_agent_config
    from tau2.domains.retail.environment import get_environment
    from tau2.data_model.message import ToolMessage, UserMessage
    from sagents.v2 import IsolatedOptimizationRunner
    from sagents.v2.contracts.principals import ActorRef, RequestContext
    from sagents.v2.model.contracts import ModelToolCall
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_standard_execution_configuration import response
    secret = "outside-workspace-canary-unchanged"
    outside = tmp_path / "outside.txt"
    outside.write_text(secret)
    tools = get_environment().get_tools()
    bridge = Bridge(tools)
    model = ScriptedModelProvider((
        response(ModelToolCall(tool_call_id="read", name="file_read", arguments={"file_path": str(outside)})),
        response(ModelToolCall(tool_call_id="calc", name="calculate", arguments={"expression": "1+1"})),
        response(text="2"),
    ))
    monkeypatch.setattr("sagents.v2.model.protocols.create_registered_model_provider", lambda *args, **kwargs: model)
    host = object.__new__(TauExperiment)
    host.target_provider = host.teacher_provider = DesktopModelProviderRecord(
        id="test-model", user_id="tester", name="test", model="test", api_key="not-a-real-key",
        base_url="https://gateway.invalid/v1", max_model_len=128000)
    host.target = package("sage.tau.target", "Use tools", (
        *default_agent_config()["availableTools"], *(t.name for t in tools)))
    native = IsolatedOptimizationRunner(builder_factory=host.factory, authorize=host.authorize,
                                        root=tmp_path / "runs")
    context = RequestContext(actor=ActorRef(principal_id="tester", principal_type="user", scopes=("skill.load",)))
    token = CURRENT_BRIDGE.set(bridge)
    try:
        async with native.conversation(host.target, "assistant", context) as session:
            outgoing = await bridge.advance(session, UserMessage(role="user", content="Compute"), [])
            assert outgoing.tool_calls[0].name == "calculate"
            final = await bridge.advance(session, ToolMessage(role="tool", id="calc", content='"2"',
                                         requestor="assistant", error=False), [])
            assert final.content == "2"
        visible = {t.name for t in model.requests[0].tools}
        assert set(default_agent_config()["availableTools"]) <= visible
        assert {t.name for t in tools} <= visible
        assert not {"web_search", "web_fetch", "search_web"} & visible
        assert secret not in repr(model.requests)
        assert outside.read_text() == secret
        assert "error" in repr(bridge.observations[0].evidence["runtime_events"]).lower()
    finally:
        await bridge.close()
        CURRENT_BRIDGE.reset(token)


def test_pass_one_and_four_use_official_all_success_estimator():
    from examples.v2.tau_bench_report import repeated_scores
    rows = []
    for label, scores in [('baseline', [[1.0, 1.0, 1.0, 1.0], [1.0, 0.0, 0.0, 0.0]]),
                          ('candidate', [[1.0, 1.0, 1.0, 0.0], [1.0, 1.0, 1.0, 1.0]])]:
        for task, values in zip(['a', 'b'], scores):
            rows.extend({'phase': 'test-' + label, 'task': task, 'trial': i, 'reward': score}
                        for i, score in enumerate(values))
    report = repeated_scores(rows, ['a', 'b'], 4)
    assert report['complete']
    assert report['baseline'] == {'pass^1': .625, 'pass^4': .5}
    assert report['candidate'] == {'pass^1': .875, 'pass^4': .5}
    assert not repeated_scores(rows[:-1], ['a', 'b'], 4)['complete']
    with pytest.raises(ValueError, match='duplicate'):
        repeated_scores([*rows, rows[0]], ['a', 'b'], 4)


def test_training_trace_keeps_action_arguments_and_final_failure_in_long_dialogues():
    from examples.v2.optimizer_tau_bench import compact_training_trace
    from sagents.v2.optimization.feedback import training_feedback
    from sagents.v2.optimization.contracts import OptimizationCaseResult, OptimizationGrade, OptimizationObservation
    simulation = {'messages': [
        {'role': 'user', 'content': 'ORIGINAL REQUEST'},
        *[{'role': 'tool', 'content': 'inventory payload' * 500} for _ in range(90)],
        {'role': 'assistant', 'tool_calls': [{'name': 'return_delivered_order_items', 'arguments': {'payment_method_id': 'original'}}]},
        {'role': 'tool', 'content': 'FINAL FAILURE: invalid payment method'},
    ]}
    trace = compact_training_trace(simulation)
    case = task_case('train-only', 'training')
    result = OptimizationCaseResult(case=case, grade=OptimizationGrade(score=0, passed=False, rationale='failed'),
        observation=OptimizationObservation(state='completed', output='FIRST' + 'x' * 10000 + 'LAST',
            evidence={'training_trace': trace}))
    feedback = training_feedback(result)['observation']
    assert feedback['output'].startswith('FIRST') and feedback['output'].endswith('LAST')
    assert feedback['output_truncated']
    assert 'ORIGINAL REQUEST' in feedback['evidence']['training_trace']
    assert 'FINAL FAILURE' in feedback['evidence']['training_trace']
    assert 'payment_method_id' in feedback['evidence']['training_trace']


@pytest.mark.asyncio
async def test_reference_mode_freezes_default_without_entering_optimizer(tmp_path):
    from types import SimpleNamespace
    from examples.v2.optimizer_tau_bench import TauExperiment, package
    host = object.__new__(TauExperiment)
    host.args = SimpleNamespace(resume_test=False, reference_only=True)
    host.root = tmp_path
    host.target = package('reference', 'Default assistant')
    host.configure_official_models = lambda: None
    measured = []
    async def measure(candidate, freeze):
        measured.append((candidate.content_hash, freeze))
    host.measure_frozen = measure
    await host.execute()
    assert len(measured) == 1
    assert measured[0][0] == host.target.content_hash
    assert json.loads((tmp_path / 'frozen.json').read_text())['selection_rule'].startswith('default reference')
    assert json.loads((tmp_path / 'suite.json').read_text())['cases'] == []
    assert not (tmp_path / 'rsi.jsonl').exists()


def test_reference_metrics_keep_same_four_trial_denominator():
    from examples.v2.tau_bench_report import repeated_scores
    rows = [{'phase': 'test-reference', 'task': 'a', 'trial': i, 'reward': score}
            for i, score in enumerate([1, 1, 0, 1])]
    report = repeated_scores(rows, ['a'], 4, labels=('reference',))
    assert report['complete']
    assert report['reference'] == {'pass^1': .75, 'pass^4': 0}
    with pytest.raises(ValueError, match='unique tasks'):
        repeated_scores(rows, ['a', 'a'], 4, labels=('reference',))
