
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.composition.loaded_agents import LoadedAgents
    from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
    from sagents.v2.contracts.principals import PrincipalType
    from sagents.v2.runtime.extensions.contracts import ExtensionScope

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

from sagents.v2.package.manifest.runtime import CapabilitySelection

from tests.sagents.v2.sdk_fixture import build_registered_app, app_configuration
from tests.sagents.v2.model_fixture import TEST_MODELS
import asyncio

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins import ScriptedModelProvider


def package():
    return BuiltinPackageFactory.create(
        "assistant",
        package_id="test.loaded",
    )


@pytest.mark.asyncio
async def test_load_reuse_update_and_close(tmp_path):
    manifest = package()
    app = (
        await build_registered_app(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()), runtime=manifest.runtime)
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
    assert cast('LoadedAgents', app._loaded_agents).implementation(
        first
    ) is not cast('LoadedAgents', app._loaded_agents).implementation(updated)
    await app.close()
    with pytest.raises(RuntimeError, match="closed"):
        await app.load_agent(manifest)


@pytest.mark.asyncio
async def test_default_runtime_matches_desktop(tmp_path):
    from app.v2.desktop.backend.package import desktop_v2_manifest

    app = (
        await build_registered_app(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()), runtime=desktop_v2_manifest(session_root=tmp_path).runtime)
    )
    from sagents.v2.composition.defaults import effective_runtime

    expected = effective_runtime(desktop_v2_manifest(session_root=tmp_path).runtime)
    for capability, selection in expected.capabilities.items():
        assert app.runtime_configuration.capabilities[capability] == selection
    assert cast(CapabilitySelection, app.runtime_configuration.capabilities["model.provider"]).plugin == "test.fixture.model.provider"
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

    async def application():
        return await build_registered_app(tmp_path, models=TEST_MODELS,
            model=ScriptedModelProvider(()), runtime=original.runtime)

    app = await application()
    try:
        first = await app.load_agent(original)
        second = await app.update_agent(agent=first, package=changed)
        expected = second.composition_hash
        assert first._application.service(
            "execution.dispatcher"
        ) is second._application.service("execution.dispatcher")
    finally:
        await app.close()
    reopened = await application()
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
        await build_registered_app(tmp_path, models=TEST_MODELS, model=ScriptedModelProvider(()), runtime=first.runtime)
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
        actor=ActorRef(principal_id="test-user", principal_type=cast('PrincipalType', "user"))
    )


@pytest.mark.asyncio
async def test_reusable_agent_runs_and_old_revision_survives_update(tmp_path):
    original = package()
    provider = model()
    app = (
        await build_registered_app(tmp_path, models=TEST_MODELS, model=provider, runtime=original.runtime)
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
            stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
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
        await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=original.runtime)
    )
    first = await app.load_agent(original)
    await app.update_agent(agent=first, package=changed)
    pending = await app.runtime.start_run(command(first, "recover-original"), context())
    await app.close()
    reopened = (
        await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=original.runtime)
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
async def test_startup_restore_does_not_swallow_cancellation(tmp_path, monkeypatch):
    from sagents.v2.composition.revision_store import AgentRevisionStore

    manifest = package()
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=manifest.runtime)
    agent = await app.load_agent(manifest)
    await app.runtime.start_run(command(agent, "cancel-startup"), context())
    await app.close()

    def cancelled(self, spec_hash):
        raise asyncio.CancelledError()

    monkeypatch.setattr(AgentRevisionStore, "read", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=manifest.runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "corrupt", "incompatible"])
