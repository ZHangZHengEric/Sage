from __future__ import annotations

import asyncio
from builtins import BaseExceptionGroup

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.agent.policy import DefaultToolPolicy, ApprovalStrategy
from sagents.v2.agent.management import (
    AgentManagementService,
    AgentPackageBundle,
    AgentPackageStore,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.plugins.agent_management import AgentManagementToolPlugin


def context(user="alice", tenant="one"):
    return RequestContext(
        actor=ActorRef(
            principal_id=user, principal_type=PrincipalType.USER, tenant_id=tenant
        )
    )


def bundle(version="1.0.0"):
    data = BuiltinPackageFactory.create(
        "assistant", package_id="com.test.expert", model="test"
    ).model_dump(mode="json")
    data["metadata"]["version"] = version
    key = data["entrypoint"]["agent"]
    data["agents"][key]["instructions"] = {"path": "prompts/expert.md"}
    data["agents"][key]["budgets"] = {"max_steps": 3, "total_tokens": 12000}
    return AgentPackageBundle.model_validate(
        {
            "manifest": data,
            "files": {"prompts/expert.md": "You are a specialist in unit conversions."},
        }
    )


@pytest.mark.asyncio
async def test_managed_builds_are_shared_but_do_not_block_other_agents(tmp_path):
    started = {name: asyncio.Event() for name in ("alice", "bob")}
    release = asyncio.Event()
    calls = []
    closed = []

    class App:
        async def close(self):
            closed.append(self)

    class Builder:
        async def build(self, *args, **kwargs):
            return App()

    async def factory(package, root, ctx):
        name = ctx.actor.principal_id
        calls.append(name)
        started[name].set()
        await release.wait()
        return Builder()

    async def allow(*args):
        pass

    svc = AgentManagementService(
        tmp_path, builder_factory=factory, authorize=allow, max_applications=2
    )
    package = bundle()
    tasks = [
        asyncio.create_task(svc._application(package, "assistant", context(name)))
        for name in ("alice", "alice", "bob")
    ]
    try:
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in started.values())), 2
        )
        assert sorted(calls) == ["alice", "bob"]
        with pytest.raises(ValueError, match="capacity"):
            await svc._application(package, "assistant", context("charlie"))
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        shutdown = asyncio.create_task(svc.close())
        await asyncio.sleep(0)
        assert not shutdown.done()
        release.set()
        await asyncio.gather(*tasks[1:], shutdown)
        assert len(closed) == 2
        assert not svc._applications
        assert not svc._application_builds
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await svc.close()


def model(text="converted", count=4):
    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="done", text=text, finish_reason="stop"
                        ),
                    ),
                )
            )
            for _ in range(count)
        )
    )


def service(root, *, authorize=None):
    models = []

    async def allow(action, package, ctx):
        return None

    def build(package, run_root, ctx):
        provider = model()
        models.append(provider)
        return (
            SAgentBuilder()
            .with_defaults(session_root=run_root)
            .with_model_provider(provider)
        )

    return AgentManagementService(
        root, builder_factory=build, authorize=authorize or allow
    ), models


async def settled(svc, op, ctx):
    async with asyncio.timeout(5):
        while True:
            value = await svc.status(op, ctx)
            if value["terminal"] or value["needs_attention"]:
                return value
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_full_package_create_execute_continue_and_restart(tmp_path):
    svc, models = service(tmp_path)
    ctx = context()
    package = bundle()
    saved = await svc.save(package, ctx)
    agent_id = package.manifest.entrypoint.agent
    first = await svc.run(saved["ref"], agent_id, "Convert 2 km to m", "first", ctx)
    result = await settled(svc, "first", ctx)
    assert result["run"]["state"] == "completed", result
    assert "converted" in str(result["result"])
    assert "specialist in unit conversions" in str(models[-1].requests)
    duplicate = await svc.run(saved["ref"], agent_id, "Convert 2 km to m", "first", ctx)
    assert duplicate["run_id"] == first["run_id"]
    second = await svc.run(
        saved["ref"],
        agent_id,
        "Now use cm",
        "second",
        ctx,
        session_id=first["session_id"],
    )
    assert second["session_id"] == first["session_id"]
    assert (await settled(svc, "second", ctx))["terminal"]
    await svc.close()
    fresh, _ = service(tmp_path)
    assert (await fresh.get(saved["ref"], ctx)) == package
    assert (await fresh.status("first", ctx))["terminal"]
    third = await fresh.run(
        saved["ref"], agent_id, "Again", "third", ctx, session_id=first["session_id"]
    )
    assert third["session_id"] == first["session_id"]
    assert (await settled(fresh, "third", ctx))["terminal"]
    await fresh.close()


@pytest.mark.asyncio
async def test_version_conflict_fork_activation_and_scope(tmp_path):
    svc, _ = service(tmp_path)
    ctx = context()
    one = await svc.save(bundle(), ctx)
    changed = bundle().model_dump(mode="json")
    changed["files"]["prompts/expert.md"] = "changed"
    with pytest.raises(ValueError, match="immutable"):
        await svc.save(AgentPackageBundle.model_validate(changed), ctx)
    two = await svc.fork(one["ref"], "com.test.expert", "2.0.0", ctx)
    await svc.activate(one["ref"], None, ctx)
    await svc.activate(two["ref"], one["ref"], ctx)
    with pytest.raises(ValueError, match="conflict"):
        await svc.activate(one["ref"], one["ref"], ctx)
    await svc.activate(one["ref"], two["ref"], ctx)
    assert len(await svc.list(ctx)) == 2
    assert not await svc.list(context("bob"))
    assert not await svc.list(context(tenant="two"))
    with pytest.raises(ValueError, match="caller scope"):
        await svc.get(one["ref"], context("bob"))
    await svc.close()


@pytest.mark.asyncio
async def test_authorize_before_build_and_every_execution(tmp_path):
    actions = []

    async def deny(action, package, ctx):
        actions.append(action)
        raise PermissionError("host grant denied")

    svc, models = service(tmp_path, authorize=deny)
    with pytest.raises(PermissionError):
        await svc.save(bundle(), context())
    assert not models
    assert actions == ["save"]
    await svc.close()


@pytest.mark.parametrize(
    "name", ["../escape", "/tmp/escape", "a/../b", "a//b", "a\\b", "sage.yaml"]
)
def test_bundle_rejects_unsafe_paths(name):
    with pytest.raises(ValueError):
        AgentPackageBundle(manifest=bundle().manifest, files={name: "x"})


@pytest.mark.asyncio
async def test_store_concurrent_version_writes(tmp_path):
    a = AgentPackageStore(tmp_path / "db.sqlite")
    b = AgentPackageStore(tmp_path / "db.sqlite")
    original = bundle()
    changed = original.model_copy(update={"files": {"prompts/expert.md": "different"}})
    results = await asyncio.gather(
        a.save("user", original), b.save("user", changed), return_exceptions=True
    )
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(await a.list("user")) == 1


def test_management_tools_publish_complete_schema(tmp_path):
    svc, _ = service(tmp_path)
    plugin = AgentManagementToolPlugin(svc)
    names = {d.name for d in plugin.definitions}
    assert {
        "agent_package_schema",
        "agent_package_save",
        "agent_package_run",
        "agent_package_status",
    } <= names
    schema = svc.schema()["bundle_schema"]
    assert {"agents", "flows", "plugins", "models", "runtime"} <= schema["$defs"][
        "SageManifest"
    ]["properties"].keys()


