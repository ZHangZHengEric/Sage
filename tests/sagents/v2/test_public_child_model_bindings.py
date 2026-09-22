"""Public Builder/manifest/Run APIs only: no private composition patches."""

import asyncio
import json

import pytest

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.contracts.commands import InputItem, ReplyInteraction, RunConfig
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.manifest import SageManifest
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.tool.contracts import ToolDefinition, ToolExecutionResult
from sagents.v2.tool.plugins.ephemeral import EphemeralToolPlugin


CONTEXT = RequestContext(actor=ActorRef(principal_id="owner", principal_type="user"))


def package(mode, *, override=None, allowed=("a", "b", "c"), dynamic=False):
    models = {
        name: {"provider": "openai-compatible", "model": name}
        for name in ("a", "b", "c")
    }
    delegation_tool = (
        "sys_team_delegate_task" if mode == "team" else "sys_delegate_task"
    )
    return SageManifest.model_validate(
        {
            "schema_version": "sage/v2",
            "kind": "application",
            "metadata": {
                "id": "test.child-bindings",
                "version": "1.0.0",
                "name": "Child bindings",
            },
            "models": models,
            "agents": {
                "main": {
                    "name": "Main",
                    "mode": mode,
                    "instructions": {"inline": "Delegate."},
                    "models": {"primary": "a", "option_b": "b", "option_c": "c"},
                    "tools": [
                        "probe",
                        delegation_tool,
                        *(["sys_spawn_agent"] if dynamic else []),
                    ],
                    "subagents": [] if dynamic else ["worker"],
                },
                "worker": {
                    "name": "Worker",
                    "instructions": {"inline": "Do the task."},
                    "models": {
                        "primary": "a",
                        **{f"option_{name}": name for name in allowed},
                    },
                    "delegation_model_bindings": {"primary": override}
                    if override
                    else {},
                    "tools": ["probe"],
                },
            },
            "entrypoint": {"agent": "main"},
        }
    )


class Model:
    def __init__(self, store, mode, dynamic=False):
        self.store, self.mode, self.dynamic = store, mode, dynamic
        self.requests = []
        self.commands = {}
        self.parent_gate = None
        self.parent_entered = asyncio.Event()

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
        command = await self.store.get_start_command(request.run_id)
        self.commands[request.run_id] = command
        self.requests.append(request)
        if not command.parent_run_id and self.parent_gate is not None:
            self.parent_entered.set()
            await self.parent_gate.wait()
        own_results = [
            m
            for m in request.messages
            if m.role == "tool" and request.run_id in (m.tool_call_id or "")
        ]
        if command.parent_run_id:
            name, arguments, prefix = "probe", {}, "probe"
            done = any(m.tool_call_id.startswith("probe_") for m in own_results)
        else:
            done = any(m.tool_call_id.startswith("delegate_") for m in own_results)
            spawned = next(
                (m for m in own_results if m.tool_call_id.startswith("spawn_")), None
            )
            if self.dynamic and spawned is None:
                name, prefix = "sys_spawn_agent", "spawn"
                arguments = {
                    "name": "Dynamic",
                    "description": "Worker",
                    "system_prompt": "Do the task.",
                }
            else:
                worker = "worker"
                if self.dynamic:
                    worker = next(
                        block.value["agent_id"]
                        for block in spawned.content
                        if block.kind == "json"
                    )
                name = (
                    "sys_team_delegate_task"
                    if self.mode == "team"
                    else "sys_delegate_task"
                )
                prefix, arguments = (
                    "delegate",
                    {"tasks": [{"agent_id": worker, "content": "Probe"}]},
                )
        yield ModelStreamEvent(
            kind="completed",
            response=ModelResponse(
                response_id=request.request_id,
                text="done" if done else "",
                tool_calls=()
                if done
                else (
                    ModelToolCall(
                        tool_call_id=f"{prefix}_{request.run_id}",
                        name=name,
                        arguments=arguments,
                    ),
                ),
                finish_reason="stop" if done else "tool_calls",
            ),
        )