@pytest.mark.parametrize("healthy_pending", [False, True])
async def test_startup_isolates_bad_revision_and_preserves_queued_work(tmp_path, monkeypatch, failure, healthy_pending):
    from datetime import timedelta
    from sagents.v2.contracts.common import utc_now
    from sagents.v2.runtime.execution.scheduler import LeaseReleaseReason
    from sagents.v2.package.manifest.runtime import CapabilitySelection

    original = package()
    original = original.model_copy(update={"runtime": original.runtime.model_copy(update={
        "capabilities": {**original.runtime.capabilities, "execution.scheduler": CapabilitySelection(
            plugin="sage.scheduler.filesystem", config={"root": str(tmp_path / "scheduler")},
        )},
    })})
    changed = original.model_copy(
        update={"metadata": original.metadata.model_copy(update={"version": "2"})}
    )
    app = await build_registered_app(
        tmp_path, models=TEST_MODELS, model=model(), runtime=original.runtime,
    )
    bad = await app.load_agent(original)
    good = await app.update_agent(agent=bad, package=changed)
    pending = [
        await app.runtime.start_run(command(bad, f"bad-{i}"), context())
        for i in range(2)
    ]
    healthy = await app.runtime.start_run(command(good, "healthy"), context()) if healthy_pending else None
    before = [await app.runtime.get_run(run.run_id) for run in pending]
    dispatcher = app.service("execution.dispatcher")
    scheduler_type = type(dispatcher.scheduler)
    # Reproduce a durable queue entry left by a previous worker process.
    work = dispatcher._work_item(before[0], context(), resume=False).model_copy(
        update={"available_at": utc_now() + timedelta(hours=1)}
    )
    await dispatcher.scheduler.submit(work)
    archive = cast('LoadedAgents', app._loaded_agents).store
    path = archive._path(bad.composition_hash)
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_text("invalid json")
    else:
        archive.save(good._resolved, bad.composition_hash)
    await app.close()

    deferred = asyncio.Event()
    release = scheduler_type.release

    async def observe_release(self, lease, reason, **kwargs):
        await release(self, lease, reason, **kwargs)
        if lease.work.run_id == pending[0].run_id and reason == LeaseReleaseReason.DEFERRED:
            deferred.set()

    monkeypatch.setattr(scheduler_type, "release", observe_release)
    reopened = await build_registered_app(
        tmp_path, models=TEST_MODELS, model=model(), runtime=original.runtime,
    )
    try:
        assert {issue.run_id for issue in reopened.recovery_issues} == {r.run_id for r in pending}
        await reopened.service("execution.scheduler").reschedule_pending(work.work_id, utc_now())
        await asyncio.wait_for(deferred.wait(), 5)
        if healthy is not None:
            async with asyncio.timeout(5):
                while (await reopened.runtime.get_run(healthy.run_id)).state.value != "completed":
                    await asyncio.sleep(0.01)
        assert [await reopened.runtime.get_run(run.run_id) for run in pending] == before
        latest = await reopened.load_agent(changed)
        assert {issue.run_id for issue in reopened.recovery_issues} == {r.run_id for r in pending}
        stream = await cast(ApplicationEntrypoint, reopened.entrypoint()).run_stream(command(latest, "new-chat"), context(), agent=latest)
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
        # A repaired archive can be restored on the next normal load pass.
        archive.save(bad._resolved, bad.composition_hash)
        await reopened.load_agent(changed)
        assert reopened.recovery_issues == ()
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
        await build_registered_app(tmp_path / 'state', models=TEST_MODELS, model=model(), runtime=manifest.runtime)
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
        getattr(next(iter(resolved.agents.values())).instructions, 'inline') == "read from package"
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

    builder, runtime = app_configuration(tmp_path, resources=(Resource(),))
    app = await builder.build(runtime=runtime, models=TEST_MODELS)
    assert cast('LoadedAgents', app._loaded_agents).builder._registry is not builder._registry
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
        await build_registered_app(tmp_path, models=TEST_MODELS, model=provider, runtime=original.runtime)
    )
    try:
        old = await app.load_agent(original)
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
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
            await cast(ApplicationEntrypoint, app.entrypoint()).continue_run(result.run_id, context(), agent=latest)
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
        await build_registered_app(tmp_path / 'one', models=TEST_MODELS, model=model(), runtime=manifest.runtime)
    )
    other = (
        await build_registered_app(tmp_path / 'two', models=TEST_MODELS, model=model(), runtime=manifest.runtime)
    )
    try:
        agent = await app.load_agent(manifest)
        foreign = await other.load_agent(manifest)
        with pytest.raises(TypeError):
            await getattr(app.entrypoint(), "run_stream")(command(agent, "missing"), context())
        with pytest.raises(ValueError, match="different application"):
            await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
                command(foreign, "foreign"), context(), agent=foreign
            )
        bad = command(agent, "wrong").model_copy(update={"resolved_spec_hash": "wrong"})
        with pytest.raises(ValueError, match="identity"):
            await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(bad, context(), agent=agent)
    finally:
        await app.close()
        await other.close()


