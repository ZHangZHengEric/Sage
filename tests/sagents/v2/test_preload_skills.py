"""Preloads are per-Run initialization, never a permanent activation requirement."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.contracts import SessionStore

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.errors import RuntimeErrorInfo
from tests.sagents.v2.sdk_fixture import build_registered_package

import hashlib
import json

import pytest
from pydantic import ValidationError

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy
from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.agent.state import AgentLoopCheckpointState
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    DelegationTask,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, PauseRun, ResumeRun, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model import ModelEventKind, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.package.manifest import SageManifestLoader
from sagents.v2.package.manifest.agents import AgentDefinition, Instructions
from sagents.v2.package.manifest.resolver import CompositionResolver, ResolvedAgent
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
from sagents.v2.skill import (
    FilteredSkillCatalog, InMemorySkillActivationRepository, InMemorySkillProvider,
    InMemorySkillWorkspace, SkillBundle, SkillDescriptor, SkillLoader,
)
from sagents.v2.skill.context import ActiveSkillsContextProvider
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.tool.plugins.skill import SkillToolPlugin


CONTEXT = RequestContext(actor=ActorRef(principal_id="test", principal_type=PrincipalType.USER,
                                       scopes=("skill.load", "agent.delegate")))
MANIFEST = """
schema_version: sage/v2
kind: application
metadata: {id: test.preload, version: 1.0.0, name: Preloads}
agents:
  root:
    name: Root
    instructions: {inline: Work}
    skills: [alpha, beta]
    preload_skills: [alpha]
  child:
    name: Child
    instructions: {inline: Work}
    skills: [alpha, beta]
    preload_skills: [beta]
