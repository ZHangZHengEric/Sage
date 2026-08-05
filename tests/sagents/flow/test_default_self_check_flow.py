import pytest

from sagents.flow.schema import (
    AgentNode,
    IfNode,
    LoopNode,
    ParallelNode,
    SequenceNode,
    SwitchNode,
)
from sagents.sagents import SAgent
from sagents.session_runtime import Session


def _agent_keys(node):
    keys = []
    if isinstance(node, AgentNode):
        return [node.agent_key]
    if isinstance(node, SequenceNode):
        for step in node.steps:
            keys.extend(_agent_keys(step))
    elif isinstance(node, ParallelNode):
        for branch in node.branches:
            keys.extend(_agent_keys(branch))
    elif isinstance(node, LoopNode):
        keys.extend(_agent_keys(node.body))
    elif isinstance(node, IfNode):
        keys.extend(_agent_keys(node.true_body))
        if node.false_body is not None:
            keys.extend(_agent_keys(node.false_body))
    elif isinstance(node, SwitchNode):
        for case in node.cases.values():
            keys.extend(_agent_keys(case))
        if node.default is not None:
            keys.extend(_agent_keys(node.default))
    return keys


def test_simple_and_fibre_memory_recall_run_outside_self_check_retry_loop(tmp_path):
    flow = SAgent(str(tmp_path), enable_obs=False)._build_default_flow(
        agent_mode="simple",
        max_loop_count=5,
    )
    switch = flow.root.steps[0]

    assert "task_analysis" not in _agent_keys(flow.root)

    for mode, executor_key in [
        ("simple", "simple"),
        ("fibre", "fibre"),
        ("team", "team"),
    ]:
        body = switch.cases[mode]

        assert isinstance(body, SequenceNode)
        assert isinstance(body.steps[0], ParallelNode)
        assert sorted(_agent_keys(body.steps[0])) == [
            "memory_recall",
            "tool_suggestion",
        ]

        retry_loop = body.steps[1]
        assert isinstance(retry_loop, LoopNode)
        assert retry_loop.condition == "self_check_should_retry"

        loop_keys = _agent_keys(retry_loop.body)
        assert executor_key in loop_keys
        assert "self_check" in loop_keys
        assert "memory_recall" not in loop_keys
        assert "tool_suggestion" not in loop_keys


def test_default_flow_only_exposes_supported_modes(tmp_path):
    flow = SAgent(str(tmp_path), enable_obs=False)._build_default_flow(
        agent_mode="simple",
        max_loop_count=5,
    )
    switch = flow.root.steps[0]

    assert set(switch.cases) == {"simple", "fibre", "team"}
    assert "task_analysis" not in _agent_keys(flow.root)
    assert "task_summary" not in _agent_keys(flow.root)


def test_runtime_registry_only_contains_current_agents():
    registry = Session("registry-audit", enable_obs=False)._agent_registry

    assert set(registry) == {
        "simple",
        "query_suggest",
        "tool_suggestion",
        "fibre",
        "team",
        "memory_recall",
        "plan",
        "self_check",
    }


@pytest.mark.asyncio
async def test_public_runtime_rejects_retired_multi_mode(tmp_path):
    stream = SAgent(str(tmp_path), enable_obs=False).run_stream(
        input_messages=[],
        model=object(),
        model_config={"model": "test-model"},
        system_prefix="",
        max_loop_count=1,
        agent_mode="multi",
    )

    with pytest.raises(ValueError, match="simple, fibre, team"):
        await anext(stream)