@pytest.mark.asyncio
async def test_plugin_validation_failure_keeps_loaded_revision(tmp_path):
    from examples.v2.host.plugins import reducer_registration
    from sagents.v2.package.manifest.root import PluginDeclaration
    from sagents.v2.package.manifest.runtime import CapabilitySelection

    manifest = package()
    runtime = manifest.runtime.model_copy(
        update={
            "capabilities": {
                **manifest.runtime.capabilities,
                "context.reducer": CapabilitySelection(
                    plugin="example.context.reference-reducer", scope=cast('ExtensionScope | None', "agent")
                ),
            }
        }
    )
    app = (
        await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=runtime, registrations=(reducer_registration(),))
    )
    try:
        original = await app.load_agent(manifest)
        invalid = manifest.model_copy(
            update={
                "plugins": (
                    PluginDeclaration(
                        id="example.context.reference-reducer",
                        config={"minimum_characters": -1},
                    ),
                )
            }
        )
        with pytest.raises(Exception, match="invalid configuration"):
            await app.update_agent(agent=original, package=invalid)
        assert app.loaded_agents == (original,)
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
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
            await build_registered_app(tmp_path, models=TEST_MODELS, model=model(), runtime=parent_package.runtime)
        )

    app = await open_app()
    try:
        child = await app.load_agent(child_package)
        parent = await app.load_agent(parent_package, subagents={"worker": child})
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
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
    historical = json.loads(json.dumps(raw))
    for agent in historical["manifest"]["agents"].values():
        agent.pop("preload_skills", None)
    expected = hashlib.sha256(
        json.dumps(historical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bundle = AgentPackageBundle.model_validate(raw)
    assert bundle.content_hash == expected
    assert bundle.model_dump(mode="json") == raw
    raw["manifest"]["agents"]["second"] = raw["manifest"]["agents"]["assistant"]
    with pytest.raises(ValueError, match="exactly one Agent"):
        AgentPackageBundle.model_validate(raw)


def test_public_sdk_types_cannot_accept_host_execution_assembly():
    import inspect
    from sagents.v2 import SAgent, SAgentApplication
    with pytest.raises(TypeError, match="SAgentBuilder"):
        SAgent(runtime=object(), driver_factory=lambda run_id: object())
    with pytest.raises(TypeError, match="SAgentBuilder"):
        SAgentApplication(agents={"host": object()}, entrypoint_agent_id="host", services={}, adapters={},
            scope_handles=(), composition_hash="host")
    assert "driver_factory" not in inspect.signature(SAgent).parameters


async def test_atomic_load_configuration_does_not_mutate_application(tmp_path):
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    baseline = app.runtime_configuration
    selected = baseline.model_copy(deep=True)
    selected.capabilities["agent.continuation-policy"] = CapabilitySelection(plugin="sage.agent.continuation.deterministic")
    try:
        loaded = await app.load_agent(package(), runtime=selected, models=TEST_MODELS)
        assert cast(CapabilitySelection, loaded._resolved.runtime.capabilities["agent.continuation-policy"]).plugin == "sage.agent.continuation.deterministic"
        assert app.runtime_configuration == baseline
        selected.capabilities.clear()
        assert loaded._resolved.runtime.capabilities
    finally:
        await app.close()


async def test_distinct_agent_builds_overlap_and_identical_loads_coalesce(tmp_path, monkeypatch):
    from sagents.v2.builder import SAgentBuilder
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    original = SAgentBuilder._build_package
    entered = set()
    both = asyncio.Event()
    builds = []
    async def observed(builder, resolved, **kwargs):
        builds.append(resolved.package_id)
        entered.add(resolved.package_id)
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 3)
        return await original(builder, resolved, **kwargs)
    monkeypatch.setattr(SAgentBuilder, "_build_package", observed)
    other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "other"})})
    try:
        one, same, two = await asyncio.gather(app.load_agent(package()), app.load_agent(package()), app.load_agent(other))
        assert one is same
        assert set(builds) == {one.id, two.id}
        assert len(builds) == 2
    finally:
        await app.close()


