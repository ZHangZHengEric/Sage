import asyncio

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins import ScriptedModelProvider


def package():
    return BuiltinPackageFactory.create(
        "assistant", package_id="test.loaded", model="test-model"
    )


@pytest.mark.asyncio
async def test_load_reuse_update_and_close(tmp_path):
    manifest = package()
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(ScriptedModelProvider(()))
        .build(runtime=manifest.runtime)
    )
    first, again = await asyncio.gather(
        app.load_agent(manifest), app.load_agent(manifest.model_dump())
    )
    assert first is again
    changed = manifest.model_copy(
        update={"metadata": manifest.metadata.model_copy(update={"version": "2"})}
    )
    with pytest.raises(ValueError, match="update_agent"):
        await app.load_agent(changed)
    updated = await app.update_agent(agent=first, package=changed)
    assert updated.id == first.id
    assert updated.version != first.version
    assert app.loaded_agents == (updated,)
    assert app._loaded_agents.implementation(
        first
    ) is not app._loaded_agents.implementation(updated)
    await app.close()
    with pytest.raises(RuntimeError, match="closed"):
        await app.load_agent(manifest)


@pytest.mark.asyncio
async def test_default_runtime_matches_desktop(tmp_path):
    from app.v2.desktop.backend.package import desktop_v2_manifest

    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(ScriptedModelProvider(()))
        .build()
    )
    assert (
        app._loaded_agents.runtime == desktop_v2_manifest(session_root=tmp_path).runtime
    )
    try:
        await app.load_agent(package())
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_revision_identity_survives_loading_order(tmp_path):
    original = package()
    changed = original.model_copy(
        update={"metadata": original.metadata.model_copy(update={"version": "2"})}
    )

    def builder():
        return (
            SAgentBuilder()
            .with_defaults(session_root=tmp_path)
            .with_model_provider(ScriptedModelProvider(()))
        )

    app = await builder().build(runtime=original.runtime)
    try:
        first = await app.load_agent(original)
        second = await app.update_agent(agent=first, package=changed)
        expected = second.composition_hash
        assert first._application.service(
            "execution.dispatcher"
        ) is second._application.service("execution.dispatcher")
    finally:
        await app.close()
    reopened = await builder().build(runtime=original.runtime)
    try:
        second = await reopened.load_agent(changed)
        assert second.composition_hash == expected
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_multiple_packages_with_same_internal_agent_name(tmp_path):
    first = package()
    other = first.model_copy(
        update={"metadata": first.metadata.model_copy(update={"id": "test.other"})}
    )
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(ScriptedModelProvider(()))
        .build(runtime=first.runtime)
    )
    try:
        one = await app.load_agent(first)
        two = await app.load_agent(other)
        assert one.id != two.id
        assert len(app.loaded_agents) == 2
    finally:
        await app.close()


def model():
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
    )

    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id=f"reply-{i}", text="OK", finish_reason="stop"
                        ),
                    ),
                )
            )
            for i in range(4)
        )
    )


def command(agent, key):
    from sagents.v2 import StartRun
    from sagents.v2.contracts.commands import InputItem
    from sagents.v2.contracts.items import TextBlock

    return StartRun(
        agent_id=agent.id,
        resolved_spec_hash=agent.composition_hash,
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        idempotency_key=key,
    )


def context():
    from sagents.v2 import ActorRef, RequestContext

    return RequestContext(
        actor=ActorRef(principal_id="test-user", principal_type="user")
    )


