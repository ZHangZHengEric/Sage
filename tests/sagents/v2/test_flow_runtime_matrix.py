from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    StartRun,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import RunState
from sagents.v2.flow.contracts import FlowNodeOutcome, FlowNodeResult
from sagents.v2.flow.engine import FlowRuntime
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_1",
    )
)


@dataclass
class FakeNode:
    output: dict
    calls: list = field(default_factory=list)
    error: RuntimeErrorInfo | None = None

    async def run(self, context):
        self.calls.append(context)
        if self.error is not None:
            return FlowNodeResult(outcome=FlowNodeOutcome.FAILED, error=self.error)
        return FlowNodeResult(output=self.output)


async def setup(flow, runners):
    runtime = HarnessRuntime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="flow_agent",
            input=(InputItem(role="user", content=(TextBlock(text="run"),)),),
            resolved_spec_hash="sha256:flow",
            idempotency_key="start",
        ),
        CONTEXT,
    )
    engine = FlowRuntime(
        runtime=runtime,
        flows={"main": flow},
        agent_nodes=runners,
    )
    return runtime, handle, engine


async def setup_flows(flows, runners, *, max_node_visits=100):
    runtime = HarnessRuntime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="flow_agent",
            input=(InputItem(role="user", content=(TextBlock(text="run"),)),),
            resolved_spec_hash="sha256:flow",
            idempotency_key="start",
        ),
        CONTEXT,
    )
    engine = FlowRuntime(
        runtime=runtime,
        flows=flows,
        agent_nodes=runners,
        max_node_visits=max_node_visits,
    )
    return runtime, handle, engine


def sequential_flow():
    return FlowDefinition(
        version="1",
        start="inspect",
        nodes=(
            FlowNode(id="inspect", type="agent", agent="inspector"),
            FlowNode(id="verify", type="agent", agent="verifier"),
        ),
        edges=(
            FlowEdge(**{"from": "inspect", "to": "verify"}),
            FlowEdge(**{"from": "verify", "to": "end"}),
        ),
    )


@pytest.mark.asyncio
async def test_sequential_agent_flow_uses_same_native_run_and_event_log():
    inspector = FakeNode({"finding": "risk"})
    verifier = FakeNode({"verified": True})
    runtime, handle, engine = await setup(
        sequential_flow(), {"inspector": inspector, "verifier": verifier}
    )
    result = await engine.execute(handle.run_id, "main", CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]

    assert result.state == RunState.COMPLETED
    assert len(inspector.calls) == len(verifier.calls) == 1
    assert verifier.calls[0].prior_results == {"inspect": {"finding": "risk"}}
    assert types.count("flow.node.started") == 2
    assert types.count("flow.node.completed") == 2
    assert types[-2:] == ["flow.completed", "run.completed"]
    started = {
        event.data.node_id: event.node_execution_id
        for event in events
        if event.type == "flow.node.started"
    }
    completed = {
        event.data.node_id: event.node_execution_id
        for event in events
        if event.type == "flow.node.completed"
    }
    assert started == completed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed", "expected_runner"), [(True, "changer"), (False, "finisher")]
)
async def test_conditional_edge_selection_matrix(changed, expected_runner):
    detector = FakeNode({"changed": changed})
    changer = FakeNode({"path": "changed"})
    finisher = FakeNode({"path": "unchanged"})
    flow = FlowDefinition(
        version="1",
        start="detect",
        nodes=(
            FlowNode(id="detect", type="agent", agent="detector"),
            FlowNode(id="change", type="agent", agent="changer"),
            FlowNode(id="finish", type="agent", agent="finisher"),
        ),
        edges=(
            FlowEdge(**{"from": "detect", "to": "change", "when": "changed == True"}),
            FlowEdge(**{"from": "detect", "to": "finish", "when": "changed == False"}),
            FlowEdge(**{"from": "change", "to": "end"}),
            FlowEdge(**{"from": "finish", "to": "end"}),
        ),
    )
    runtime, handle, engine = await setup(
        flow,
        {"detector": detector, "changer": changer, "finisher": finisher},
    )
    result = await engine.execute(handle.run_id, "main", CONTEXT)
    assert result.state == RunState.COMPLETED
    assert (len(changer.calls), len(finisher.calls)) == (
        (1, 0) if expected_runner == "changer" else (0, 1)
    )