def tool_step(name, arguments, call_id):
    from sagents.v2.model.contracts import ModelToolCall

    return ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=call_id,
                    finish_reason="tool_calls",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id=call_id, name=name, arguments=arguments
                        ),
                    ),
                ),
            ),
        )
    )


@pytest.mark.asyncio
async def test_parent_model_creates_and_invokes_full_agent(tmp_path):
    from sagents.v2.contracts.commands import StartRun, InputItem
    from sagents.v2.contracts.items import TextBlock

    child = bundle()
    svc, _ = service(tmp_path / "management")
    plugin = AgentManagementToolPlugin(svc)
    parent = BuiltinPackageFactory.create(
        "assistant", package_id="parent", model="test"
    ).model_dump(mode="json")
    parent["agents"]["assistant"]["tools"] = [d.name for d in plugin.definitions]
    parent["agents"]["assistant"]["budgets"] = {"max_steps": 8}
    from sagents.v2.package.manifest import SageManifest

    provider = ScriptedModelProvider(
        (
            tool_step(
                "agent_package_save",
                {"bundle": child.model_dump(mode="json")},
                "create",
            ),
            tool_step(
                "agent_package_run",
                {
                    "ref": child.content_hash,
                    "agent_id": "assistant",
                    "content": "Convert units",
                    "operation": "parent-created",
                },
                "invoke",
            ),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="done",
                            text="Created and invoked",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    app = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "parent")
        .with_model_provider(provider)
        .with_tool_policy(
            DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
        )
        .with_agent_management(svc)
        .build(SageManifest.model_validate(parent))
    )
    try:
        stream = await app.entrypoint().run_stream(
            StartRun(
                agent_id="assistant",
                input=(
                    InputItem(
                        role="user", content=(TextBlock(text="Create an expert"),)
                    ),
                ),
                resolved_spec_hash=app.composition_hash,
                idempotency_key="parent",
            ),
            context(),
        )
        result = await stream.wait()
        await stream.detach()
        assert result.state.value == "completed"
        assert len(await svc.list(context())) == 1
        assert (await settled(svc, "parent-created", context()))["run"][
            "state"
        ] == "completed"
        assert "agent_package_save" in str(provider.requests[0].tools)
    finally:
        await app.close()
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["host", "plugin"])
async def test_builder_executes_declared_flow_and_custom_node(tmp_path, binding):
    from sagents.v2.flow import FlowNodeResult

    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["worker"] = data["manifest"]["agents"][
        "assistant"
    ].copy()
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "pipeline",
    }
    data["manifest"]["flows"] = {
        "pipeline": {
            "version": "1",
            "start": "calculate",
            "nodes": [
                {
                    "id": "calculate",
                    "type": "tool",
                    "tool": "calculate",
                    "config": {"factor": 7},
                },
                {"id": "worker", "type": "agent", "agent": "worker"},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "calculate", "to": "worker"},
                {"from": "worker", "to": "end"},
            ],
        }
    }
    calls = []

    class Node:
        async def run(self, ctx):
            calls.append(ctx)
            return FlowNodeResult(output={"answer": ctx.config["factor"] * 6})

    async def allow(action, package, ctx):
        pass

    def build(package, root, ctx):
        return (
            SAgentBuilder()
            .with_defaults(session_root=root)
            .with_model_provider(model())
            .with_flow_tool_nodes({"calculate": Node()})
        )

    if binding == "plugin":
        from sagents.v2.runtime.extensions import (
            CapabilityOffer,
            ExtensionDescriptor,
            ExtensionRegistration,
            ExtensionScope,
        )

        data["manifest"]["plugins"] = [{"id": "test.flow-node", "version": "1.0.0"}]
        data["manifest"]["runtime"]["capabilities"] = {
            "flow.node": {"plugin": "test.flow-node", "name": "calculate"}
        }
        registration = ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="test.flow-node",
                version="1.0.0",
                name="Calculate",
                provides=(
                    CapabilityOffer(
                        capability="flow.node", api_version="2", name="wrong-first"
                    ),
                    CapabilityOffer(
                        capability="flow.node", api_version="2", name="calculate"
                    ),
                ),
                supported_scopes=frozenset({ExtensionScope.AGENT}),
            ),
            factory=lambda ctx, deps: Node(),
            start=lambda node, ctx, deps: {
                "flow.node:wrong-first": object(),
                "flow.node:calculate": node,
            },
        )

        def build(package, root, ctx):
            return (
                SAgentBuilder()
                .with_defaults(session_root=root)
                .with_model_provider(model())
                .register(registration)
            )

    package = AgentPackageBundle.model_validate(data)
    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    try:
        saved = await svc.save(package, context())
        await svc.run(saved["ref"], "assistant", "Calculate", "flow", context())
        result = await settled(svc, "flow", context())
        assert result["run"]["state"] == "completed", result
        assert len(calls) == 1
        assert calls[0].node_id == "calculate"
        assert result["flow_results"]["calculate"]["answer"] == 42
        await svc.close()
        svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
        assert (await svc.status("flow", context()))["flow_results"]["calculate"][
            "answer"
        ] == 42
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_managed_agent_selects_standard_plugin_and_configuration(tmp_path):
    from sagents.v2.runtime.extensions import (
        CapabilityOffer,
        ExtensionDescriptor,
        ExtensionRegistration,
        ExtensionScope,
    )
    from sagents.v2.tool.decorated import DecoratedToolProvider
    from sagents.v2.tool.decorators import tool

    calls = []

    class Scale:
        def __init__(self, factor):
            self.factor = factor

        @tool(description="Scale a value")
        async def scale(self, value: int) -> dict:
            calls.append((self.factor, value))
            return {"value": value * self.factor}

    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.scale",
            version="1.0.0",
            name="Scale",
            provides=(
                CapabilityOffer(
                    capability="tool.catalog", api_version="2", name="wrong"
                ),
                CapabilityOffer(
                    capability="tool.executor", api_version="2", name="wrong"
                ),
                CapabilityOffer(
                    capability="tool.catalog", api_version="2", name="scale"
                ),
                CapabilityOffer(
                    capability="tool.executor", api_version="2", name="scale"
                ),
            ),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema={
                "type": "object",
                "properties": {"factor": {"type": "integer"}},
                "required": ["factor"],
                "additionalProperties": False,
            },
        ),
        factory=lambda ctx, deps: DecoratedToolProvider(Scale(ctx.config["factor"])),
        start=lambda provider, ctx, deps: {
            "tool.catalog:wrong": object(),
            "tool.executor:wrong": object(),
            "tool.catalog:scale": provider.catalog,
            "tool.executor:scale": provider.executor,
        },
    )
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["tools"] = ["scale"]
    data["manifest"]["plugins"] = [
        {"id": "test.scale", "version": "1.0.0", "config": {"factor": 9}}
    ]
    data["manifest"]["runtime"]["capabilities"] = {
        "tool.catalog": {"plugin": "test.scale", "name": "scale"}
    }
    package = AgentPackageBundle.model_validate(data)

    async def allow(action, bundle, ctx):
        pass

    def build(bundle, root, ctx):
        provider = ScriptedModelProvider(
            (
                tool_step("scale", {"value": 4}, "scale"),
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED,
                            response=ModelResponse(
                                response_id="done", text="36", finish_reason="stop"
                            ),
                        ),
                    )
                ),
            )
        )
        return (
            SAgentBuilder()
            .with_defaults(session_root=root)
            .register(registration)
            .with_model_provider(provider)
        )

    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    try:
        saved = await svc.save(package, context())
        await svc.run(saved["ref"], "assistant", "Scale", "scale", context())
        assert (await settled(svc, "scale", context()))["run"]["state"] == "completed"
        assert calls == [(9, 4)]
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_managed_agent_loads_its_selected_skill(tmp_path):
    from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor
    from sagents.v2.skill.plugins.ephemeral import (
        InMemorySkillProvider,
        InMemorySkillWorkspace,
    )

    skill = SkillBundle(
        descriptor=SkillDescriptor(
            name="unit-check", description="Check unit conversion", source_id="test"
        ),
        files={"SKILL.md": b"Always verify unit dimensions before reporting."},
        content_hash="unit-v1",
    )
    source = InMemorySkillProvider((skill,))
    ctx = context()
    ctx = ctx.model_copy(
        update={"actor": ctx.actor.model_copy(update={"scopes": ("skill.load",)})}
    )
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["skills"] = ["unit-check"]
    data["manifest"]["agents"]["assistant"]["tools"] = ["load_skill"]
    requests = []

    async def allow(action, bundle, ctx):
        pass

    def build(bundle, root, ctx):
        provider = ScriptedModelProvider(
            (
                tool_step("load_skill", {"skill_name": "unit-check"}, "load"),
                ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED,
                            response=ModelResponse(
                                response_id="done", text="checked", finish_reason="stop"
                            ),
                        ),
                    )
                ),
            )
        )
        requests.append(provider.requests)
        return (
            SAgentBuilder()
            .with_defaults(session_root=root)
            .with_model_provider(provider)
            .with_skill_provider(source, source, InMemorySkillWorkspace())
            .with_tool_policy(
                DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
            )
        )

    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    try:
        saved = await svc.save(AgentPackageBundle.model_validate(data), ctx)
        first = await svc.run(saved["ref"], "assistant", "Check", "skill", ctx)
        result = await settled(svc, "skill", ctx)
        assert result["run"]["state"] == "completed", result
        assert source.fetches, str(requests[-1])
        assert "Always verify unit dimensions" in str(requests[-1][-1])
        # Recreate the host so restoration cannot rely on in-memory Run state.
        await svc.close()
        svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
        await svc.run(
            saved["ref"], "assistant", "Continue", "skill_next", ctx,
            session_id=first["session_id"],
        )
        continued = await settled(svc, "skill_next", ctx)
        assert continued["run"]["state"] == "completed", continued
        # The very first request must already contain the complete skill body.
        assert "Always verify unit dimensions" in str(requests[-1][0])
    finally:
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user_input", "approval"])
async def test_managed_flow_question_resume_or_host_approval(tmp_path, kind):
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "question",
    }
    data["manifest"]["flows"] = {
        "question": {
            "version": "1",
            "start": "ask",
            "nodes": [
                {
                    "id": "ask",
                    "type": "interaction",
                    "config": {
                        "interaction_type": kind,
                        "payload": {"prompt": "Which units?"},
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "ask", "to": "end"}],
        }
    }
    svc, _ = service(tmp_path)
    try:
        saved = await svc.save(AgentPackageBundle.model_validate(data), context())
        await svc.run(saved["ref"], "assistant", "Ask", "question", context())
        pending = await settled(svc, "question", context())
        assert pending["needs_attention"]
        assert pending["interaction"]["interaction_type"] == kind
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 0
        await svc.close()
        svc, _ = service(tmp_path)
        await svc.status("question", context())
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 0
        if kind == "user_input":
            reply = await svc.control(
                "question",
                "reply",
                context(),
                decision="submit",
                interaction_id=pending["interaction"]["interaction_id"],
                payload={"text": "meters"},
            )
            assert reply["decision"] == "accepted"
            assert (await settled(svc, "question", context()))["run"][
                "state"
            ] == "completed"
        else:
            with pytest.raises(ValueError, match="resolved by the host"):
                await svc.control(
                    "question",
                    "reply",
                    context(),
                    decision="approve",
                    interaction_id=pending["interaction"]["interaction_id"],
                )
            await svc.control("question", "cancel", context())
            assert (await settled(svc, "question", context()))["run"][
                "state"
            ] == "cancelled"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_operation_conflict_and_cross_version_session_rejected(tmp_path):
    svc, _ = service(tmp_path)
    try:
        first = await svc.save(bundle(), context())
        handle = await svc.run(first["ref"], "assistant", "One", "op", context())
        await settled(svc, "op", context())
        with pytest.raises(ValueError, match="different invocation"):
            await svc.run(first["ref"], "assistant", "Changed", "op", context())
        second = await svc.save(bundle("2.0.0"), context())
        with pytest.raises(ValueError, match="session does not belong"):
            await svc.run(
                second["ref"],
                "assistant",
                "Two",
                "next",
                context(),
                session_id=handle["session_id"],
            )
        with pytest.raises(ValueError, match="caller scope"):
            await svc.status("op", context("bob"))
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_created_agent_can_create_another_agent_when_granted(tmp_path):
    leaf = bundle().model_dump(mode="json")
    leaf["manifest"]["metadata"]["id"] = "leaf"
    leaf = AgentPackageBundle.model_validate(leaf)

    async def allow(action, package, ctx):
        pass

    def build(package, root, ctx):
        provider = model()
        if package.manifest.metadata.id == "maker":
            provider = ScriptedModelProvider(
                (
                    tool_step(
                        "agent_package_save",
                        {"bundle": leaf.model_dump(mode="json")},
                        "save-leaf",
                    ),
                    ScriptedModelStep(
                        events=(
                            ModelStreamEvent(
                                kind=ModelEventKind.COMPLETED,
                                response=ModelResponse(
                                    response_id="done",
                                    text="Created leaf",
                                    finish_reason="stop",
                                ),
                            ),
                        )
                    ),
                )
            )
        return (
            SAgentBuilder()
            .with_defaults(session_root=root)
            .with_model_provider(provider)
            .with_agent_management(svc)
            .with_tool_policy(
                DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
            )
        )

    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    data = bundle().model_dump(mode="json")
    data["manifest"]["metadata"]["id"] = "maker"
    data["manifest"]["agents"]["assistant"]["tools"] = ["agent_package_save"]
    try:
        saved = await svc.save(AgentPackageBundle.model_validate(data), context())
        await svc.run(
            saved["ref"], "assistant", "Create another expert", "maker", context()
        )
        assert (await settled(svc, "maker", context()))["run"]["state"] == "completed"
        assert (
            await svc.get(leaf.content_hash, context())
        ).manifest.metadata.id == "leaf"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_bundle_preserves_resources_and_instruction_whitespace(tmp_path):
    from sagents.v2.package.manifest import CompositionResolver
    from sagents.v2.agent.multi_agent.contracts import AgentDescriptor

    data = bundle().model_dump(mode="json")
    text = "  indented instruction\n\n"
    data["files"] = {"prompts/expert.md": text, "plugin.py": "\n# source\n\n"}
    package = AgentPackageBundle.model_validate(data)
    store = AgentPackageStore(tmp_path / "packages.sqlite")
    ref = await store.save("owner", package)
    restored = await store.get("owner", ref)
    assert restored.files == data["files"]
    resolved = CompositionResolver().resolve(restored.resolved_manifest())
    assert resolved.agents["assistant"].instructions == text
    assert (
        AgentDescriptor(
            agent_id="assistant", name="Test", description="test", instructions=text
        ).instructions
        == text
    )


@pytest.mark.asyncio
async def test_save_snapshots_input_and_finishes_during_shutdown(tmp_path):
    authorized = asyncio.Event()
    release = asyncio.Event()

    async def allow(action, package, ctx):
        if action == "save":
            authorized.set()
            await release.wait()

    svc, _ = service(tmp_path, authorize=allow)
    package = bundle()
    original = package.content_hash
    saving = asyncio.create_task(svc.save(package, context()))
    await authorized.wait()
    package.files["prompts/expert.md"] = "Changed after authorization began"
    shutdown = asyncio.create_task(svc.close())
    await asyncio.sleep(0)
    release.set()
    try:
        report, _ = await asyncio.gather(saving, shutdown)
        assert report["ref"] == original
        assert (await svc.get(original, context())).content_hash == original
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_reply_retries_survive_resume_failure_and_never_answer_next_question(
    tmp_path, monkeypatch
):
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "questions",
    }
    data["manifest"]["flows"] = {
        "questions": {
            "version": "1",
            "start": "first",
            "nodes": [
                {
                    "id": name,
                    "type": "interaction",
                    "config": {
                        "interaction_type": "user_input",
                        "payload": {"prompt": name},
                    },
                }
                for name in ("first", "second")
            ]
            + [{"id": "end", "type": "end"}],
            "edges": [
                {"from": "first", "to": "second"},
                {"from": "second", "to": "end"},
            ],
        }
    }
    svc, _ = service(tmp_path)
    try:
        saved = await svc.save(AgentPackageBundle.model_validate(data), context())
        await svc.run(saved["ref"], "assistant", "Ask twice", "questions", context())
        first = await settled(svc, "questions", context())
        question = first["interaction"]["interaction_id"]
        app = await svc._application(
            await svc.get(saved["ref"], context()), "assistant", context()
        )
        native = app.entrypoint()
        resume = native.continue_run

        async def interrupted(*args, **kwargs):
            raise RuntimeError("interrupted after reply persistence")

        monkeypatch.setattr(native, "continue_run", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            await svc.control(
                "questions",
                "reply",
                context(),
                interaction_id=question,
                decision="submit",
                payload={"text": "one"},
            )
        monkeypatch.setattr(native, "continue_run", resume)
        await svc.close()
        svc, _ = service(tmp_path)
        replays = await asyncio.gather(
            *(
                svc.control(
                    "questions",
                    "reply",
                    context(),
                    interaction_id=question,
                    decision="submit",
                    payload={"text": "one"},
                )
                for _ in range(8)
            )
        )
        assert all(replay["decision"] == "duplicate" for replay in replays)
        second = await settled(svc, "questions", context())
        assert second["interaction"]["interaction_id"] != question
        await svc.control(
            "questions",
            "reply",
            context(),
            interaction_id=question,
            decision="submit",
            payload={"text": "one"},
        )
        still_pending = await svc.status("questions", context())
        assert (
            still_pending["interaction"]["interaction_id"]
            == second["interaction"]["interaction_id"]
        )
        with pytest.raises(ValueError, match="stale"):
            await svc.control(
                "questions",
                "reply",
                context(),
                interaction_id=question,
                decision="submit",
                payload={"text": "changed"},
            )
        await svc.control(
            "questions",
            "reply",
            context(),
            interaction_id=second["interaction"]["interaction_id"],
            decision="submit",
            payload={"text": "two"},
        )
        assert (await settled(svc, "questions", context()))["terminal"]
    finally:
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_concurrent_managed_runs_are_isolated_and_duplicate_admission_is_once(
    tmp_path,
):
    import re
    import time

    providers = []

    class SlowModel(ScriptedModelProvider):
        active = 0
        peak = 0

        async def _stream(self, request):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                async for event in super()._stream(request):
                    yield event
            finally:
                self.active -= 1

    def build(package, root, ctx):
        provider = SlowModel(model(count=64)._steps)
        providers.append(provider)
        return (
            SAgentBuilder()
            .with_defaults(session_root=root)
            .with_model_provider(provider)
        )

    async def allow(*args):
        pass

    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    try:
        saved = await svc.save(bundle(), context())
        start = time.perf_counter()
        indices = list(range(24)) + [0] * 8
        handles = await asyncio.gather(
            *(
                svc.run(
                    saved["ref"],
                    "assistant",
                    f"task-marker-{index}",
                    f"parallel-{index}",
                    context(),
                )
                for index in indices
            )
        )
        assert len({item["run_id"] for item in handles}) == 24
        assert len({item["session_id"] for item in handles}) == 24
        assert all(item["run_id"] == handles[0]["run_id"] for item in handles[24:])
        results = await asyncio.gather(
            *(settled(svc, f"parallel-{index}", context()) for index in range(24))
        )
        assert all(item["run"]["state"] == "completed" for item in results)
        provider = providers[-1]
        assert len(provider.requests) == 24
        tags = [
            set(re.findall(r"task-marker-\d+", request.model_dump_json()))
            for request in provider.requests
        ]
        assert all(len(values) == 1 for values in tags)
        assert set().union(*tags) == {f"task-marker-{index}" for index in range(24)}
        assert provider.peak > 1
        print(
            f"\n24 unique + 8 duplicate admissions: {time.perf_counter() - start:.3f}s; peak model calls={provider.peak}"
        )
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_invocation_status_read_does_not_acquire_sqlite_write_lock(tmp_path):
    import sqlite3

    store = AgentPackageStore(tmp_path / "packages.sqlite")
    await store.invocation("owner", "op", "ref", "assistant", "request")
    writer = sqlite3.connect(store.path)
    writer.execute("BEGIN IMMEDIATE")
    reader = asyncio.create_task(store.invocation("owner", "op"))
    try:
        done, _ = await asyncio.wait({reader}, timeout=1)
        assert reader in done, "read-only status was blocked by a reserved writer lock"
        assert (await reader)["operation"] == "op"
    finally:
        writer.rollback()
        writer.close()
        await reader


@pytest.mark.asyncio
async def test_duplicate_saves_share_validation_and_conflicts_fail_before_build(
    tmp_path,
):
    authorizations = []

    async def allow(action, package, ctx):
        authorizations.append(action)

    svc, providers = service(tmp_path, authorize=allow)
    try:
        package = bundle()
        reports = await asyncio.gather(
            *(svc.save(package, context()) for _ in range(12))
        )
        assert len(providers) == 1
        assert sum(not report["reused"] for report in reports) == 1
        assert authorizations.count("save") == 12
        assert authorizations.count("validate") == 12
        changed = package.model_dump(mode="json")
        changed["files"]["prompts/expert.md"] = "Conflicting content"
        with pytest.raises(ValueError, match="immutable"):
            await svc.save(AgentPackageBundle.model_validate(changed), context())
        assert len(providers) == 1
        await svc.validate(package, context())
        assert (
            len(providers) == 2
        )  # Explicit validation always probes current providers.
        assert not svc._save_locks
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_build_limit_covers_validation_and_runtime_and_releases_cancelled_waiters(
    tmp_path,
):
    release = asyncio.Event()
    two_started = asyncio.Event()
    active = peak = built = closed = 0

    class App:
        async def close(self):
            nonlocal closed
            closed += 1

    class Builder:
        async def build(self, *args, **kwargs):
            return App()

    async def factory(package, root, ctx):
        nonlocal active, peak, built
        active += 1
        peak = max(peak, active)
        if active == 2:
            two_started.set()
        try:
            await release.wait()
            built += 1
            return Builder()
        finally:
            active -= 1

    async def allow(*args):
        pass

    svc = AgentManagementService(
        tmp_path, builder_factory=factory, authorize=allow, max_concurrent_builds=2
    )
    tasks = [
        asyncio.create_task(svc.validate(bundle(), context(str(i)))) for i in range(6)
    ]
    tasks += [
        asyncio.create_task(svc._application(bundle(), "assistant", context("runtime")))
    ]
    try:
        await asyncio.wait_for(two_started.wait(), 2)
        tasks[5].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[5]
        release.set()
        await asyncio.gather(*(task for index, task in enumerate(tasks) if index != 5))
        assert peak == 2
        assert built == 6
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await svc.close()
    assert closed == built


@pytest.mark.asyncio
async def test_session_ownership_uses_index_and_updates_with_handle(tmp_path):
    import sqlite3

    store = AgentPackageStore(tmp_path / "packages.sqlite")
    await store.invocation("owner", "op", "ref", "assistant", "request")
    assert not await store.owns_session("owner", "ref", "assistant", "session")
    await store.invocation("owner", "op", handle={"session_id": "session"})
    assert await store.owns_session("owner", "ref", "assistant", "session")
    assert not await store.owns_session("other", "ref", "assistant", "session")
    with sqlite3.connect(store.path) as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM invocations WHERE owner=? AND ref=? AND agent=? AND json_extract(handle, '$.session_id')=? LIMIT 1",
            ("owner", "ref", "assistant", "session"),
        ).fetchall()
    assert "invocation_session_lookup" in str(plan)


