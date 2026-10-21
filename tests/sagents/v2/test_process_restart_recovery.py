"""Cold-process recovery, including hard kills at model/tool/Team boundaries."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.contracts.run_state import RunSnapshot
    from sagents.v2.model.contracts import ModelEventKind
    from sagents.v2.runtime.session.contracts import SessionStore

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentInvocationMode,
    AgentMode,
    AgentRegistry,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.contracts.commands import InputItem, ReplyInteraction, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model import (
    ModelCapabilities,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import FilesystemScheduler
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.sagent import SAgent
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="restart-test", principal_type=PrincipalType.USER)
)
DEFINITION = ToolDefinition(
    name="save_value",
    description="Persist an external value",
    input_schema={"type": "object"},
    side_effect_level=SideEffectLevel.WRITE,
)


def completion(text="done", calls=()):
    return ModelStreamEvent(
        kind=cast('ModelEventKind', "completed"),
        response=ModelResponse(
            response_id="response",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
        ),
    )


def effect(root, name):
    with (root / f"effect-{name}").open("a") as output:
        output.write("applied\n")
        output.flush()
        os.fsync(output.fileno())


class Model:
    def __init__(
        self, root, store, *, crash=False, team=False, suspend=False, initial=False
    ):
        self.root, self.store, self.crash, self.team = root, store, crash, team
        self.suspend = suspend
        self.initial = initial
        self.requests = []

    async def capabilities(self, binding):
        return ModelCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def stream(self, request):
        self.requests.append(request)
        command = await self.store.get_start_command(request.run_id)
        name = command.agent_id
        if self.initial:
            (self.root / "ready").write_text("first LLM request in flight")
            await asyncio.Event().wait()
        results = [m for m in request.messages if m.role == "tool"]
        if results:
            if self.crash and (not self.team or name == "slow"):
                if self.team:
                    # Ensure the sibling result is durable before killing the worker.
                    while not (self.root / "fast-completed").exists():
                        await asyncio.sleep(0.01)
                if self.suspend:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="model.provider_permanent",
                            category=ErrorCategory.PROVIDER_PERMANENT,
                            message="temporary unavailable model",
                            safe_to_resume=True,
                        )
                    )
                (self.root / "ready").write_text("waiting for LLM with saved tools")
                await asyncio.Event().wait()
            yield completion(f"done {name}")
            return
        targets = {"root": ["director"], "director": ["fast", "slow"]}
        if self.team and name in targets:
            yield completion(
                "",
                (
                    ModelToolCall(
                        tool_call_id=f"delegate-{name}",
                        name="sys_team_delegate_task",
                        arguments={
                            "tasks": [
                                {"agent_id": child, "content": f"work {child}"}
                                for child in targets[name]
                            ]
                        },
                    ),
                ),
            )
        else:
            yield completion(
                "",
                (
                    ModelToolCall(
                        tool_call_id=f"save-{name}", name="save_value", arguments={}
                    ),
                ),
            )


class CrashBoundaryLoop(AgentLoopEngine):
    def __init__(self, *args, root, boundary, **kwargs):
        super().__init__(*args, **kwargs)
        self.root, self.boundary = root, boundary

    async def _commit_running(self, run, context, drafts, **kwargs):
        result = await super()._commit_running(run, context, drafts, **kwargs)
        state = kwargs.get("recovery_state")
        if self.boundary == "response" and state and state.pending_response_step_id:
            (self.root / "ready").write_text("response saved before dispatch")
            await asyncio.Event().wait()
        return result

    async def _commit_tool_result(self, *args, **kwargs):
        result = await super()._commit_tool_result(*args, **kwargs)
        if self.boundary == "result":
            (self.root / "ready").write_text("result saved before control checkpoint")
            await asyncio.Event().wait()
        return result


def simple_loop(root, runtime, model, *, boundary=None, unknown=False, followup=False):
    async def save(call, context):
        effect(root, "root")
        if unknown:
            (root / "ready").write_text("effect happened but result is missing")
            await asyncio.Event().wait()
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="saved result"),),
            metadata={
                "followup_user_message": {
                    "content": [{"kind": "text", "text": "retained tool context"}]
                }
            }
            if followup
            else {},
        )

    options: dict[str, Any] = dict(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((DEFINITION,)),
        tool_executor=InMemoryToolExecutor(
            {DEFINITION.name: DEFINITION}, {DEFINITION.name: save}
        ),
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    )
    if boundary:
        return CrashBoundaryLoop(**options, root=root, boundary=boundary)
    return AgentLoopEngine(**options)


def team_factory(root, runtime, model, *, crash=False, unknown=False):
    descriptors = {
        name: AgentDescriptor(
            agent_id=name,
            name=name,
            description=name,
            instructions="Complete the assigned task.",
            mode=AgentMode.TEAM if name in {"root", "director"} else AgentMode.SIMPLE,
            tools=("save_value",),
        )
        for name in ("root", "director", "fast", "slow")
    }

    # Explicitly declared nested Teams use agent-as-tool; ordinary members
    # retain the default delegated-leaf boundary, as embedding hosts require.
    class TeamExecutor(LoopChildRunExecutor):
        async def run_child(self, descriptor, task, **kwargs):
            if descriptor.mode == AgentMode.TEAM:
                task = task.model_copy(
                    update={"invocation_mode": AgentInvocationMode.AGENT_AS_TOOL}
                )
            result = await super().run_child(descriptor, task, **kwargs)
            if crash and descriptor.agent_id == "fast":
                (root / "fast-completed").write_text(result.child_run_id)
            return result

    async def save(call, context):
        name = (
            await runtime.session_store.get_start_command(call.owner_run_id)
        ).agent_id
        effect(root, name)
        if unknown and name == "slow":
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="mcp.result_not_received",
                    category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                    message="response lost after remote effect",
                    safe_to_resume=False,
                )
            )
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=f"saved {name}"),),
        )

    def compose(descriptor, run_id, catalog, executor):
        return AgentLoopEngine(
            runtime=runtime,
            model=model,
            tool_catalog=catalog,
            tool_executor=executor,
            tool_policy=DefaultToolPolicy(
                approval_strategy=ApprovalStrategy.AUTO_APPROVE
            ),
        )

    registry = AgentRegistry(tuple(descriptors.values()))
    factory = ModeAwareAgentLoopFactory(
        runtime=runtime,
        model_factory=lambda *_: model,
        base_catalog=InMemoryToolCatalog((DEFINITION,)),
        base_executor=InMemoryToolExecutor(
            {DEFINITION.name: DEFINITION}, {DEFINITION.name: save}
        ),
        registry=registry,
        resolved_spec_hash="sha256:restart",
        loop_composer=compose,
    )
    factory.child_executor = TeamExecutor(
        runtime=runtime,
        loop_factory=lambda descriptor, run_id, context: factory.create_loop(
            descriptor, run_id
        ),
        descriptor_resolver=registry.get,
        resolved_spec_hash="sha256:restart",
    )
    return factory, descriptors["root"]


async def retry_interaction(runtime, store, run_id, *, decision="retry"):
    run = await store.get_run(run_id)
    suspension = await store.get_suspension(run.suspension_id)
    interaction = await store.get_interaction(suspension.interaction_id)
    receipt = await runtime.reply_interaction(
        ReplyInteraction(
            run_id=run.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=run.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision=decision,
            payload={"result_text": "verified saved remote result"},
            idempotency_key="retry-after-restart",
        ),
        CONTEXT,
    )
    assert receipt.decision.value == "accepted"


async def worker(root, scenario):
    store = FilesystemSessionStore(root / "store")
    runtime = HarnessRuntime(cast('SessionStore', store))
    handle = await runtime.start_run(
        StartRun(
            agent_id="root",
            idempotency_key="start",
            input=(
                InputItem(role="user", content=(TextBlock(text="original request"),)),
            ),
            resolved_spec_hash="sha256:restart",
        ),
        CONTEXT,
    )
    (root / "identity.json").write_text(
        json.dumps({"run": handle.run_id, "session": handle.session_id})
    )
    model = Model(
        root,
        store,
        crash=True,
        team=scenario.startswith("team"),
        suspend=scenario in {"team-suspended", "team-resuming", "team-child-resuming"},
        initial=scenario == "first-model",
    )
    if scenario.startswith("team"):
        factory, descriptor = team_factory(
            root, runtime, model, crash=True, unknown=scenario == "team-unknown"
        )
        loop = factory.create_loop(descriptor, handle.run_id)
    else:
        boundary = (
            "result"
            if scenario == "followup"
            else scenario
            if scenario in {"response", "result"}
            else None
        )
        loop = simple_loop(
            root,
            runtime,
            model,
            boundary=boundary,
            unknown=scenario == "unknown",
            followup=scenario == "followup",
        )
    result = await loop.execute(handle.run_id, CONTEXT)
    if scenario == "team-unknown":
        assert result.state == RunState.SUSPENDED
        (root / "ready").write_text("nested unknown tool awaiting reconciliation")
        await asyncio.Event().wait()
    if scenario in {"team-suspended", "team-resuming", "team-child-resuming"}:
        assert result.state == RunState.SUSPENDED
        if scenario == "team-suspended":
            (root / "ready").write_text("nested interaction saved")
            await asyncio.Event().wait()
        await retry_interaction(runtime, store, handle.run_id)
        mark_resumed = runtime.mark_resumed

        async def crash_during_resume(**kwargs):
            resumed = await mark_resumed(**kwargs)
            command = await store.get_start_command(resumed.run_id)
            target = "root" if scenario == "team-resuming" else "slow"
            if command.agent_id == target:
                (root / "ready").write_text("resume committed before continuation")
                await asyncio.Event().wait()
            return resumed

        runtime.mark_resumed = crash_during_resume
        await loop.resume(handle.run_id, CONTEXT)
    raise AssertionError("worker must be killed at a durable boundary")


async def kill_worker(root, scenario):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])}
    process = subprocess.Popen(
        [sys.executable, __file__, str(root), scenario],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(20):
            while not (root / "ready").exists():
                if process.poll() is not None:
                    raise AssertionError(process.communicate())
                await asyncio.sleep(0.02)
        process.kill()  # No engine/store cleanup: this is a real cold restart.
        await asyncio.to_thread(process.communicate)
    finally:
        if process.poll() is None:
            process.kill()
            await asyncio.to_thread(process.communicate)
    return json.loads((root / "identity.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["first-model", "model", "response", "result", "unknown", "followup"]
)
async def test_hard_kill_preserves_ledger_and_does_not_repeat_tools(tmp_path, scenario):
    identity = await kill_worker(tmp_path, scenario)
    store = FilesystemSessionStore(tmp_path / "store")
    try:
        runtime = HarnessRuntime(cast('SessionStore', store))
        before = await store.read_events(identity["run"])
        model = Model(tmp_path, store)
        loop = simple_loop(tmp_path, runtime, model)
        recovered = await asyncio.wait_for(
            loop.recover_interrupted(identity["run"], CONTEXT), 10
        )
        assert cast('RunSnapshot', recovered).run_id == identity["run"]
        assert cast('RunSnapshot', recovered).state == (
            RunState.SUSPENDED if scenario == "unknown" else RunState.COMPLETED
        )
        after = await store.read_events(identity["run"])
        assert [e.event_id for e in after[: len(before)]] == [
            e.event_id for e in before
        ]
        assert (tmp_path / "effect-root").read_text() == "applied\n"
        assert sum(e.type == "tool.call.started" for e in after) == 1
        if scenario != "unknown":
            assert len(model.requests) == (2 if scenario == "first-model" else 1)
            assert any(
                m.role == "tool" and m.content[0].text == "saved result"
                for m in model.requests[-1].messages
            )
            if scenario == "followup":
                assert (
                    sum(
                        m.role == "user"
                        and m.content[0].text == "retained tool context"
                        for m in model.requests[0].messages
                    )
                    == 1
                )
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    ["team", "team-suspended", "team-resuming", "team-child-resuming", "team-unknown"],
)
async def test_dispatcher_recovers_entire_team_tree_after_hard_kill(tmp_path, scenario):
    identity = await kill_worker(tmp_path, scenario)
    store = FilesystemSessionStore(tmp_path / "store")
    runtime = HarnessRuntime(cast('SessionStore', store))
    sessions = [
        identity["session"],
        *[
            s.session_id
            for s in await store.list_descendant_sessions(identity["session"])
        ],
    ]
    original = {
        r.run_id: await store.read_events(r.run_id)
        for sid in sessions
        for r in await store.list_session_runs(sid)
    }
    assert len(original) == 4
    model = Model(tmp_path, store, team=True)
    factory, descriptor = team_factory(tmp_path, runtime, model)
    scheduler = FilesystemScheduler(tmp_path / "scheduler")
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    agent = SAgent._from_composition(
        runtime=runtime,
        driver_factory=lambda run_id: factory.create_loop(descriptor, run_id),
    )
    dispatcher.attach_recovery_agent(agent)
    try:
        if scenario == "team-suspended":
            await retry_interaction(runtime, store, identity["run"])
        if scenario == "team-unknown":
            await retry_interaction(
                runtime, store, identity["run"], decision="confirm_succeeded"
            )
        await dispatcher.start()
        async with asyncio.timeout(10):
            while (await store.get_run(identity["run"])).state not in {
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.SUSPENDED,
            }:
                await asyncio.sleep(0.02)
        assert (await store.get_run(identity["run"])).state == RunState.COMPLETED
        restored = {
            r.run_id for sid in sessions for r in await store.list_session_runs(sid)
        }
        assert restored == set(original)
        assert len(await store.list_descendant_sessions(identity["session"])) == 3
        for run_id, before in original.items():
            after = await store.read_events(run_id)
            assert [e.event_id for e in after[: len(before)]] == [
                e.event_id for e in before
            ]
            assert (await store.get_run(run_id)).state == RunState.COMPLETED
        for name in ("fast", "slow"):
            assert (tmp_path / f"effect-{name}").read_text() == "applied\n"
        requested_agents = [
            (await store.get_start_command(r.run_id)).agent_id for r in model.requests
        ]
        assert "fast" not in requested_agents
    finally:
        await dispatcher.close()
        await agent.close()
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["digest", "codec"])
async def test_running_checkpoint_digest_mismatch_never_retries_a_tool(
    tmp_path, monkeypatch, fault
):
    identity = await kill_worker(tmp_path, "result")
    store = FilesystemSessionStore(tmp_path / "store")
    try:
        original = store.get_checkpoint

        async def corrupted(checkpoint_id):
            checkpoint = await original(checkpoint_id)
            if fault == "codec":
                return checkpoint.model_copy(
                    update={"checkpoint_codec_version": "agent-loop/unsupported"}
                )
            return checkpoint.model_copy(
                update={"state": {**checkpoint.state, "ledger_digest": "sha256:wrong"}}
            )

        monkeypatch.setattr(store, "get_checkpoint", corrupted)
        model = Model(tmp_path, store)
        loop = simple_loop(tmp_path, HarnessRuntime(cast('SessionStore', store)), model)
        with pytest.raises(SageV2Error) as failure:
            await loop.recover_interrupted(identity["run"], CONTEXT)
        assert failure.value.info.code == (
            "loop.checkpoint_ledger_mismatch"
            if fault == "digest"
            else "loop.checkpoint_incompatible"
        )
        assert failure.value.info.safe_to_resume is False
        assert model.requests == []
        assert (tmp_path / "effect-root").read_text() == "applied\n"
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2]))