@pytest.mark.asyncio
async def test_parallel_branches_actually_overlap_and_commit_deterministically():
    active = 0
    maximum = 0
    both_active = asyncio.Event()

    class ParallelNode:
        def __init__(self, name):
            self.name = name

        async def run(self, context):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_active.set()
            await both_active.wait()
            active -= 1
            return FlowNodeResult(output={"branch": self.name})

    flow = FlowDefinition(
        version="1",
        start="parallel",
        nodes=(
            FlowNode(
                id="parallel",
                type="parallel",
                config={"branches": ["branch_a", "branch_b"]},
            ),
            FlowNode(id="branch_a", type="agent", agent="a"),
            FlowNode(id="branch_b", type="agent", agent="b"),
            FlowNode(id="join", type="join"),
        ),
        edges=(
            FlowEdge(**{"from": "parallel", "to": "join"}),
            FlowEdge(**{"from": "join", "to": "end"}),
        ),
    )
    runtime, handle, engine = await setup(
        flow, {"a": ParallelNode("a"), "b": ParallelNode("b")}
    )
    result = await engine.execute(handle.run_id, "main", CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    completed_nodes = [
        event.data.node_id for event in events if event.type == "flow.node.completed"
    ]
    assert result.state == RunState.COMPLETED
    assert maximum == 2
    assert completed_nodes[:3] == ["branch_a", "branch_b", "parallel"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected_agent"),
    [("approve", "approved_agent"), ("deny", "denied_agent")],
)
async def test_interaction_node_suspends_and_resumes_conditional_flow(
    decision, expected_agent
):
    approved = FakeNode({"path": "approved"})
    denied = FakeNode({"path": "denied"})
    flow = FlowDefinition(
        version="1",
        start="approval",
        nodes=(
            FlowNode(
                id="approval",
                type="interaction",
                interaction="approval",
                blocking_scope="run",
                config={"allowed_decisions": ["approve", "deny"]},
            ),
            FlowNode(id="approved", type="agent", agent="approved_agent"),
            FlowNode(id="denied", type="agent", agent="denied_agent"),
        ),
        edges=(
            FlowEdge(**{"from": "approval", "to": "approved", "when": "approved"}),
            FlowEdge(**{"from": "approval", "to": "denied", "when": "denied"}),
            FlowEdge(**{"from": "approved", "to": "end"}),
            FlowEdge(**{"from": "denied", "to": "end"}),
        ),
    )
    runtime, handle, engine = await setup(
        flow, {"approved_agent": approved, "denied_agent": denied}
    )
    suspended = await engine.execute(handle.run_id, "main", CONTEXT)
    assert suspended.state == RunState.SUSPENDED
    checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
    assert checkpoint.checkpoint_codec_version == "flow/1"
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=0,
            expected_interaction_revision=0,
            decision=decision,
            idempotency_key=f"reply_{decision}",
        ),
        CONTEXT,
    )
    result = await engine.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert (len(approved.calls), len(denied.calls)) == (
        (1, 0) if expected_agent == "approved_agent" else (0, 1)
    )
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]
    assert "flow.node.suspended" in types
    assert "flow.node.resumed" in types
    interaction_lifecycle = [
        event
        for event in await runtime.session_store.read_events(handle.run_id)
        if event.type
        in {
            "flow.node.started",
            "flow.node.suspended",
            "flow.node.resumed",
            "flow.node.completed",
        }
        and event.data.node_id == "approval"
    ]
    assert [event.type for event in interaction_lifecycle] == [
        "flow.node.started",
        "flow.node.suspended",
        "flow.node.resumed",
        "flow.node.completed",
    ]
    assert len({event.node_execution_id for event in interaction_lifecycle}) == 1