@pytest.mark.asyncio
async def test_cancelled_save_settles_validation_and_releases_version_lock(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()
    closed = []

    class App:
        async def close(self):
            closed.append(True)

    class Builder:
        async def build(self, *args, **kwargs):
            started.set()
            await release.wait()
            return App()

    async def allow(*args):
        pass

    svc = AgentManagementService(
        tmp_path,
        builder_factory=lambda *args: Builder(),
        authorize=allow,
        max_concurrent_builds=1,
    )
    first = asyncio.create_task(svc.save(bundle(), context()))
    second = None
    try:
        await started.wait()
        second = asyncio.create_task(svc.save(bundle(), context()))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()
        shutdown = asyncio.create_task(svc.close())
        await asyncio.sleep(0)
        assert not shutdown.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await shutdown
        assert closed == [True]
        assert not await svc.list(context())
        assert not svc._save_locks
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
        await svc.close()


@pytest.mark.asyncio
async def test_reply_revision_conflict_can_retry_same_answer(tmp_path, monkeypatch):
    from sagents.v2.contracts.run_state import RunState

    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {
        "type": "flow",
        "flow": "ask",
    }
    data["manifest"]["flows"] = {
        "ask": {
            "version": "1",
            "start": "question",
            "nodes": [
                {
                    "id": "question",
                    "type": "interaction",
                    "config": {
                        "interaction_type": "user_input",
                        "payload": {"prompt": "Choose"},
                    },
                },
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "question", "to": "end"}],
        }
    }
    svc, _ = service(tmp_path)
    try:
        saved = await svc.save(AgentPackageBundle.model_validate(data), context())
        await svc.run(saved["ref"], "assistant", "Ask", "ask", context())
        pending = await settled(svc, "ask", context())
        app = await svc._application(
            await svc.get(saved["ref"], context()), "assistant", context()
        )
        runtime = app.entrypoint().runtime
        reply = runtime.reply_interaction
        bumped = False

        async def reply_after_revision_change(command, ctx):
            nonlocal bumped
            if not bumped:
                bumped = True
                await runtime.session_store.commit_run(
                    run_id=command.run_id,
                    expected_revision=command.expected_revision,
                    expected_states={RunState.SUSPENDED},
                    new_state=RunState.SUSPENDED,
                    drafts=(),
                    context=ctx,
                    idempotency_key="concurrent-state-update",
                )
            return await reply(command, ctx)

        monkeypatch.setattr(runtime, "reply_interaction", reply_after_revision_change)
        kwargs = {
            "interaction_id": pending["interaction"]["interaction_id"],
            "decision": "submit",
            "payload": {"text": "answer"},
        }
        rejected = await svc.control("ask", "reply", context(), **kwargs)
        assert rejected["error"]["code"] == "run.revision_conflict"
        retried = await svc.control("ask", "reply", context(), **kwargs)
        assert retried["decision"] == "accepted"
        assert (await settled(svc, "ask", context()))["run"]["state"] == "completed"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_validation_close_failure_is_retained_and_retried(tmp_path):
    roots = []
    closes = []

    class App:
        async def close(self):
            closes.append(True)
            if len(closes) == 1:
                raise RuntimeError("temporary cleanup failure")

    class Builder:
        async def build(self, *args, **kwargs):
            return App()

    def build(bundle, root, ctx):
        roots.append(root)
        return Builder()

    async def allow(*args):
        pass

    svc = AgentManagementService(tmp_path, builder_factory=build, authorize=allow)
    with pytest.raises(RuntimeError, match="cleanup failure"):
        await svc.validate(bundle(), context())
    assert roots[0].exists()
    assert len(svc._validation_cleanup) == 1
    with pytest.raises(RuntimeError, match="closing"):
        await svc.save(bundle(), context())
    await svc.close()
    assert len(closes) == 2
    assert not roots[0].exists()
    assert not svc._validation_cleanup