async def test_evicted_revision_restores_exact_run_configuration(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    try:
        first = await app.load_agent(package())
        middle_package = package().model_copy(update={"metadata": package().metadata.model_copy(update={"version": "2"})})
        middle = await app.update_agent(agent=first, package=middle_package)
        latest_package = package().model_copy(update={"metadata": package().metadata.model_copy(update={"version": "3"})})
        latest = await app.update_agent(agent=middle, package=latest_package)
        cast('LoadedAgents', app._loaded_agents).max_idle_revisions = 0
        await cast('LoadedAgents', app._loaded_agents).prune_revisions()
        assert middle._application._closed
        assert latest._application._closed
        run = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(command(middle, "restored"), context(), agent=middle)
        assert (await run.wait()).resolved_spec_hash == middle.composition_hash
        assert app.loaded_agents == (latest,)
    finally:
        await app.close()


async def test_revision_cache_keeps_control_and_execution_references(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    blocked = asyncio.Event()
    task = None
    try:
        first = await app.load_agent(package())
        second = await app.update_agent(agent=first, package=package().model_copy(
            update={"metadata": package().metadata.model_copy(update={"version": "2"})}))
        await app.update_agent(agent=second, package=package().model_copy(
            update={"metadata": package().metadata.model_copy(update={"version": "3"})}))
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        async with cast('LoadedAgents', catalog).pin(second):
            await cast('LoadedAgents', catalog).prune_revisions()
            assert not second._application._closed
        agent = cast('LoadedAgents', catalog).implementation(second)
        task = asyncio.create_task(blocked.wait())
        agent._tasks["active"] = task
        await cast('LoadedAgents', catalog).prune_revisions()
        assert not second._application._closed
        blocked.set()
        await task
        agent._tasks.pop("active")
        await cast('LoadedAgents', catalog).prune_revisions()
        assert second._application._closed
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await app.close()


async def test_same_package_builds_distinct_models_in_parallel(tmp_path, monkeypatch):
    from copy import deepcopy
    from sagents.v2.builder import SAgentBuilder
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    original = SAgentBuilder._build_package
    hashes = set()
    both = asyncio.Event()
    async def observed(builder, resolved, **kwargs):
        hashes.add(resolved.manifest_hash)
        if len(hashes) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 3)
        return await original(builder, resolved, **kwargs)
    monkeypatch.setattr(SAgentBuilder, "_build_package", observed)
    first_models, second_models = deepcopy(TEST_MODELS), deepcopy(TEST_MODELS)
    first_models["models"]["primary"]["model"] = "first-model"
    second_models["models"]["primary"]["model"] = "second-model"
    try:
        first, second = await asyncio.gather(
            app.load_agent(package(), models=first_models),
            app.load_agent(package(), models=second_models),
        )
        assert first._resolved.model_routes["primary"]["model"] == "first-model"
        assert second._resolved.model_routes["primary"]["model"] == "second-model"
        assert app.models.models["primary"].model == "test-model"
        assert first.composition_hash != second.composition_hash
    finally:
        await app.close()


async def test_concurrent_first_loads_cannot_publish_different_package_sources(tmp_path, monkeypatch):
    from sagents.v2.builder import SAgentBuilder
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    original = SAgentBuilder._build_package
    entered = 0
    both = asyncio.Event()

    async def observed(builder, resolved, **kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 3)
        return await original(builder, resolved, **kwargs)

    monkeypatch.setattr(SAgentBuilder, "_build_package", observed)
    changed = package().model_copy(update={"metadata": package().metadata.model_copy(update={"version": "2"})})
    try:
        results = await asyncio.gather(app.load_agent(package()), app.load_agent(changed), return_exceptions=True)
        successes = [item for item in results if not isinstance(item, BaseException)]
        failures = [item for item in results if isinstance(item, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], ValueError)
        assert "update_agent" in str(failures[0])
        assert app.loaded_agents == (successes[0],)
    finally:
        await app.close()


async def test_idle_current_packages_release_resources_and_restore_old_handles(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    try:
        root = await app.load_agent(package())
        other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "test.idle-current"})})
        current = await app.load_agent(other)
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        await cast('LoadedAgents', catalog).prune_revisions()
        assert current._application._closed
        assert not root._application._closed
        assert len(cast('LoadedAgents', catalog).revisions) == 1
        assert app.loaded_agents == (root, current)
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(command(current, "idle-current-restored"), context(), agent=current)
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
        assert app.loaded_agents == (root, current)
        changed = other.model_copy(update={"metadata": other.metadata.model_copy(update={"version": "2"})})
        latest = await app.update_agent(agent=current, package=changed)
        assert latest.version != current.version
    finally:
        await app.close()