entrypoint: {agent: root}
"""


def source():
    return InMemorySkillProvider(tuple(SkillBundle(
        descriptor=SkillDescriptor(name=name, description=name, source_id="test"),
        files={"SKILL.md": f"Follow {name}".encode()}, content_hash=f"hash-{name}",
    ) for name in ("alpha", "beta")))


def loader(provider, *, budget=24000):
    return SkillLoader(catalog=provider, source=provider, workspace=InMemorySkillWorkspace(),
                       activations=InMemorySkillActivationRepository(), max_active_characters=budget)


def done(*calls):
    return ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
        response_id="response", text="" if calls else "done", tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop"))


def model(*events, assertion=None):
    return ScriptedModelProvider(tuple(ScriptedModelStep(events=(event,), assertion=assertion)
                                       for event in events))


def engine(runtime, provider_model, skill_loader, defaults=("alpha",)):
    skill_tools = SkillToolPlugin(skill_loader)
    return AgentLoopEngine(
        runtime=runtime, model=provider_model, tool_catalog=skill_tools.catalog,
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
        tool_executor=skill_tools.executor, skill_loader=skill_loader, preload_skills=defaults,
        context_assembler=DefaultContextAssembler(providers=(ActiveSkillsContextProvider(skill_loader),)),
    )


async def start(runtime, *, session_id=None, agent="root", key="start", enabled=None):
    return await runtime.start_run(StartRun(
        session_id=session_id, agent_id=agent, resolved_spec_hash="sha256:test",
        config=RunConfig(model_bindings={"primary": "test"}, enabled_skills=enabled),
        input=(InputItem(role="user", content=(TextBlock(text="work"),)),), idempotency_key=key,
    ), CONTEXT)


def content(request):
    return "\n".join(block.text for message in request.messages for block in message.content
                     if isinstance(block, TextBlock))


@pytest.mark.parametrize("contract,values", [
    (AgentDefinition, {"name": "A", "instructions": Instructions(inline="work")}),
    (ResolvedAgent, {"name": "A", "instructions": "work", "entrypoint": {}}),
    (AgentDescriptor, {"agent_id": "a", "name": "A", "description": "", "instructions": "work"}),
])
def test_preload_declaration_cannot_expand_skill_permissions(contract, values):
    assert contract(**values).preload_skills == ()
    assert contract(**values, skills=("alpha",), preload_skills=("alpha",)).preload_skills == ("alpha",)
    with pytest.raises(ValidationError, match="subset"):
        contract(**values, skills=("alpha",), preload_skills=("beta",))


def test_manifest_resolution_and_legacy_hash_compatibility():
    manifest = SageManifestLoader().loads(MANIFEST)
    resolved = CompositionResolver().resolve(manifest)
    assert resolved.agents["root"].preload_skills == ("alpha",)
    assert resolved.agents["child"].preload_skills == ("beta",)
    assert resolved.policy_ceilings["root"].allowed_skills == {"alpha", "beta"}
    legacy = SageManifestLoader().loads(MANIFEST.replace("    preload_skills: [alpha]\n", "")
                                      .replace("    preload_skills: [beta]\n", ""))
    payload = legacy.model_dump(mode="json", exclude={"environments"})
    for definition in payload["agents"].values():
        definition.pop("preload_skills")
    from sagents.v2.model.catalog import ModelCatalogConfig
    payload["models"] = ModelCatalogConfig().model_dump(mode="json")
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert CompositionResolver().resolve(legacy).manifest_hash == f"sha256:{expected}"


@pytest.mark.asyncio
async def test_each_new_run_in_same_session_preloads_before_first_model():
    runtime, provider = ephemeral_runtime(), source()
    requests = model(done(), done(), assertion=lambda request: (
        pytest.fail("missing preload") if "Follow alpha" not in content(request) else None))
    session = None
    for index in range(2):
        run = await start(runtime, session_id=session, key=f"start-{index}")
        session = run.session_id
        assert (await engine(runtime, requests, loader(provider)).execute(run.run_id, CONTEXT)).state == RunState.COMPLETED
    assert len(provider.fetches) == 2
    assert len({run_id for run_id, _ in provider.fetches}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "denied", "oversized", "unavailable"])
async def test_initialization_failure_is_diagnostic_and_never_calls_model(failure):
    runtime, provider = ephemeral_runtime(), source()
    loaded = loader(provider, budget=1 if failure == "oversized" else 24000)
    defaults = ("missing",) if failure == "missing" else ("alpha",)
    if failure == "denied":
        loaded.catalog = FilteredSkillCatalog(provider, ())
    requests = model(done())
    loop = engine(runtime, requests, loaded, defaults)
    if failure == "unavailable":
        loop.skill_loader = None
    run = await start(runtime)
    result = await loop.execute(run.run_id, CONTEXT)
    assert result.state in {RunState.SUSPENDED, RunState.FAILED}
    assert requests.requests == []
    events = await runtime.session_store.read_events(run.run_id)
    errors = [cast(RunEventData, event.data).error for event in events if getattr(event.data, "error", None)]
    assert cast(RuntimeErrorInfo, errors[-1]).code == "skill.preload_failed"
    assert cast('RuntimeErrorInfo', errors[-1]).metadata["run_id"] == run.run_id
    assert cast('RuntimeErrorInfo', errors[-1]).metadata["agent_id"] == "root"
    assert cast('RuntimeErrorInfo', errors[-1]).metadata["skill_name"] == defaults[0]
    if failure != "unavailable":
        assert cast('RuntimeErrorInfo', errors[-1]).metadata["cause_code"].startswith("skill.")


@pytest.mark.asyncio
async def test_defaults_can_evict_each_other_and_explicit_load_reactivates():
    runtime, provider = ephemeral_runtime(), source()
    loaded = loader(provider, budget=200)
    requests = model(
        done(ModelToolCall(tool_call_id="reload", name="load_skill", arguments={"skill_name": "alpha", "session_id": None})),
        done(),
    )
    run = await start(runtime)
    assert (await engine(runtime, requests, loaded, ("alpha", "beta")).execute(run.run_id, CONTEXT)).state == RunState.COMPLETED
    assert "Follow beta" in content(requests.requests[0])
    assert "Follow alpha" not in content(requests.requests[0])
    assert "Follow alpha" in content(requests.requests[1])
    assert "Follow beta" not in content(requests.requests[1])
    assert provider.fetches == [(run.run_id, "alpha"), (run.run_id, "beta"), (run.run_id, "alpha")]


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_process_restart_restores_same_run_without_reloading_evicted_defaults(tmp_path, empty):
    store = FilesystemSessionStore(tmp_path)
    runtime, provider = HarnessRuntime(cast('SessionStore', store)), source()
    loaded = loader(provider, budget=200)
    loop = engine(runtime, model(done()), loaded)
    handle = await start(runtime)
    run = await runtime.start_execution(run_id=handle.run_id, expected_revision=0,
                                        context=CONTEXT, idempotency_key="execute")
    command = await store.get_start_command(run.run_id)
    run = await loop._initialize_skills(run, command, CONTEXT)
    await loaded.load("beta", run_id=run.run_id)
    if empty:
        await loaded.activations.replace_loaded(run_id=run.run_id, values=())
    await runtime.pause_run(PauseRun(run_id=run.run_id, expected_revision=run.revision,
                                    idempotency_key="pause"), CONTEXT)
    state = AgentLoopCheckpointState(turn_id="turn", step_number=1,
        messages=await loop.context_assembler.initial_ledger(command, run_id=run.run_id))
    suspended = await loop.commit_safe_point_suspension(await runtime.get_run(run.run_id), state, CONTEXT)
    await store.close()
    # Reopen all runtime, model, loader, workspace and activation objects.
    reopened = FilesystemSessionStore(tmp_path)
    try:
        runtime = HarnessRuntime(cast('SessionStore', reopened))
        loaded = loader(provider, budget=200)
        # A history callback must not be invoked again on recovery either.
        async def forbidden_history(run_id):
            pytest.fail("history must not be restored on an initialized Run")
        loaded.inherited_skills = forbidden_history
        requests = model(done())
        loop = engine(runtime, requests, loaded)
        suspension = await reopened.get_suspension(suspended.suspension_id)
        await runtime.resume_run(ResumeRun(run_id=run.run_id, suspension_id=suspension.suspension_id,
            expected_revision=suspended.revision, expected_suspension_revision=suspension.expected_revision,
            idempotency_key="resume"), CONTEXT)
        assert (await loop.resume(run.run_id, CONTEXT)).state == RunState.COMPLETED
        assert "Follow alpha" not in content(requests.requests[0])
        assert ("Follow beta" in content(requests.requests[0])) is (not empty)
        assert provider.fetches == [(run.run_id, "alpha"), (run.run_id, "beta")]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_parent_children_and_grandchildren_read_their_own_configuration():
    runtime, provider = ephemeral_runtime(), source()
    manifest = SageManifestLoader().loads(MANIFEST)
    resolved = CompositionResolver().resolve(manifest)
    factory = AgentCompositionFactory(runtime)
    requests = {}
    def compose(descriptor, run_id):
        requests[run_id] = model(done())
        return factory.create_loop(resolved, descriptor.agent_id,
            model=requests[run_id], tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}), skill_loader=loader(provider),
            completion_gates=(), expected_resolved_spec_hash="sha256:test")
    root = await start(runtime)
    # Keep ancestors running while child Runs are allocated by the real child executor.
    running = await runtime.start_execution(run_id=root.run_id, expected_revision=0,
                                            context=CONTEXT, idempotency_key="root-execute")
    parent_loop = compose(AgentDescriptor(agent_id="root", name="Root", description="", instructions="work"), root.run_id)
    await parent_loop._initialize_skills(running, await runtime.session_store.get_start_command(root.run_id), CONTEXT)
    executor = LoopChildRunExecutor(runtime=runtime, loop_factory=compose, resolved_spec_hash="sha256:test")
    async def child(parent, agent, index):
        definition = resolved.agents[agent]
        return await executor.run_child(AgentDescriptor(agent_id=agent, name=agent, description="", instructions="work",
            skills=definition.skills, preload_skills=definition.preload_skills),
            DelegationTask(task_id=f"task-{index}", agent_id=agent, task_name="work", original_task="work", content="work"),
            parent_run_id=parent, workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD, context=CONTEXT)
    first = await child(root.run_id, "child", 1)
    assert first.outcome == RunState.COMPLETED, first
    second = await child(first.child_run_id, "root", 2)
    assert second.outcome == RunState.COMPLETED
    assert "Follow beta" in content(requests[first.child_run_id].requests[0])
    assert "Follow alpha" not in content(requests[first.child_run_id].requests[0])
    assert "Follow alpha" in content(requests[second.child_run_id].requests[0])


@pytest.mark.asyncio
async def test_restart_mid_initialization_skips_preloads_already_evicted(tmp_path):
    import asyncio
    store = FilesystemSessionStore(tmp_path)
    runtime, provider = HarnessRuntime(cast('SessionStore', store)), source()
    provider._bundles["gamma"] = SkillBundle(
        descriptor=SkillDescriptor(name="gamma", description="gamma", source_id="test"),
        files={"SKILL.md": b"Follow gamma"}, content_hash="hash-gamma")
    original = provider.get_skill
    async def interrupt(name, *, run_id):
        if name == "gamma":
            raise asyncio.CancelledError()
        return await original(name, run_id=run_id)
    provider.get_skill = interrupt
    run = await start(runtime)
    try:
        with pytest.raises(asyncio.CancelledError):
            await engine(runtime, model(done()), loader(provider, budget=200),
                         ("alpha", "beta", "gamma")).execute(run.run_id, CONTEXT)
        assert provider.fetches == [(run.run_id, "alpha"), (run.run_id, "beta")]
    finally:
        await store.close()
    provider.get_skill = original
    reopened = FilesystemSessionStore(tmp_path)
    try:
        requests = model(done())
        result = await engine(HarnessRuntime(cast('SessionStore', reopened)), requests, loader(provider, budget=200),
                              ("alpha", "beta", "gamma")).execute(run.run_id, CONTEXT)
        assert result.state == RunState.COMPLETED
        assert "Follow gamma" in content(requests.requests[0])
        assert "Follow alpha" not in content(requests.requests[0])
        assert provider.fetches == [(run.run_id, name) for name in ("alpha", "beta", "gamma")]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_unconfigured_run_preserves_lazy_loading_and_emits_no_skill_state():
    runtime, provider = ephemeral_runtime(), source()
    requests = model(done())
    run = await start(runtime)
    assert (await engine(runtime, requests, loader(provider), ()).execute(run.run_id, CONTEXT)).state == RunState.COMPLETED
    assert provider.fetches == []
    assert "Follow alpha" not in content(requests.requests[0])
    assert not any(event.type == "skill.state" for event in await runtime.session_store.read_events(run.run_id))


@pytest.mark.asyncio
async def test_partial_failure_retry_after_restart_does_not_reinject_completed_defaults(tmp_path):
    from sagents.v2.contracts.commands import ReplyInteraction
    store = FilesystemSessionStore(tmp_path)
    runtime, provider = HarnessRuntime(cast('SessionStore', store)), source()
    run = await start(runtime)
    requests = model(done())
    result = await engine(runtime, requests, loader(provider, budget=200),
                          ("alpha", "beta", "gamma")).execute(run.run_id, CONTEXT)
    assert result.state == RunState.SUSPENDED
    assert requests.requests == []
    suspension = await store.get_suspension(result.suspension_id)
    interaction = await store.get_interaction(suspension.interaction_id)
    await store.close()
    provider._bundles["gamma"] = SkillBundle(
        descriptor=SkillDescriptor(name="gamma", description="gamma", source_id="test"),
        files={"SKILL.md": b"Follow gamma"}, content_hash="hash-gamma")
    reopened = FilesystemSessionStore(tmp_path)
    try:
        runtime = HarnessRuntime(cast('SessionStore', reopened))
        await runtime.reply_interaction(ReplyInteraction(
            run_id=run.run_id, suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id, expected_revision=result.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="retry", idempotency_key="retry"), CONTEXT)
        requests = model(done())
        result = await engine(runtime, requests, loader(provider, budget=200),
                              ("alpha", "beta", "gamma")).resume(run.run_id, CONTEXT)
        assert result.state == RunState.COMPLETED
        assert "Follow gamma" in content(requests.requests[0])
        assert provider.fetches == [(run.run_id, name) for name in ("alpha", "beta", "gamma")]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_run_grant_can_narrow_preloads_but_never_expand_permissions():
    runtime, provider = ephemeral_runtime(), source()
    resolved = CompositionResolver().resolve(SageManifestLoader().loads(MANIFEST))
    factory = AgentCompositionFactory(runtime)
    loaded = factory.create_skill_loader(resolved, "root", catalog=provider, source=provider,
        workspace=InMemorySkillWorkspace(), activations=InMemorySkillActivationRepository())
    run = await start(runtime, enabled=("beta",))
    requests = model(done())
    result = await engine(runtime, requests, loaded).execute(run.run_id, CONTEXT)
    assert result.state == RunState.SUSPENDED
    assert requests.requests == []
    errors = [cast(RunEventData, event.data).error for event in await runtime.session_store.read_events(run.run_id)
              if getattr(event.data, "error", None)]
    assert cast('RuntimeErrorInfo', errors[-1]).metadata["cause_code"] == "skill.not_enabled"
    assert provider.fetches == []


@pytest.mark.asyncio
async def test_preloads_finish_before_auxiliary_model_preparation():
    from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy
    runtime, provider = ephemeral_runtime(), source()
    loaded = loader(provider)
    prepared = []
    class InspectPreparation(RecentToolSelectionPolicy):
        async def prepare(self, context):
            prepared.append(context.run_id)
            assert [item.descriptor.name for item in await loaded.loaded(run_id=context.run_id)] == ["alpha"]
            await super().prepare(context)
    run = await start(runtime)
    loop = engine(runtime, model(done()), loaded)
    loop.tool_selection_policy = InspectPreparation()
    assert (await loop.execute(run.run_id, CONTEXT)).state == RunState.COMPLETED
    assert prepared == [run.run_id]


@pytest.mark.asyncio
async def test_public_builder_wires_agent_package_preloads(tmp_path):
    from tests.sagents.v2.model_fixture import TEST_MODELS
    manifest = SageManifestLoader().loads(MANIFEST)
    manifest = manifest.model_copy(update={"agents": {"root": manifest.agents["root"]}})
    provider, requests = source(), model(done())
    app = await (build_registered_package(tmp_path, models=TEST_MODELS, model=requests, tools=(InMemoryToolCatalog(()), InMemoryToolExecutor({}, {}),), skills=(provider, provider, InMemorySkillWorkspace(),), package=manifest))
    try:
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream((StartRun(
            agent_id="root", input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash=app.composition_hash, idempotency_key="builder")).model_copy(update={"agent_id": app.loaded_agents[-1].id, "resolved_spec_hash": app.loaded_agents[-1].composition_hash}), CONTEXT, agent=app.loaded_agents[-1])
        assert (await stream.wait()).state == RunState.COMPLETED
        assert "Follow alpha" in content(requests.requests[0])
        assert [name for _, name in provider.fetches] == ["alpha"]
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_legacy_checkpoint_does_not_retroactively_initialize_defaults():
    runtime, provider = ephemeral_runtime(), source()
    loaded = loader(provider)
    original = engine(runtime, model(done()), loaded, ())
    handle = await start(runtime)
    run = await runtime.start_execution(run_id=handle.run_id, expected_revision=0,
                                        context=CONTEXT, idempotency_key="execute")
    command = await runtime.session_store.get_start_command(run.run_id)
    await runtime.pause_run(PauseRun(run_id=run.run_id, expected_revision=run.revision,
                                    idempotency_key="pause"), CONTEXT)
    suspended = await original.commit_safe_point_suspension(await runtime.get_run(run.run_id),
        AgentLoopCheckpointState(turn_id="turn", step_number=1,
            messages=await original.context_assembler.initial_ledger(command, run_id=run.run_id)), CONTEXT)
    checkpoint = await runtime.session_store.get_latest_checkpoint(run.run_id)
    assert checkpoint.state.get("skill_state") is None
    suspension = await runtime.session_store.get_suspension(cast(str, suspended.suspension_id))
    await runtime.resume_run(ResumeRun(run_id=run.run_id, suspension_id=suspension.suspension_id,
        expected_revision=suspended.revision, expected_suspension_revision=suspension.expected_revision,
        idempotency_key="resume"), CONTEXT)
    requests = model(done())
    assert (await engine(runtime, requests, loaded).resume(run.run_id, CONTEXT)).state == RunState.COMPLETED
    assert provider.fetches == []
    assert "Follow alpha" not in content(requests.requests[0])


@pytest.mark.asyncio
async def test_concurrent_initialization_does_not_reload_budget_evictions():
    import asyncio
    provider = source()
    loaded = loader(provider, budget=200)
    await asyncio.gather(*(loaded.initialize_preloads(("alpha", "beta"), run_id="run")
                           for _ in range(3)))
    assert provider.fetches == [("run", "alpha"), ("run", "beta")]
    assert [skill.descriptor.name for skill in await loaded.loaded(run_id="run")] == ["beta"]


@pytest.mark.asyncio
async def test_pause_mid_initialization_resumes_remaining_preloads_only():
    import asyncio
    runtime, provider = ephemeral_runtime(), source()
    entered, release = asyncio.Event(), asyncio.Event()
    loaded = loader(provider, budget=200)
    materialize = loaded.workspace.materialize
    async def blocking_materialize(bundle, **kwargs):
        if bundle.descriptor.name == "alpha":
            entered.set()
            await release.wait()
        return await materialize(bundle, **kwargs)
    loaded.workspace.materialize = blocking_materialize
    requests = model(done())
    loop = engine(runtime, requests, loaded, ("alpha", "beta"))
    handle = await start(runtime)
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(entered.wait(), 1)
    current = await runtime.get_run(handle.run_id)
    await runtime.pause_run(PauseRun(run_id=handle.run_id, expected_revision=current.revision,
                                    idempotency_key="pause-init"), CONTEXT)
    release.set()
    suspended = await asyncio.wait_for(execution, 1)
    assert suspended.state == RunState.SUSPENDED
    assert requests.requests == []
    assert provider.fetches == [(handle.run_id, "alpha")]
    suspension = await runtime.session_store.get_suspension(cast(str, suspended.suspension_id))
    await runtime.resume_run(ResumeRun(run_id=handle.run_id, suspension_id=suspension.suspension_id,
        expected_revision=suspended.revision, expected_suspension_revision=suspension.expected_revision,
        idempotency_key="resume-init"), CONTEXT)
    restored = engine(runtime, requests, loader(provider, budget=200), ("alpha", "beta"))
    assert (await restored.resume(handle.run_id, CONTEXT)).state == RunState.COMPLETED
    assert provider.fetches == [(handle.run_id, "alpha"), (handle.run_id, "beta")]
    assert "Follow beta" in content(requests.requests[0])
    assert "Follow alpha" not in content(requests.requests[0])


@pytest.mark.parametrize("with_dependency", [False, True])
def test_legacy_bundle_content_hash_is_stable(with_dependency):
    from sagents.v2.agent.management import AgentPackageBundle
    manifest = SageManifestLoader().loads(MANIFEST)
    definition = manifest.agents["root"].model_copy(update={"preload_skills": ()})
    manifest = manifest.model_copy(update={"agents": {"root": definition}})
    child = AgentPackageBundle(manifest=manifest)
    bundle = AgentPackageBundle(
        manifest=manifest, dependencies={"worker": child} if with_dependency else {},
    )
    legacy_payload = bundle.model_dump(mode="json")
    def remove_new_field(value):
        for agent in value["manifest"]["agents"].values():
            agent.pop("preload_skills", None)
        for dependency in value.get("dependencies", {}).values():
            remove_new_field(dependency)
    remove_new_field(legacy_payload)
    legacy_hash = hashlib.sha256(json.dumps(
        legacy_payload, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert AgentPackageBundle.model_validate(legacy_payload).content_hash == legacy_hash


@pytest.mark.asyncio
async def test_pause_racing_preload_commit_is_not_reported_as_load_failure():
    runtime, provider = ephemeral_runtime(), source()
    loaded = loader(provider, budget=200)
    snapshot_run = loaded.snapshot_run
    paused = False
    async def pause_before_commit(run_id):
        nonlocal paused
        snapshot = await snapshot_run(run_id)
        if snapshot["processed_preloads"] == ["alpha"] and not paused:
            paused = True
            current = await runtime.get_run(run_id)
            await runtime.pause_run(PauseRun(
                run_id=run_id, expected_revision=current.revision,
                idempotency_key="pause-between-read-and-commit",
            ), CONTEXT)
        return snapshot
    loaded.snapshot_run = pause_before_commit
    requests = model(done())
    run = await start(runtime)
    result = await engine(runtime, requests, loaded, ("alpha", "beta")).execute(run.run_id, CONTEXT)
    assert result.state == RunState.SUSPENDED
    assert requests.requests == []
    assert provider.fetches == [(run.run_id, "alpha")]
    assert not any(event.type == "step.failed"
                   for event in await runtime.session_store.read_events(run.run_id))


@pytest.mark.asyncio
async def test_legacy_package_can_be_read_and_saved_under_original_immutable_ref(tmp_path):
    from sagents.v2.agent.management import AgentPackageBundle, AgentPackageStore
    manifest = SageManifestLoader().loads(MANIFEST)
    definition = manifest.agents["root"].model_copy(update={"preload_skills": ()})
    manifest = manifest.model_copy(update={"agents": {"root": definition}})
    payload = AgentPackageBundle(manifest=manifest).model_dump(mode="json")
    for agent in payload["manifest"]["agents"].values():
        agent.pop("preload_skills", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    ref = hashlib.sha256(encoded.encode()).hexdigest()
    store = AgentPackageStore(tmp_path / "packages.db")
    # Seed exactly the payload/ref an older version persisted.
    with store._connect() as database:
        database.execute("INSERT INTO bundles VALUES (?, ?, ?, ?, ?)", (
            "owner", ref, manifest.metadata.id, manifest.metadata.version, encoded,
        ))
    restored = await store.get("owner", ref)
    assert restored.content_hash == ref
    assert await store.save("owner", restored) == ref
    assert await store.version_ref("owner", manifest.metadata.id, manifest.metadata.version) == ref
    changed = restored.model_copy(update={"manifest": manifest.model_copy(update={
        "agents": {"root": definition.model_copy(update={"preload_skills": ("alpha",)})},
    })})
    assert changed.content_hash != ref