@pytest.mark.asyncio
async def test_close_failure_keeps_managed_admission_closed_until_cleanup(tmp_path):
    svc, _ = service(tmp_path)
    saved = await svc.save(bundle(), context())
    app = await svc._application(
        await svc.get(saved["ref"], context()), "assistant", context()
    )

    class FailOnce:
        failed = False

        async def close(self):
            if not self.failed:
                self.failed = True
                raise RuntimeError("close once")

    app._owned_resources.append(FailOnce())
    with pytest.raises(BaseExceptionGroup):
        await svc.close()
    with pytest.raises(RuntimeError, match="closing"):
        await svc.run(saved["ref"], "assistant", "No admission", "new", context())
    await svc.close()
    assert svc._closed
    assert not svc._applications


@pytest.mark.asyncio
async def test_readiness_reports_missing_resources_and_strict_save_rejects(tmp_path):
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["tools"] = ["missing_tool"]
    data["manifest"]["agents"]["assistant"]["skills"] = ["missing_skill"]
    package = AgentPackageBundle.model_validate(data)

    async def allow(*args):
        pass

    def factory(package, root, ctx):
        return SAgentBuilder().with_defaults(session_root=root).with_model_provider(model())

    svc = AgentManagementService(tmp_path, builder_factory=factory, authorize=allow)
    try:
        report = await svc.validate(package, context(), readiness=True)
        assert report["valid"] is True
        assert report["readiness"]["ready"] is False
        resources = report["readiness"]["agents"]["assistant"]["agents"]["assistant"]
        assert resources["missing_tools"] == ["missing_tool"]
        assert resources["missing_skills"] == ["missing_skill"]
        svc.require_readiness = True
        with pytest.raises(ValueError, match="resources are not ready"):
            await svc.save(package, context())
        assert not await svc.list(context())
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_readiness_available_skill_and_deferred_catalog(tmp_path):
    from sagents.v2.agent.management.readiness import resource_readiness
    from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor
    from sagents.v2.skill.plugins.ephemeral import InMemorySkillProvider, InMemorySkillWorkspace
    from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog

    source = InMemorySkillProvider((SkillBundle(
        descriptor=SkillDescriptor(name="known", description="Known", source_id="test"),
        files={"SKILL.md": b"Instructions"}, content_hash="v1",
    ),))
    definition = bundle().manifest.agents["assistant"].model_copy(update={"tools": ("load_skill",), "skills": ("known",)})
    report = await resource_readiness(definition, InMemoryToolCatalog(()),
        skill_provider=(source, source, InMemorySkillWorkspace()))
    assert report["ready"] is True
    assert not source.fetches
    report = await resource_readiness(definition, InMemoryToolCatalog(()), deferred_tools=True)
    assert report["ready"] is False
    assert report["unverified"]