async def build(root, manifest, *, approval=False, dynamic=False):
    store = FilesystemSessionStore(root)
    model = Model(store, manifest.agents["main"].mode, dynamic)
    calls = []

    async def probe(call, context):
        calls.append(call)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="ok"),),
        )

    plugin = EphemeralToolPlugin(
        (
            ToolDefinition(
                name="probe",
                description="Record the child's call",
                input_schema={"type": "object", "properties": {}},
                side_effect_level="write" if approval else "none",
            ),
        ),
        {"probe": probe},
    )
    try:
        app = await (
            SAgentBuilder()
            .with_session_store(store)
            .with_derived_state_store(store)
            .with_model_provider(model)
            .with_tool_provider(plugin.catalog, plugin.executor)
            .build(manifest)
        )
    except BaseException:
        await store.close()
        raise
    return app, store, model, calls


async def start(app, manifest, route, key):
    config = CompositionResolver().resolve_run_config(
        CompositionResolver().resolve(manifest),
        "main",
        model_bindings={"primary": route},
    )
    return await app.entrypoint().run_stream(
        StartRun(
            agent_id="main",
            session_id=key,
            input=(InputItem(role="user", content=(TextBlock(text="Delegate"),)),),
            config=config,
            resolved_spec_hash=app.composition_hash,
            idempotency_key=key,
        ),
        CONTEXT,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["team", "fibre"])
@pytest.mark.parametrize("override", [None, "c"])
async def test_public_children_persist_inherited_or_explicit_routes(
    tmp_path, mode, override
):
    manifest = package(mode, override=override)
    app, store, model, calls = await build(tmp_path, manifest)
    try:
        streams = [
            await start(app, manifest, route, f"parent-{route}") for route in ("a", "b")
        ]
        results = await asyncio.wait_for(
            asyncio.gather(*(s.wait() for s in streams)), 10
        )
        assert all(r.state.value == "completed" for r in results)
        assert len(calls) == 2
        expected = {
            s.handle.run_id: override or route for s, route in zip(streams, ("a", "b"))
        }
        for call in calls:
            command = await store.get_start_command(call.owner_run_id)
            assert (
                command.config.model_bindings["primary"]
                == expected[command.parent_run_id]
            )
            assert {
                r.model_binding for r in model.requests if r.run_id == call.owner_run_id
            } == {expected[command.parent_run_id]}
    finally:
        await app.close()
        await store.close()