@pytest.mark.asyncio
async def test_reusable_agent_runs_and_old_revision_survives_update(tmp_path):
    original = package()
    provider = model()
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(provider)
        .build(runtime=original.runtime)
    )
    try:
        first = await app.load_agent(original)
        changed = original.model_copy(deep=True)
        name = next(iter(changed.agents))
        changed.agents[name] = changed.agents[name].model_copy(
            update={
                "instructions": changed.agents[name].instructions.model_copy(
                    update={"inline": "UPDATED INSTRUCTIONS"}
                )
            }
        )
        second = await app.update_agent(agent=first, package=changed)
        for index, agent in enumerate((first, second, first)):
            stream = await app.entrypoint().run_stream(
                command(agent, f"run-{index}"), context(), agent=agent
            )
            assert (await stream.wait()).state.value == "completed"
            await stream.detach()
        assert "UPDATED INSTRUCTIONS" not in str(provider.requests[0])
        assert "UPDATED INSTRUCTIONS" in str(provider.requests[1])
        assert "UPDATED INSTRUCTIONS" not in str(provider.requests[2])
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_restart_restores_pending_original_revision_after_update(tmp_path):
    original = package()
    changed = original.model_copy(
        update={"metadata": original.metadata.model_copy(update={"version": "2"})}
    )
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(model())
        .build(runtime=original.runtime)
    )
    first = await app.load_agent(original)
    await app.update_agent(agent=first, package=changed)
    pending = await app.runtime.start_run(command(first, "recover-original"), context())
    await app.close()
    reopened = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(model())
        .build(runtime=original.runtime)
    )
    try:
        latest = await reopened.load_agent(changed)
        assert reopened.loaded_agents == (latest,)
        async with asyncio.timeout(5):
            while (await reopened.runtime.get_run(pending.run_id)).state.value not in {
                "completed",
                "failed",
            }:
                await asyncio.sleep(0.01)
        run = await reopened.runtime.get_run(pending.run_id)
        assert run.state.value == "completed"
        assert run.resolved_spec_hash == first.composition_hash
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_package_inputs_and_atomic_invalid_update(tmp_path):
    import json
    import yaml

    manifest = package()
    folder = tmp_path / "package"
    folder.mkdir()
    data = manifest.model_dump(mode="json")
    (folder / "sage.yaml").write_text(yaml.safe_dump(data))
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path / "state")
        .with_model_provider(model())
        .build(runtime=manifest.runtime)
    )
    try:
        agent = await app.load_agent(folder)
        assert await app.load_agent(folder / "sage.yaml") is agent
        assert await app.load_agent(config_text=json.dumps(data)) is agent
        assert await app.load_agent(data) is agent
        for bad in (
            {**data, "agents": {}},
            {
                **data,
                "agents": {
                    **data["agents"],
                    "other": next(iter(data["agents"].values())),
                },
            },
        ):
            with pytest.raises(ValueError, match="exactly one"):
                await app.update_agent(agent=agent, package=bad)
            assert app.loaded_agents == (agent,)
        with pytest.raises(ValueError, match="exactly one"):
            await app.load_agent(data, config_text="{}")
    finally:
        await app.close()


def test_runtime_inputs_and_resource_base_path(tmp_path):
    import json
    from sagents.v2.composition.inputs import package_input, runtime_input

    runtime = package().runtime
    text = runtime.model_dump_json()
    path = tmp_path / "runtime.yaml"
    path.write_text(text)
    assert runtime_input(path) == runtime_input(config_text=text) == runtime
    with pytest.raises(ValueError, match="mutually exclusive"):
        runtime_input(path, config_text=text)
    with pytest.raises(ValueError, match="mapping"):
        runtime_input(config_text="[]")
    raw = package().model_dump(mode="json")
    agent = next(iter(raw["agents"].values()))
    agent["instructions"] = {"path": "instructions.md"}
    (tmp_path / "instructions.md").write_text("read from package")
    with pytest.raises(ValueError, match="base_path"):
        package_input(raw)
    resolved = package_input(config_text=json.dumps(raw), base_path=tmp_path)
    assert (
        next(iter(resolved.agents.values())).instructions.inline == "read from package"
    )
    agent["instructions"] = {"path": "../outside.md"}
    with pytest.raises(ValueError, match="inside base_path"):
        package_input(raw, base_path=tmp_path)


@pytest.mark.asyncio
async def test_app_owns_resources_without_loading_and_snapshots_registration(tmp_path):
    closed = []

    class Resource:
        async def close(self):
            closed.append(True)

    builder = (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_owned_resources(Resource())
    )
    app = await builder.build()
    assert app._loaded_agents.builder.extensions is not builder.extensions
    await app.close()
    await app.close()
    assert closed == [True]


@pytest.mark.asyncio
async def test_update_while_old_run_is_in_flight(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class GatedModel(ScriptedModelProvider):
        async def _stream(self, request):
            entered.set()
            await release.wait()
            async for event in super()._stream(request):
                yield event

    provider = GatedModel(model()._steps)
    original = package()
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(provider)
        .build(runtime=original.runtime)
    )
    try:
        old = await app.load_agent(original)
        stream = await app.entrypoint().run_stream(
            command(old, "in-flight"), context(), agent=old
        )
        await asyncio.wait_for(entered.wait(), 2)
        changed = original.model_copy(
            update={"metadata": original.metadata.model_copy(update={"version": "2"})}
        )
        latest = await app.update_agent(agent=old, package=changed)
        assert latest is not old
        release.set()
        result = await stream.wait()
        assert result.state.value == "completed"
        assert result.resolved_spec_hash == old.composition_hash
        assert await app.agent_for_run(result.run_id, context()) is old
        with pytest.raises(ValueError, match="admitted Agent revision"):
            await app.entrypoint().continue_run(result.run_id, context(), agent=latest)
        with pytest.raises(ValueError, match="Agent was updated"):
            await app.update_agent(agent=old, package=changed)
        await stream.detach()
    finally:
        release.set()
        await app.close()