@pytest.mark.asyncio
async def test_node_failure_becomes_flow_and_run_failure():
    error = RuntimeErrorInfo(
        code="node.failed",
        category=ErrorCategory.PROVIDER_PERMANENT,
        message="node failed",
    )
    flow = FlowDefinition(
        version="1",
        start="bad",
        nodes=(FlowNode(id="bad", type="agent", agent="bad"),),
        edges=(FlowEdge(**{"from": "bad", "to": "end"}),),
    )
    runtime, handle, engine = await setup(flow, {"bad": FakeNode({}, error=error)})
    result = await engine.execute(handle.run_id, "main", CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    assert result.state == RunState.FAILED
    assert [event.type for event in events[-2:]] == [
        "flow.node.failed",
        "run.failed",
    ]
    assert events[-1].data.error.code == "node.failed"


@pytest.mark.asyncio
async def test_equal_priority_matching_edges_fail_instead_of_nondeterminism():
    flow = FlowDefinition(
        version="1",
        start="first",
        nodes=(
            FlowNode(id="first", type="agent", agent="first"),
            FlowNode(id="a", type="agent", agent="a"),
            FlowNode(id="b", type="agent", agent="b"),
        ),
        edges=(
            FlowEdge(**{"from": "first", "to": "a", "when": "always"}),
            FlowEdge(**{"from": "first", "to": "b", "when": "always"}),
        ),
    )
    runtime, handle, engine = await setup(
        flow, {"first": FakeNode({}), "a": FakeNode({}), "b": FakeNode({})}
    )
    result = await engine.execute(handle.run_id, "main", CONTEXT)
    assert result.state == RunState.FAILED
    events = await runtime.session_store.read_events(handle.run_id)
    assert events[-1].type == "run.failed"
    assert events[-1].data.error.code == "flow.edge_ambiguous"


@pytest.mark.asyncio
async def test_subflow_runs_as_a_nested_frame_and_returns_results_to_parent():
    worker = FakeNode({"artifact": "ready"})
    finisher = FakeNode({"verified": True})
    flows = {
        "main": FlowDefinition(
            version="1",
            start="delegate",
            nodes=(
                FlowNode(id="delegate", type="subflow", flow="child"),
                FlowNode(id="finish", type="agent", agent="finisher"),
            ),
            edges=(
                FlowEdge(**{"from": "delegate", "to": "finish"}),
                FlowEdge(**{"from": "finish", "to": "end"}),
            ),
        ),
        "child": FlowDefinition(
            version="7",
            start="work",
            nodes=(FlowNode(id="work", type="agent", agent="worker"),),
            edges=(FlowEdge(**{"from": "work", "to": "end"}),),
        ),
    }
    runtime, handle, engine = await setup_flows(
        flows, {"worker": worker, "finisher": finisher}
    )

    result = await engine.execute(handle.run_id, "main", CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    started = {
        event.data.node_id: event.node_execution_id
        for event in events
        if event.type == "flow.node.started"
    }
    completed = {
        event.data.node_id: event.node_execution_id
        for event in events
        if event.type == "flow.node.completed"
    }

    assert result.state == RunState.COMPLETED
    assert worker.calls[0].flow_id == "child"
    assert finisher.calls[0].prior_results["delegate"] == {
        "flow_id": "child",
        "version": "7",
        "results": {"work": {"artifact": "ready"}},
    }
    assert started == completed
    flow_events = [
        event for event in events if event.type in {"flow.started", "flow.completed"}
    ]
    root_execution_id = flow_events[0].flow_execution_id
    child_execution_id = flow_events[1].flow_execution_id
    assert child_execution_id != root_execution_id
    assert [
        (event.type, event.data.flow_id, event.flow_execution_id)
        for event in flow_events
    ] == [
        ("flow.started", "main", root_execution_id),
        ("flow.started", "child", child_execution_id),
        ("flow.completed", "child", child_execution_id),
        ("flow.completed", "main", root_execution_id),
    ]


@pytest.mark.asyncio
async def test_nested_subflow_interaction_checkpoint_resumes_exact_active_frame():
    child_worker = FakeNode({"continued": True})
    flows = {
        "main": FlowDefinition(
            version="1",
            start="delegate",
            nodes=(FlowNode(id="delegate", type="subflow", flow="child"),),
            edges=(FlowEdge(**{"from": "delegate", "to": "end"}),),
        ),
        "child": FlowDefinition(
            version="1",
            start="approval",
            nodes=(
                FlowNode(
                    id="approval",
                    type="interaction",
                    interaction="approval",
                    blocking_scope="run",
                    config={"allowed_decisions": ["approve", "deny"]},
                ),
                FlowNode(id="work", type="agent", agent="child_worker"),
            ),
            edges=(
                FlowEdge(**{"from": "approval", "to": "work", "when": "approved"}),
                FlowEdge(**{"from": "approval", "to": "end", "when": "denied"}),
                FlowEdge(**{"from": "work", "to": "end"}),
            ),
        ),
    }
    runtime, handle, engine = await setup_flows(flows, {"child_worker": child_worker})

    suspended = await engine.execute(handle.run_id, "main", CONTEXT)
    checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
    assert suspended.state == RunState.SUSPENDED
    assert checkpoint.state["subflow_stack"][0]["flow_id"] == "child"
    assert checkpoint.state["subflow_stack"][0]["current_node_id"] == "approval"
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=0,
            expected_interaction_revision=0,
            decision="approve",
            idempotency_key="nested_reply",
        ),
        CONTEXT,
    )

    result = await engine.resume(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(child_worker.calls) == 1
    assert child_worker.calls[0].prior_results["approval"]["decision"] == "approve"
    events = await runtime.session_store.read_events(handle.run_id)
    assert [
        event.data.node_id for event in events if event.type == "flow.node.completed"
    ] == ["approval", "work", "delegate"]
    child_execution_ids = {
        event.flow_execution_id
        for event in events
        if getattr(event.data, "flow_id", None) == "child"
    }
    assert len(child_execution_ids) == 1
    assert next(iter(child_execution_ids)) != next(
        event.flow_execution_id
        for event in events
        if event.type == "flow.started" and event.data.flow_id == "main"
    )


@pytest.mark.asyncio
async def test_double_nested_subflow_can_execute_parallel_leaf_nodes():
    a = FakeNode({"leaf": "a"})
    b = FakeNode({"leaf": "b"})
    flows = {
        "main": FlowDefinition(
            version="1",
            start="middle",
            nodes=(FlowNode(id="middle", type="subflow", flow="middle_flow"),),
            edges=(FlowEdge(**{"from": "middle", "to": "end"}),),
        ),
        "middle_flow": FlowDefinition(
            version="1",
            start="leaf",
            nodes=(FlowNode(id="leaf", type="subflow", flow="leaf_flow"),),
            edges=(FlowEdge(**{"from": "leaf", "to": "end"}),),
        ),
        "leaf_flow": FlowDefinition(
            version="1",
            start="fanout",
            nodes=(
                FlowNode(
                    id="fanout",
                    type="parallel",
                    config={"branches": ["a", "b"]},
                ),
                FlowNode(id="a", type="agent", agent="a"),
                FlowNode(id="b", type="agent", agent="b"),
            ),
            edges=(FlowEdge(**{"from": "fanout", "to": "end"}),),
        ),
    }
    runtime, handle, engine = await setup_flows(flows, {"a": a, "b": b})

    result = await engine.execute(handle.run_id, "main", CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(a.calls) == len(b.calls) == 1
    events = await runtime.session_store.read_events(handle.run_id)
    assert [
        event.data.node_id for event in events if event.type == "flow.node.completed"
    ] == ["a", "b", "fanout", "leaf", "middle"]


@pytest.mark.asyncio
async def test_recursive_subflow_depth_budget_fails_deterministically():
    recursive = FlowDefinition(
        version="1",
        start="again",
        nodes=(FlowNode(id="again", type="subflow", flow="recursive"),),
        edges=(FlowEdge(**{"from": "again", "to": "end"}),),
    )
    runtime, handle, engine = await setup_flows(
        {"recursive": recursive}, {}, max_node_visits=2
    )

    result = await engine.execute(handle.run_id, "recursive", CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)

    assert result.state == RunState.FAILED
    assert events[-1].type == "run.failed"
    assert events[-1].data.error.code == "flow.subflow_depth_exhausted"