@pytest.mark.asyncio
async def test_idle_release_reads_archived_result_without_rebuilding_application(tmp_path):
    async def allow(*args):
        pass

    def factory(package, root, ctx):
        return SAgentBuilder().with_defaults(session_root=root).with_model_provider(model())

    svc = AgentManagementService(tmp_path, builder_factory=factory, authorize=allow, max_applications=1)
    try:
        saved = await svc.save(bundle(), context())
        await svc.run(saved["ref"], "assistant", "hello", "idle", context())
        result = await settled(svc, "idle", context())
        assert result["run"]["state"] == "completed"
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 1
        assert svc.capacity()["applications"] == 0
        restored = await svc.status("idle", context())
        assert restored["result"] == result["result"]
        assert svc.capacity()["applications"] == 0
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_idle_probe_preserves_queued_runs_after_reopen(tmp_path):
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore

    store = FilesystemSessionStore(tmp_path)
    try:
        created = await store.create_run(StartRun(agent_id="assistant", input=(), resolved_spec_hash="test", idempotency_key="first"), context())
        assert await store.has_nonterminal_runs()
        run = await store.get_run(created.handle.run_id)
        # A terminal row can be reclaimed; a new queued row cannot.
        await store.commit_run(run_id=run.run_id, expected_revision=run.revision,
            expected_states={RunState.QUEUED}, new_state=RunState.CANCELLED,
            drafts=(), context=context(), idempotency_key="cancel-first")
        assert not await store.has_nonterminal_runs()
    finally:
        await store.close()
    reopened = FilesystemSessionStore(tmp_path)
    try:
        assert not await reopened.has_nonterminal_runs()
        await reopened.create_run(StartRun(agent_id="assistant", input=(), resolved_spec_hash="test", idempotency_key="second"), context())
    finally:
        await reopened.close()
    again = FilesystemSessionStore(tmp_path)
    try:
        assert await again.has_nonterminal_runs()
    finally:
        await again.close()


