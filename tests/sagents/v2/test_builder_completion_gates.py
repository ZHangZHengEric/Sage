"""Real Goal/Plan Builder runs with a public host continuation plugin."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.agent.policy import (
    ApprovalStrategy,
    ContinuationAction,
    ContinuationDecision,
    DefaultToolPolicy,
)
from sagents.v2.composition.defaults import default_runtime
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import TextBlock, UsageSummary
from sagents.v2.goal import GoalStateService
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.session import FilesystemSessionStore
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT


MARKER = "yiii_autonomous_replan"
GUIDANCE = "Change the failed approach and verify the saved result. Recovery attempt "
POLICY_USAGE = UsageSummary(input_tokens=11, output_tokens=2, cost=0.001)


class PolicyConfig(StrictModel):
    max_replans: int = 3
    premature_completion: bool = False


class HostPolicy:
    def __init__(self, store, config):
        self.store, self.config = store, config

    async def decide(self, context):
        if context.response.tool_calls:
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="tool.pending",
                reason="Read the tool result.",
            )
        if self.config.premature_completion:
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="host.complete",
                reason="The model claims completion.",
                metadata={"host_completion_candidate": True},
                usage=POLICY_USAGE,
            )
        events = await self.store.read_events(context.run_id)
        attempts = sum(
            e.type == "continuation.decided" and e.data.details.get(MARKER) is True
            for e in events
        )
        if attempts >= self.config.max_replans:
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="host.recovery_exhausted",
                reason="Three recovery attempts exhausted.",
                metadata={"recovery_attempts": attempts},
                error=RuntimeErrorInfo(
                    code="host.recovery_exhausted",
                    category=ErrorCategory.VALIDATION,
                    message="Three recovery attempts exhausted.",
                    safe_to_resume=False,
                    retryable=False,
                ),
                usage=POLICY_USAGE,
            )
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="judge.continue",
            reason=GUIDANCE + str(attempts + 1),
            metadata={
                MARKER: True,
                "recovery_attempt": attempts + 1,
                "original_reason_code": "status.blocked"
                if attempts % 2 == 0
                else "loop.no_progress",
            },
            usage=POLICY_USAGE,
        )


class Model:
    def __init__(self, *, mode="goal", checkpoint=False, complete=False):
        self.mode, self.checkpoint, self.complete = mode, checkpoint, complete
        self.requests = []

    async def capabilities(self, binding):
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def stream(self, request):
        self.requests.append(request)
        stage = sum(m.role == "assistant" for m in request.messages)
        call = None
        if self.complete:
            if stage == 1:
                call = (
                    "goal_submit",
                    {"content": "Deliver verified output", "session_id": None},
                )
            elif stage == 3:
                call = ("goal_complete", {"summary": "Verified output"})
        elif self.mode == "goal" and stage == 0:
            call = (
                "goal_submit",
                {"content": "Deliver verified output", "session_id": None},
            )
        elif self.checkpoint and stage == (3 if self.mode == "goal" else 2):
            call = (
                (
                    "file_write",
                    {"file_path": "checkpoint.txt", "content": "saved candidate"},
                )
                if self.mode == "goal"
                else ("file_read", {"file_path": "checkpoint.txt"})
            )
        calls = (
            (
                ModelToolCall(
                    tool_call_id=f"call-{stage}", name=call[0], arguments=call[1]
                ),
            )
            if call
            else ()
        )
        yield ModelStreamEvent(
            kind="completed",
            response=ModelResponse(
                response_id=f"response-{stage}",
                text="I am done"
                if self.complete and not calls
                else f"blocked-{stage}"
                if not calls
                else "",
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
            ),
        )


async def open_app(root, model, *, premature_completion=False):
    store = FilesystemSessionStore(root / "store")
    bindings = LocalWorkspaceExecutionBindingProvider(
        root / "workspace", process_enabled=False
    )
    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.continuation.host-recovery",
            version="1.0.0",
            name="Host recovery",
            provides=(
                CapabilityOffer(
                    capability="agent.continuation-policy", api_version="2"
                ),
            ),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema=PolicyConfig.model_json_schema(),
        ),
        config_model=PolicyConfig,
        factory=lambda context, dependencies: HostPolicy(
            store, PolicyConfig.model_validate(context.config)
        ),
    )
    runtime = default_runtime(root / "sessions")
    runtime = runtime.model_copy(
        update={
            "capabilities": {
                **runtime.capabilities,
                "tool.catalog": CapabilitySelection(plugin="sage.tool.official"),
                "tool.selection-policy": CapabilitySelection(
                    plugin="sage.tool-selection.direct"
                ),
                "agent.continuation-policy": CapabilitySelection(
                    plugin=registration.descriptor.plugin_id,
                    config={"premature_completion": premature_completion},
                ),
            }
        }
    )

    class Policy(DefaultToolPolicy):
        async def decide(self, context):
            if context.definition.name in {"file_read", "file_write"}:
                return await DefaultToolPolicy(
                    approval_strategy=ApprovalStrategy.ALWAYS_ASK
                ).decide(context)
            return await super().decide(context)

    app = await (
        SAgentBuilder()
        .with_models(TEST_MODELS)
        .with_defaults(session_root=root / "sessions")
        .with_session_store(store)
        .with_owned_resources(store)
        .with_model_provider(model)
        .with_execution_binding_provider(bindings)
        .with_tool_policy(Policy(approval_strategy=ApprovalStrategy.AUTO_APPROVE))
        .register(registration)
        .build(runtime=runtime)
    )
    package = BuiltinPackageFactory.create(
        "assistant", package_id="test.completion-gates"
    )
    package = package.model_copy(
        update={
            "agents": {
                "assistant": package.agents["assistant"].model_copy(
                    update={"tools": ("file_read", "file_write")}
                )
            }
        }
    )
    loaded = await app.load_agent(package)
    return app, bindings, loaded


async def start(app, loaded, mode):
    stream = await app.entrypoint().run_stream(
        StartRun(
            agent_id=loaded.id,
            resolved_spec_hash=loaded.composition_hash,
            invocation_mode=mode,
            config=RunConfig(max_steps=12),
            idempotency_key="goal-recovery",
            input=(
                InputItem(
                    role="user", content=(TextBlock(text="Deliver verified output"),)
                ),
            ),
        ),
        CONTEXT,
        agent=loaded,
    )
    async with asyncio.timeout(15):
        async for _ in stream.events:
            pass
        return await stream.wait()


async def assert_recovery(app, model, run_id, *, complete=True):
    events = await app.runtime.session_store.read_events(run_id)
    marked = [
        e
        for e in events
        if e.type == "continuation.decided" and e.data.details.get(MARKER)
    ]
    assert [e.data.details["recovery_attempt"] for e in marked] == (
        [1, 2, 3] if complete else [1, 2]
    )
    for index, event in enumerate(marked, start=1):
        assert event.data.reason_code == "judge.continue"
        assert event.data.reason == GUIDANCE + str(index)
    usage = [
        e.data.usage
        for e in events
        if e.type == "usage.recorded" and e.data.usage.cost == 0.001
    ]
    assert len(usage) == (4 if complete else 2)
    assert all(value == POLICY_USAGE for value in usage)
    if complete:
        decisions = [e for e in events if e.type == "continuation.decided"]
        assert decisions[-1].data.action == "fail"
        assert decisions[-1].data.details["recovery_attempts"] == 3
        assert (await app.runtime.get_run(run_id)).state.value == "failed"
    # At least one next inference must receive the unchanged host recovery guidance.
    assert any(GUIDANCE in request.model_dump_json() for request in model.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["goal", "plan"])
async def test_builder_completion_gate_preserves_recovery_budget_guidance_and_usage(
    tmp_path, mode
):
    model = Model(mode=mode)
    app, bindings, loaded = await open_app(tmp_path, model)
    try:
        result = await start(app, loaded, mode)
        await assert_recovery(app, model, result.run_id)
        goal = await GoalStateService(app.runtime.session_store).get(result.run_id)
        if mode == "goal":
            assert goal is not None and not goal.completed
            events = await app.runtime.session_store.read_events(result.run_id)
            assert any(
                e.type == "tool.call.succeeded" and e.data.tool_name == "goal_submit"
                for e in events
            )
        else:
            assert goal is None
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_builder_goal_rejects_completion_until_goal_complete_and_summary(
    tmp_path,
):
    model = Model(complete=True)
    app, bindings, loaded = await open_app(tmp_path, model, premature_completion=True)
    try:
        result = await start(app, loaded, "goal")
        assert result.state.value == "completed"
        assert len(model.requests) == 5
        events = await app.runtime.session_store.read_events(result.run_id)
        blocked = [
            e
            for e in events
            if e.type == "continuation.decided"
            and e.data.reason_code == "goal.incomplete"
        ]
        assert len(blocked) == 2
        assert all(
            e.data.action == "continue_step"
            and e.data.details["host_completion_candidate"]
            for e in blocked
        )
        usage = [
            e
            for e in events
            if e.type == "usage.recorded" and e.data.usage == POLICY_USAGE
        ]
        assert len(usage) == 2
        goal = await GoalStateService(app.runtime.session_store).get(result.run_id)
        assert goal is not None and goal.completed
    finally:
        await app.close()
        await bindings.close()


async def pause_recovery(root, *, mode="goal"):
    model = Model(mode=mode, checkpoint=True)
    app, bindings, loaded = await open_app(root, model)
    try:
        if mode == "plan":
            (root / "workspace/checkpoint.txt").write_text("saved candidate")
        result = await start(app, loaded, mode)
        assert result.state.value == "suspended"
        await assert_recovery(app, model, result.run_id, complete=False)
        (root / "paused.json").write_text(
            json.dumps({"run_id": result.run_id, "hash": loaded.composition_hash})
        )
    finally:
        await app.close()
        await bindings.close()


async def resume_recovery(root, *, mode="goal"):
    paused = json.loads((root / "paused.json").read_text())
    model = Model(mode=mode, checkpoint=True)
    app, bindings, _ = await open_app(root, model)
    try:
        run_id = paused["run_id"]
        loaded = await app.agent_for_run(run_id, CONTEXT)
        assert loaded.composition_hash == paused["hash"]
        state = await app.runtime.get_run(run_id)
        store = app.runtime.session_store
        suspension = await store.get_suspension(state.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        await app.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=state.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision="approve_once",
                idempotency_key="resume-recovery",
            ),
            CONTEXT,
        )
        async with asyncio.timeout(15):
            await app.entrypoint().continue_run(run_id, CONTEXT, agent=loaded)
            while (await app.runtime.get_run(run_id)).state.value in {
                "queued",
                "running",
                "resuming",
            }:
                await asyncio.sleep(0.01)
        await assert_recovery(app, model, run_id)
        assert (root / "workspace/checkpoint.txt").read_text() == "saved candidate"
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.parametrize("mode", ["goal", "plan"])
def test_builder_recovery_counter_survives_process_restart(tmp_path, mode):
    for seed, phase in enumerate(("pause_recovery", "resume_recovery"), start=1):
        code = (
            "import asyncio,sys; from pathlib import Path; "
            f"from tests.sagents.v2.test_builder_completion_gates import {phase}; "
            f"asyncio.run({phase}(Path(sys.argv[1]), mode=sys.argv[2]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), mode],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_builder_plan_completion_requires_successful_user_approved_submission(
    tmp_path,
):
    model = Model(mode="plan", complete=True)
    app, bindings, loaded = await open_app(tmp_path, model, premature_completion=True)
    try:
        result = await start(app, loaded, "plan")
        assert result.state.value == "suspended"
        run_id = result.run_id
        store = app.runtime.session_store
        goals = GoalStateService(store)
        assert await goals.get(run_id) is None
        events = await store.read_events(run_id)
        blocked = [
            e
            for e in events
            if e.type == "continuation.decided"
            and e.data.reason_code == "plan.required"
        ]
        assert len(blocked) == 1
        assert blocked[0].data.action == "continue_step"
        assert blocked[0].data.details == {"host_completion_candidate": True}
        assert any(
            e.type == "usage.recorded" and e.data.usage == POLICY_USAGE for e in events
        )
        state = await app.runtime.get_run(run_id)
        suspension = await store.get_suspension(state.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        assert interaction.payload["tool_name"] == "goal_submit"
        await app.runtime.reply_interaction(
            ReplyInteraction(
                run_id=run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=state.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision="approve_once",
                idempotency_key="approve-plan",
            ),
            CONTEXT,
        )
        async with asyncio.timeout(15):
            await app.entrypoint().continue_run(run_id, CONTEXT, agent=loaded)
            while (await app.runtime.get_run(run_id)).state.value in {
                "queued",
                "running",
                "resuming",
            }:
                await asyncio.sleep(0.01)
        assert (await app.runtime.get_run(run_id)).state.value == "completed"
        assert len(model.requests) == 3
        goal = await goals.get(run_id)
        assert goal is not None and goal.source == "plan"
        events = await store.read_events(run_id)
        assert any(
            e.type == "tool.call.succeeded" and e.data.tool_name == "goal_submit"
            for e in events
        )
        assert [
            e.data.reason_code for e in events if e.type == "continuation.decided"
        ] == [
            "plan.required",
            "plan.explanation_required",
            "plan.submitted",
        ]
    finally:
        await app.close()
        await bindings.close()