async def test_interface_projection_pins_revision_until_detach(tmp_path):
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    stream = None
    try:
        await app.load_agent(package())
        other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "test.interface-pin"})})
        agent = await app.load_agent(other)
        stream = await app.run_interface("native", command(agent, "projection-pin"), context(), agent=agent)
        assert (await stream.wait()).state.value == "completed"
        await anext(stream.results)
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        await cast('LoadedAgents', catalog).prune_revisions()
        assert not agent._application._closed
        await stream.detach()
        assert not cast('LoadedAgents', catalog)._users
        await cast('LoadedAgents', catalog).prune_revisions()
        assert agent._application._closed
    finally:
        if stream is not None:
            await stream.detach()
        await app.close()


async def test_synchronous_agent_lookup_restores_an_idle_current_revision(tmp_path):
    from sagents.v2 import SAgent
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    try:
        await app.load_agent(package())
        other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "test.sync-cold"})})
        loaded = await app.load_agent(other)
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        await cast('LoadedAgents', catalog).prune_revisions()
        assert loaded._application._closed
        exported = app.agent(loaded.id)
        assert isinstance(exported, SAgent)
        assert app.agent(loaded.id) is exported
        stream = await exported.run_stream(command(loaded, "sync-cold"), context())
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
        await cast('LoadedAgents', catalog).prune_revisions()
        stream = await exported.run_stream(command(loaded, "sync-cold-again"), context())
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
    finally:
        await app.close()


async def test_exported_agent_synchronous_drive_and_subscription_release_leases(tmp_path):
    from sagents.v2.contracts.run_state import EventCursor
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    try:
        await app.load_agent(package())
        other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "test.sync-drive"})})
        loaded = await app.load_agent(other)
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        await cast('LoadedAgents', catalog).prune_revisions()
        exported = app.agent(loaded.id)
        initial = await exported.run_stream(command(loaded, "sync-drive"), context())
        assert (await initial.wait()).state.value == "completed"
        pending = initial.handle
        await initial.detach()
        await cast('LoadedAgents', catalog).prune_revisions()
        stream = exported.drive_accepted_run(pending, context())
        assert isinstance(stream.execution, asyncio.Task)
        assert (await stream.wait()).state.value == "completed"
        await stream.detach()
        await cast('LoadedAgents', catalog).prune_revisions()
        events = exported.subscribe_events(EventCursor(run_id=pending.run_id, run_sequence=0), context())
        await anext(events)
        assert cast('LoadedAgents', catalog)._users
        await cast('LoadedAgents', catalog).prune_revisions()
        assert (loaded.package_id, loaded.version) in cast('LoadedAgents', catalog).revisions
        await getattr(events, 'aclose')()
        assert not cast('LoadedAgents', catalog)._users
        await cast('LoadedAgents', catalog).prune_revisions()
        assert (loaded.package_id, loaded.version) not in cast('LoadedAgents', catalog).revisions
    finally:
        await app.close()


async def test_cold_exported_runtime_admits_with_its_original_workspace(tmp_path):
    import sys
    from copy import deepcopy
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model())
    streams = []
    try:
        await app.load_agent(package())
        selected = app.runtime_configuration
        workspace = tmp_path / "isolated-workspace"
        selected.capabilities["execution.binding"] = CapabilitySelection(
            plugin="sage.execution.binding.local-workspace",
            config={"workspace": str(workspace), "isolation_python": sys.executable})
        models = deepcopy(TEST_MODELS)
        models["models"]["primary"]["model"] = "frozen-original-model"
        other = package().model_copy(update={"metadata": package().metadata.model_copy(update={"id": "test.runtime-cold"})})
        loaded = await app.load_agent(other, runtime=selected, models=models)
        catalog = app._loaded_agents
        cast('LoadedAgents', catalog).max_idle_revisions = 0
        await cast('LoadedAgents', catalog).prune_revisions()
        assert loaded._application._closed
        exported = app.agent(loaded.id)
        for method, key in (("start_run", "cold-runtime-start"), ("stream", "cold-runtime-stream")):
            result = await getattr(exported.runtime, method)(command(loaded, key), context())
            handle = result.handle if method == "stream" else result
            if method == "stream":
                streams.append(result)
            stored = await exported.runtime.session_store.get_start_command(handle.run_id)
            assert cast('ExecutionConfigurationSnapshot', stored.config.execution_snapshot).workspace_root == str(workspace)
            assert stored.resolved_spec_hash == loaded.composition_hash
            live = cast('LoadedAgents', catalog).revisions[(loaded.package_id, loaded.version)]
            assert live._resolved.model_routes["primary"]["model"] == "frozen-original-model"
    finally:
        for stream in streams:
            await stream.detach()
        await app.close()