@pytest.mark.asyncio
async def test_flow_build_only_initializes_reachable_agents(tmp_path, monkeypatch):
    data = bundle().model_dump(mode="json")
    template = data["manifest"]["agents"]["assistant"].copy()
    for name in ("worker", "unused"):
        data["manifest"]["agents"][name] = template.copy()
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {"type": "flow", "flow": "main"}
    data["manifest"]["flows"] = {
        "main": {"version": "1", "start": "nested", "nodes": [
            {"id": "nested", "type": "subflow", "flow": "child"},
            {"id": "end", "type": "end"},
            {"id": "unused", "type": "agent", "agent": "unused"},
        ], "edges": [{"from": "nested", "to": "end"}]},
        "child": {"version": "1", "start": "parallel", "nodes": [
            {"id": "parallel", "type": "parallel", "config": {"branches": ["worker"]}},
            {"id": "worker", "type": "agent", "agent": "worker"},
            {"id": "end", "type": "end"},
        ], "edges": [{"from": "parallel", "to": "end"}]},
    }
    calls = []

    async def create_model(self, host, process, handles, resolved, agent_id, *args, **kwargs):
        calls.append(agent_id)
        return model()

    monkeypatch.setattr(SAgentBuilder, "_create_model", create_model)
    app = await SAgentBuilder().with_defaults(session_root=tmp_path).build(
        AgentPackageBundle.model_validate(data).resolved_manifest())
    try:
        assert calls == ["assistant", "worker"]
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_managed_applications_share_host_model_budget(tmp_path):
    from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget

    budget = ModelConcurrencyBudget(1)
    release = asyncio.Event()
    started = asyncio.Event()
    calls = []

    class Model:
        async def capabilities(self, binding):
            return await model().capabilities(binding)

        async def stream(self, request):
            calls.append(request.run_id)
            started.set()
            await release.wait()
            async for event in model().stream(request):
                yield event

    async def allow(*args):
        pass

    def factory(package, root, ctx):
        return SAgentBuilder().with_defaults(session_root=root).with_model_provider(Model())

    svc = AgentManagementService(tmp_path, builder_factory=factory, authorize=allow, model_budget=budget)
    try:
        for index in range(2):
            saved = await svc.save(bundle(f"{index + 1}.0.0"), context())
            await svc.run(saved["ref"], "assistant", "hello", f"bounded-{index}", context())
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(200):
            if budget.waiting:
                break
            await asyncio.sleep(.01)
        assert budget.active == 1 and budget.waiting == 1
        assert len(calls) == 1
        release.set()
        for index in range(2):
            assert (await settled(svc, f"bounded-{index}", context()))["run"]["state"] == "completed"
        assert len(calls) == 2
        assert svc.capacity()["model_calls"]["active"] == 0
    finally:
        release.set()
        await svc.close()