@pytest.mark.asyncio
async def test_entrypoint_requires_owned_agent_and_matching_command(tmp_path):
    manifest = package()
    app = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path / "one")
        .with_model_provider(model())
        .build(runtime=manifest.runtime)
    )
    other = (
        await SAgentBuilder()
        .with_defaults(session_root=tmp_path / "two")
        .with_model_provider(model())
        .build(runtime=manifest.runtime)
    )
    try:
        agent = await app.load_agent(manifest)
        foreign = await other.load_agent(manifest)
        with pytest.raises(TypeError):
            await app.entrypoint().run_stream(command(agent, "missing"), context())
        with pytest.raises(ValueError, match="different application"):
            await app.entrypoint().run_stream(
                command(foreign, "foreign"), context(), agent=foreign
            )
        bad = command(agent, "wrong").model_copy(update={"resolved_spec_hash": "wrong"})
        with pytest.raises(ValueError, match="identity"):
            await app.entrypoint().run_stream(bad, context(), agent=agent)
    finally:
        await app.close()
        await other.close()


@pytest.mark.asyncio
async def test_plugin_validation_failure_keeps_loaded_revision(tmp_path):
    from examples.sagents_v2_host.plugins import estimator_registration
    from sagents.v2.package.manifest.root import PluginDeclaration
    from sagents.v2.package.manifest.runtime import CapabilitySelection

    manifest = package()
    runtime = manifest.runtime.model_copy(
        update={
            "capabilities": {
                **manifest.runtime.capabilities,
                "context.token-estimator": CapabilitySelection(
                    plugin="example.context.byte-estimator", scope="agent"
                ),
            }
        }
    )
    app = (
        await SAgentBuilder()
        .register(estimator_registration())
        .with_defaults(session_root=tmp_path)
        .with_model_provider(model())
        .build(runtime=runtime)
    )
    try:
        original = await app.load_agent(manifest)
        invalid = manifest.model_copy(
            update={
                "plugins": (
                    PluginDeclaration(
                        id="example.context.byte-estimator",
                        config={"bytes_per_token": -1},
                    ),
                )
            }
        )
        with pytest.raises(Exception, match="invalid configuration"):
            await app.update_agent(agent=original, package=invalid)
        assert app.loaded_agents == (original,)
        stream = await app.entrypoint().run_stream(
            command(original, "after-failed-update"), context(), agent=original
        )
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_child_revision_is_pinned_across_update_and_restart(tmp_path):
    child_package = package()
    parent_package = package().model_copy(deep=True)
    parent_package = parent_package.model_copy(
        update={
            "metadata": parent_package.metadata.model_copy(update={"id": "test.parent"})
        }
    )
    name = next(iter(parent_package.agents))
    parent_package.agents[name] = parent_package.agents[name].model_copy(
        update={"subagents": ("worker",)}
    )

    async def open_app():
        return (
            await SAgentBuilder()
            .with_defaults(session_root=tmp_path)
            .with_model_provider(model())
            .build(runtime=parent_package.runtime)
        )

    app = await open_app()
    try:
        child = await app.load_agent(child_package)
        parent = await app.load_agent(parent_package, subagents={"worker": child})
        stream = await app.entrypoint().run_stream(
            command(parent, "pinned-child"), context(), agent=parent
        )
        assert (await stream.wait()).state.value == "completed"
        run_id = stream.handle.run_id
        await stream.detach()
        changed = child_package.model_copy(deep=True)
        changed.agents[name] = changed.agents[name].model_copy(
            update={
                "instructions": changed.agents[name].instructions.model_copy(
                    update={"inline": "NEW CHILD"}
                )
            }
        )
        new_child = await app.update_agent(agent=child, package=changed)
        assert parent._resolved.agents["worker"].instructions != "NEW CHILD"
        new_parent = await app.update_agent(
            agent=parent, package=parent_package, subagents={"worker": new_child}
        )
        assert new_parent.composition_hash != parent.composition_hash
        assert new_parent._resolved.agents["worker"].instructions == "NEW CHILD"
        old_hash = parent.composition_hash
    finally:
        await app.close()
    app = await open_app()
    try:
        await app.load_agent(changed)
        restored = await app.agent_for_run(run_id, context())
        assert restored.composition_hash == old_hash
        assert restored._resolved.agents["worker"].instructions != "NEW CHILD"
    finally:
        await app.close()


def test_builder_rejects_old_package_argument():
    import inspect

    assert "package" not in inspect.signature(SAgentBuilder.build).parameters
    assert "agent_id" not in inspect.signature(SAgentBuilder.build).parameters


def test_single_agent_bundle_preserves_historical_content_hash():
    import hashlib
    import json
    from sagents.v2.agent.management import AgentPackageBundle

    raw = {"manifest": package().model_dump(mode="json"), "files": {}}
    expected = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bundle = AgentPackageBundle.model_validate(raw)
    assert bundle.content_hash == expected
    assert bundle.model_dump(mode="json") == raw
    raw["manifest"]["agents"]["second"] = raw["manifest"]["agents"]["assistant"]
    with pytest.raises(ValueError, match="exactly one Agent"):
        AgentPackageBundle.model_validate(raw)