@pytest.mark.asyncio
async def test_public_fibre_spawn_inherits_parent_model_policy(tmp_path):
    manifest = package("fibre", dynamic=True)
    app, store, model, calls = await build(tmp_path, manifest, dynamic=True)
    try:
        stream = await start(app, manifest, "b", "dynamic-parent")
        assert (await asyncio.wait_for(stream.wait(), 10)).state.value == "completed"
        assert len(calls) == 1, [
            m.model_dump()
            for r in model.requests
            for m in r.messages
            if m.role == "tool"
        ]
        command = await store.get_start_command(calls[0].owner_run_id)
        assert command.agent_id != "worker"
        assert command.config.model_bindings["primary"] == "b"
        assert {
            r.model_binding for r in model.requests if r.run_id == calls[0].owner_run_id
        } == {"b"}
    finally:
        await app.close()
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["team", "fibre"])
async def test_public_child_policy_rejects_parent_route_before_child_creation(
    tmp_path, mode
):
    manifest = package(mode, allowed=("a",))
    app, store, model, calls = await build(tmp_path, manifest)
    try:
        stream = await start(app, manifest, "b", "denied-parent")
        await asyncio.wait_for(stream.wait(), 10)
        assert not calls
        assert not [c for c in model.commands.values() if c.parent_run_id]
        assert not await store.list_descendant_sessions(stream.handle.session_id)
        messages = [
            m.model_dump(mode="json")
            for r in model.requests
            for m in r.messages
            if m.role == "tool"
        ]
        assert "manifest.model_override_denied" in json.dumps(messages)
    finally:
        await app.close()
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["team", "fibre"])
@pytest.mark.parametrize("reopen", [False, True])
async def test_public_child_approval_resume_keeps_persisted_route(
    tmp_path, mode, reopen
):
    manifest = package(mode)
    app, store, model, calls = await build(tmp_path, manifest, approval=True)
    try:
        stream = await start(app, manifest, "b", "paused-parent")
        outcome = await asyncio.wait_for(stream.wait(), 10)
        assert outcome.state.value == "suspended"
        children = [run_id for run_id, c in model.commands.items() if c.parent_run_id]
        assert len(children) == 1
        child_id = children[0]
        original = await store.get_start_command(child_id)
        assert original.config.model_bindings["primary"] == "b"
        if reopen:
            await app.close()
            await store.close()
            app, store, model, calls = await build(
                tmp_path, package(mode), approval=True
            )
        else:
            # Updating the source definition must not change the accepted Run.
            manifest.agents["worker"].delegation_model_bindings["primary"] = "c"
            manifest.agents["worker"].models["primary"] = "c"
        run = await store.get_run(outcome.run_id)
        suspension = await store.get_suspension(run.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        receipt = await app.entrypoint().runtime.reply_interaction(
            ReplyInteraction(
                run_id=run.run_id,
                suspension_id=suspension.suspension_id,
                interaction_id=interaction.interaction_id,
                expected_revision=run.revision,
                expected_suspension_revision=suspension.expected_revision,
                expected_interaction_revision=interaction.expected_revision,
                decision="approve_once",
                idempotency_key="approve-child",
            ),
            CONTEXT,
        )
        assert receipt.decision.value == "accepted"
        execution = await app.entrypoint().continue_run(run.run_id, CONTEXT)
        assert (await asyncio.wait_for(execution, 10)).state.value == "completed"
        assert len(calls) == 1
        assert calls[0].owner_run_id == child_id
        assert (
            await store.get_start_command(child_id)
        ).config.model_bindings == original.config.model_bindings
        assert {r.model_binding for r in model.requests if r.run_id == child_id} == {
            "b"
        }
    finally:
        await app.close()
        await store.close()


def test_public_resolver_priority_and_rejection():
    manifest = package("team", allowed=("a",), override="a")
    resolved = CompositionResolver().resolve(manifest)
    parent = RunConfig(model_bindings={"primary": "b", "parent_only": "c"})
    child = CompositionResolver().resolve_child_run_config(
        resolved, "worker", parent_config=parent
    )
    assert child.model_bindings["primary"] == "a"
    assert "parent_only" not in child.model_bindings
    manifest.agents["worker"].delegation_model_bindings["primary"] = "b"
    with pytest.raises(SageV2Error, match="policy ceiling"):
        CompositionResolver().resolve(manifest)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["team", "fibre"])
async def test_public_resolved_package_is_snapshotted_before_delegation(tmp_path, mode):
    manifest = package(mode)
    resolved = CompositionResolver().resolve(manifest)
    app, store, model, calls = await build(tmp_path, resolved)
    model.parent_gate = asyncio.Event()
    try:
        stream = await start(app, manifest, "b", "snapshot-parent")
        await asyncio.wait_for(model.parent_entered.wait(), 10)
        resolved.agents["worker"].delegation_model_bindings["primary"] = "c"
        model.parent_gate.set()
        assert (await asyncio.wait_for(stream.wait(), 10)).state.value == "completed"
        assert len(calls) == 1
        child_id = calls[0].owner_run_id
        assert (await store.get_start_command(child_id)).config.model_bindings[
            "primary"
        ] == "b"
        assert {r.model_binding for r in model.requests if r.run_id == child_id} == {
            "b"
        }
    finally:
        model.parent_gate.set()
        await app.close()
        await store.close()