@pytest.mark.asyncio
async def test_idle_cleanup_failure_closes_admission_and_can_retry(tmp_path):
    svc, _ = service(tmp_path)
    try:
        app = await svc._application(bundle(), "assistant", context())

        class FailOnce:
            attempts = 0

            async def close(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("idle cleanup failed")

        resource = FailOnce()
        await app.adopt_resource(resource)
        with pytest.raises(RuntimeError, match="failed to close"):
            await svc.release_idle(min_idle_seconds=0)
        assert svc.capacity()["draining"]
        assert svc.capacity()["applications"] == 1
        with pytest.raises(RuntimeError, match="closing"):
            await svc.validate(bundle(), context())
        await svc.close()
        assert resource.attempts == 2
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_idle_probe_fails_closed_on_corrupt_persisted_state(tmp_path):
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore

    store = FilesystemSessionStore(tmp_path)
    await store.create_run(StartRun(agent_id="assistant", input=(), resolved_spec_hash="test", idempotency_key="one"), context())
    await store.close()
    snapshot = next(tmp_path.rglob("state.json"))
    snapshot.write_text("broken", encoding="utf-8")
    restored = FilesystemSessionStore(tmp_path)
    try:
        with pytest.raises(Exception):
            await restored.has_nonterminal_runs()
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_strict_readiness_rechecks_saved_versions_when_resource_disappears(tmp_path):
    from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
    from sagents.v2.tool.contracts import ToolDefinition

    available = [ToolDefinition(name="known", description="Known", input_schema={"type": "object"})]
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["tools"] = ["known"]
    package = AgentPackageBundle.model_validate(data)

    async def allow(*args):
        pass

    def factory(package, root, ctx):
        return (SAgentBuilder().with_defaults(session_root=root).with_model_provider(model())
            .with_tool_provider(InMemoryToolCatalog(tuple(available)), InMemoryToolExecutor({}, {})))

    svc = AgentManagementService(tmp_path, builder_factory=factory, authorize=allow, require_readiness=True)
    try:
        saved = await svc.save(package, context())
        assert saved["readiness"]["ready"]
        await svc.run(saved["ref"], "assistant", "hello", "before", context())
        await settled(svc, "before", context())
        available.clear()
        with pytest.raises(ValueError, match="resources are not ready"):
            await svc.save(package, context())
        with pytest.raises(ValueError, match="resources are not ready"):
            await svc.run(saved["ref"], "assistant", "hello", "after", context())
    finally:
        await svc.close()


async def finish_without_status(svc, handle):
    app = next(app for app in svc._applications.values()
               if handle["run_id"] in app.entrypoint().runtime.session_store._runs)
    async with asyncio.timeout(5):
        while (await app.entrypoint().runtime.get_run(handle["run_id"])).state.value != "completed":
            await asyncio.sleep(.01)
    return app


@pytest.mark.asyncio
async def test_capacity_pressure_archives_and_reclaims_then_reads_offline(tmp_path):
    svc, models = service(tmp_path)
    svc.max_applications = 1
    svc.auto_release_idle_seconds = 0
    try:
        first = await svc.save(bundle(), context())
        second = await svc.save(bundle("2.0.0"), context())
        handle = await svc.run(first["ref"], "assistant", "first", "first", context())
        await finish_without_status(svc, handle)
        await svc.run(second["ref"], "assistant", "second", "second", context())
        assert svc.capacity()["applications"] == 1
        count = len(models)
        result = await svc.status("first", context())
        assert result["terminal"] and result["run"]["run_id"] == handle["run_id"]
        assert len(models) == count
    finally:
        await svc.close()

    def unavailable(*args):
        raise RuntimeError("model plugin removed")

    async def allow(*args):
        pass

    offline = AgentManagementService(tmp_path, builder_factory=unavailable, authorize=allow)
    try:
        assert (await offline.status("first", context())) == result
        assert offline.capacity()["applications"] == 0
        with pytest.raises(ValueError, match="caller scope"):
            await offline.status("first", context("bob"))

        async def deny(*args):
            raise PermissionError("read grant revoked")

        offline.authorize = deny
        with pytest.raises(PermissionError, match="revoked"):
            await offline.status("first", context())
    finally:
        await offline.close()


@pytest.mark.asyncio
async def test_eviction_cannot_close_application_while_status_holds_lease(tmp_path, monkeypatch):
    svc, _ = service(tmp_path)
    svc.max_applications = 1
    svc.auto_release_idle_seconds = 0
    entered = asyncio.Event()
    release = asyncio.Event()
    reading = None
    try:
        first = await svc.save(bundle(), context())
        second = await svc.save(bundle("2.0.0"), context())
        handle = await svc.run(first["ref"], "assistant", "first", "first", context())
        await finish_without_status(svc, handle)
        original = svc._read_status

        async def blocked(*args):
            entered.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(svc, "_read_status", blocked)
        reading = asyncio.create_task(svc.status("first", context()))
        await entered.wait()
        assert svc.capacity()["leased_applications"] == 1
        assert await svc.release_idle(min_idle_seconds=0) == {"released": 0, "busy": True}
        with pytest.raises(ValueError, match="capacity"):
            await svc.run(second["ref"], "assistant", "second", "second", context())
        release.set()
        assert (await reading)["terminal"]
        assert svc.capacity()["leased_applications"] == 0
        await svc.run(second["ref"], "assistant", "second", "second", context())
    finally:
        release.set()
        if reading is not None:
            await reading
        await svc.close()


@pytest.mark.asyncio
async def test_cancelled_status_releases_lease_for_eviction(tmp_path, monkeypatch):
    svc, _ = service(tmp_path)
    entered = asyncio.Event()
    reading = None
    try:
        saved = await svc.save(bundle(), context())
        handle = await svc.run(saved["ref"], "assistant", "first", "first", context())
        await finish_without_status(svc, handle)
        original = svc._read_status

        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(svc, "_read_status", blocked)
        reading = asyncio.create_task(svc.status("first", context()))
        await entered.wait()
        reading.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reading
        assert svc.capacity()["leased_applications"] == 0
        monkeypatch.setattr(svc, "_read_status", original)
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("idle_age", [None, 300])
async def test_capacity_does_not_evict_when_disabled_or_recent(tmp_path, idle_age):
    svc, _ = service(tmp_path)
    svc.max_applications = 1
    svc.auto_release_idle_seconds = idle_age
    try:
        first = await svc.save(bundle(), context())
        second = await svc.save(bundle("2.0.0"), context())
        handle = await svc.run(first["ref"], "assistant", "first", "first", context())
        await finish_without_status(svc, handle)
        with pytest.raises(ValueError, match="capacity"):
            await svc.run(second["ref"], "assistant", "second", "second", context())
        assert svc.capacity()["applications"] == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_reclamation_preserves_ephemeral_session_continuation(tmp_path):
    from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore

    async def allow(*args):
        pass

    def factory(package, root, ctx):
        return (SAgentBuilder().with_defaults(session_root=root)
                .with_session_store(EphemeralSessionStore()).with_model_provider(model()))

    svc = AgentManagementService(tmp_path, builder_factory=factory, authorize=allow,
                                 max_applications=1, auto_release_idle_seconds=0)
    try:
        saved = await svc.save(bundle(), context())
        first = await svc.run(saved["ref"], "assistant", "hello", "first", context())
        await settled(svc, "first", context())
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 0
        second = await svc.run(saved["ref"], "assistant", "continue", "second", context(), session_id=first["session_id"])
        assert second["session_id"] == first["session_id"]
        assert (await settled(svc, "second", context()))["terminal"]
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_shutdown_archives_unobserved_completed_run_and_releases_on_archive_failure(tmp_path, monkeypatch):
    svc, _ = service(tmp_path)
    saved = await svc.save(bundle(), context())
    handle = await svc.run(saved["ref"], "assistant", "hello", "first", context())
    await finish_without_status(svc, handle)
    await svc.close()
    reopened, models = service(tmp_path)
    try:
        assert (await reopened.status("first", context()))["terminal"]
        assert models == []
        other = await reopened.run(saved["ref"], "assistant", "again", "second", context())
        app = await finish_without_status(reopened, other)
        original = reopened.store.terminal_status

        async def fail_archive(owner, operation, *, value=None):
            if value is not None:
                raise OSError("archive disk full")
            return await original(owner, operation)

        monkeypatch.setattr(reopened.store, "terminal_status", fail_archive)
        with pytest.raises(BaseExceptionGroup):
            await reopened.close()
        assert app._closed
        assert reopened.capacity()["applications"] == 0
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_archive_pagination_does_not_skip_unobserved_operations(tmp_path):
    svc, _ = service(tmp_path)
    try:
        saved = await svc.save(bundle(), context())
        handle = await svc.run(saved["ref"], "assistant", "hello", "first", context())
        await finish_without_status(svc, handle)
        from sagents.v2.agent.management.service import owner_key
        owner = owner_key(context())
        # Multiple inventory rows make the paging boundary observable without
        # spending the test on 101 separate model executions.
        for index in range(101):
            await svc.store.invocation(owner, f"copy-{index:03}", saved["ref"], "assistant", "same-run", handle=handle)
        assert (await svc.release_idle(min_idle_seconds=0))["released"] == 1
        assert (await svc.store.terminal_status(owner, "copy-100"))["terminal"]
        assert await svc.store.unarchived_invocations(owner, saved["ref"], "assistant") == []
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_cancelled_shutdown_preserves_owned_build_for_cleanup_retry(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = []

    class App:
        async def close(self):
            closed.append(self)

    class Builder:
        async def build(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return App()

    async def allow(*args):
        pass

    svc = AgentManagementService(tmp_path, builder_factory=lambda *args: Builder(), authorize=allow)
    building = asyncio.create_task(svc._application(bundle(), "assistant", context()))
    try:
        await entered.wait()
        closing = asyncio.create_task(svc.close())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        release.set()
        app = await building
        await svc.close()
        assert closed == [app]
        assert svc.capacity()["building"] == 0
        assert svc.capacity()["applications"] == 0
    finally:
        release.set()
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_managed_run_preserves_queue_failure_reason(tmp_path, timeout):
    from sagents.v2.model import ModelConcurrencyBudget

    svc, models = service(tmp_path)
    svc.model_budget = ModelConcurrencyBudget(1, max_waiting=1 if timeout else 0,
                                             wait_timeout_seconds=.01)
    try:
        saved = await svc.save(bundle(), context())
        async with svc.model_budget.lease():
            await svc.run(saved["ref"], "assistant", "hello", "overloaded", context())
            result = await settled(svc, "overloaded", context())
        assert result["run"]["state"] == "suspended"
        error = result["interaction"]["payload"]["error"]
        assert error["code"] == ("model.queue_timeout" if timeout else "model.queue_full")
        assert error["retryable"] and error["safe_to_resume"]
        assert all(not provider.requests for provider in models)
        await svc.control("overloaded", "reply", context(), decision="retry",
            interaction_id=result["interaction"]["interaction_id"])
        assert (await settled(svc, "overloaded", context()))["run"]["state"] == "completed"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_unarchived_filesystem_history_reads_without_model_or_source_writes(tmp_path, monkeypatch):
    svc, _ = service(tmp_path)
    saved = await svc.save(bundle(), context())
    handle = await svc.run(saved["ref"], "assistant", "hello", "unobserved", context())
    await finish_without_status(svc, handle)
    async def skip_archive(*args):
        pass
    monkeypatch.setattr(svc, "_archive_application", skip_archive)
    await svc.close()
    root = tmp_path / "runs"
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    async def allow(*args):
        pass
    def unavailable(*args):
        raise AssertionError("history must not initialize a model")
    restored = AgentManagementService(tmp_path, builder_factory=unavailable, authorize=allow)
    try:
        value = await restored.status("unobserved", context())
        assert value["terminal"]
        assert value["run"]["run_id"] == handle["run_id"]
        assert restored.capacity()["applications"] == 0
        after = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
        assert after == before
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_shared_jobs_survive_one_application_close_and_bound_admission(tmp_path):
    from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
    from sagents.v2.contracts.jobs import JobSpec, JobCompletion
    from sagents.v2.contracts.errors import SageV2Error
    release = asyncio.Event()
    started = asyncio.Event()
    async def runner(spec, emit, cancelled):
        started.set()
        await release.wait()
        return JobCompletion(exit_code=0)
    jobs = InMemoryJobRuntime({"test": runner}, max_concurrent_jobs=1, max_admitted_jobs=1)
    apps = []
    try:
        for index in range(2):
            apps.append(await SAgentBuilder().with_defaults(session_root=tmp_path / str(index))
                        .with_model_provider(model()).with_job_runtime(jobs).build(bundle().resolved_manifest()))
        assert apps[0].service("execution.job-runtime") is apps[1].service("execution.job-runtime") is jobs
        first = await jobs.submit(JobSpec(kind="test", owner_run_id="run-a", idempotency_key="a"))
        await started.wait()
        with pytest.raises(SageV2Error):
            await apps[1].service("execution.job-runtime").submit(JobSpec(kind="test", owner_run_id="run-b", idempotency_key="b"))
        await apps[0].close()
        assert not jobs._closed
        release.set()
        assert first.job_id
    finally:
        release.set()
        for app in apps:
            await app.close()
        await jobs.close()


def source_plugin_bundle():
    data = bundle().model_dump(mode="json")
    data["manifest"]["agents"]["assistant"]["entrypoint"] = {"type": "flow", "flow": "main"}
    data["manifest"]["plugins"] = [{"id": "test.generated", "version": "1.0.0"}]
    data["manifest"]["runtime"]["capabilities"] = {"flow.node": {"plugin": "test.generated", "name": "calculate"}}
    data["manifest"]["flows"] = {"main": {"version": "1", "start": "calculate", "nodes": [
        {"id": "calculate", "type": "tool", "tool": "calculate"}, {"id": "end", "type": "end"}],
        "edges": [{"from": "calculate", "to": "end"}]}}
    data["files"]["extensions/test.generated.py"] = '''
from sagents.v2.flow import FlowNodeResult
from sagents.v2.runtime.extensions import ExtensionRegistration, ExtensionDescriptor, CapabilityOffer, ExtensionScope
class Node:
    async def run(self, context):
        return FlowNodeResult(output={"answer": 42})
registration = ExtensionRegistration(
    descriptor=ExtensionDescriptor(plugin_id="test.generated", version="1.0.0", name="Generated",
        provides=(CapabilityOffer(capability="flow.node", api_version="2", name="calculate"),),
        supported_scopes=frozenset({ExtensionScope.AGENT})),
    factory=lambda context, dependencies: Node(),
    start=lambda node, context, dependencies: {"flow.node:calculate": node})
'''
    return AgentPackageBundle.model_validate(data)


@pytest.mark.asyncio
async def test_source_extension_build_register_run_and_module_cleanup(tmp_path):
    import sys
    baseline = {name for name in sys.modules if name.startswith("_sage_extension_")}
    calls = []
    async def allow(action, package, ctx):
        calls.append(action)
    svc, _ = service(tmp_path, authorize=allow)
    svc.allow_source_plugins = True
    try:
        saved = await svc.save(source_plugin_bundle(), context())
        assert "load_source_plugin" in calls
        await svc.run(saved["ref"], "assistant", "calculate", "source", context())
        result = await settled(svc, "source", context())
        assert result["flow_results"]["calculate"]["answer"] == 42
        assert {name for name in sys.modules if name.startswith("_sage_extension_")} != baseline
    finally:
        await svc.close()
    assert {name for name in sys.modules if name.startswith("_sage_extension_")} == baseline


@pytest.mark.asyncio
async def test_source_extensions_require_optin_and_explicit_authorization(tmp_path):
    svc, _ = service(tmp_path)
    try:
        with pytest.raises(ValueError, match="opt-in"):
            await svc.save(source_plugin_bundle(), context())
        svc.allow_source_plugins = True
        async def deny_load(action, package, ctx):
            if action == "load_source_plugin":
                raise PermissionError("source import denied")
        svc.authorize = deny_load
        with pytest.raises(PermissionError, match="denied"):
            await svc.save(source_plugin_bundle(), context())
        assert not await svc.list(context())
    finally:
        await svc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['syntax', 'export', 'identity', 'version', 'built_in'])
async def test_invalid_source_extensions_leave_no_modules_or_packages(tmp_path, invalid):
    import sys
    from sagents.v2.contracts.errors import SageV2Error
    data = source_plugin_bundle().model_dump(mode='json')
    path = 'extensions/test.generated.py'
    source = data['files'][path]
    if invalid == 'syntax':
        source = 'def broken('
    elif invalid == 'export':
        source = 'registration = None'
    elif invalid == 'identity':
        source = source.replace('plugin_id="test.generated"', 'plugin_id="other.plugin"')
    elif invalid == 'version':
        source = source.replace('version="1.0.0"', 'version="2.0.0"')
    else:
        source = source.replace('name="Generated",', 'name="Generated", built_in=True,')
    data['files'][path] = source
    baseline = {name for name in sys.modules if name.startswith('_sage_extension_')}
    svc, _ = service(tmp_path)
    svc.allow_source_plugins = True
    try:
        with pytest.raises((ValueError, SyntaxError, SageV2Error)):
            await svc.save(AgentPackageBundle.model_validate(data), context())
        assert not await svc.list(context())
        assert {name for name in sys.modules if name.startswith('_sage_extension_')} == baseline
    finally:
        await svc.close()
