"""Run-tree Skill attachments through public build/load/entrypoint APIs."""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.composition.defaults import default_runtime
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction, RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider
from sagents.v2.skill import (
    InMemorySkillProvider, InMemorySkillWorkspace, RuntimeSkillAttachment,
    RuntimeSkillAuthorization,
)
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.sdk_fixture import build_registered_app
from tests.sagents.v2.test_builder_nested_teams import Models, delegate, package, CONTEXT
from tests.sagents.v2.test_skill_provider_matrix import bundle


CONTEXT = CONTEXT.model_copy(update={"actor": CONTEXT.actor.model_copy(update={"scopes": ("skill.load",)})})
EXTRA = bundle("temporary-guide", "UNIQUE RUNTIME INSTRUCTIONS")
ATTACHMENT = RuntimeSkillAttachment.from_bundle(EXTRA)
LOAD = ("load_skill", {"skill_name": EXTRA.descriptor.name})


async def open_app(root, plans, *, authorized=True, approval=False, existing=(), real_workspace=False):
    models = Models(plans)
    bindings = LocalWorkspaceExecutionBindingProvider(root / "workspace", process_enabled=False)
    config = default_runtime(root / "sessions")
    config = config.model_copy(update={
        "runtime_skill_authorizations": (RuntimeSkillAuthorization.from_bundle(EXTRA),) if authorized else (),
        "capabilities": {**config.capabilities,
            "tool.provider": CapabilitySelection(plugin="sage.tool.official"),
            "tool.selection-policy": CapabilitySelection(plugin="sage.tool-selection.direct"),
            "agent.continuation-policy": CapabilitySelection(plugin="sage.agent.continuation.deterministic"),
        },
    })
    class Policy(DefaultToolPolicy):
        async def decide(self, context):
            if approval and context.definition.name == "file_write":
                return await DefaultToolPolicy(approval_strategy=ApprovalStrategy.ALWAYS_ASK).decide(context)
            return await super().decide(context)

    app = await build_registered_app(
        root / "sessions", runtime=config,
        models={**TEST_MODELS, "models": {**TEST_MODELS["models"], **{
            role: TEST_MODELS["models"]["primary"] for role in ("root", "d1", "d2", "maker", "outsider")
        }}}, model_factory=models.factory,
        skills=(InMemorySkillProvider(existing), InMemorySkillProvider(existing),
                None if real_workspace else InMemorySkillWorkspace()),
        providers={"execution.binding": bindings, "agent.tool-policy": Policy(
            approval_strategy=ApprovalStrategy.AUTO_APPROVE)},
    )
    return app, bindings, models


def no_skills(role, children=()):
    value = package(role, children)
    return value.model_copy(update={"agents": {"assistant": value.agents["assistant"].model_copy(
        update={"skills": (), "preload_skills": ()})}})


async def load_tree(app):
    member = await app.load_agent(no_skills("maker"))
    d2 = await app.load_agent(no_skills("d2", ("maker",)), subagents={"maker": member})
    d1 = await app.load_agent(no_skills("d1", ("d2",)), subagents={"d2": d2})
    outsider = await app.load_agent(no_skills("outsider"))
    return await app.load_agent(no_skills("root", ("d1", "outsider")), subagents={"d1": d1, "outsider": outsider})


async def run(app, agent, *, key="start", attachments=(ATTACHMENT,), session_id=None):
    stream = await app.entrypoint().run_stream(StartRun(
        agent_id=agent.id, resolved_spec_hash=agent.composition_hash, input=(),
        config=RunConfig(skill_attachments=attachments), idempotency_key=key,
        session_id=session_id,
    ), CONTEXT, agent=agent)
    async with asyncio.timeout(60):
        events = [event async for event in stream.events]
        result = await stream.wait()
    return result, events


def prompt(request):
    return "\n".join(getattr(block, "text", "") for message in request.messages
                     if message.role in {"system", "developer"} for block in message.content)


def plans():
    return {"root": (LOAD, delegate("d1", "outsider")),
            "d1": (LOAD, delegate("d2")), "d1.d2": (LOAD, delegate("maker")),
            "d1.d2.maker": (LOAD,), "outsider": (LOAD,)}


@pytest.mark.asyncio
@pytest.mark.parametrize("preload", [False, True])
async def test_team_members_load_extra_skill_in_parallel_on_real_workspace(tmp_path, monkeypatch, preload):
    from sagents.v2.skill.plugins.workspace import AutoSyncSkillWorkspace

    app, bindings, models = await open_app(tmp_path, {
        "root": (() if preload else (LOAD,)) + (delegate("maker", "outsider"),),
        "maker": () if preload else (LOAD,),
        "outsider": () if preload else (LOAD,),
    }, real_workspace=True)
    ready = asyncio.Event()
    arrived = set()
    original = AutoSyncSkillWorkspace.materialize

    async def materialize(self, value, *, run_id, destination):
        command = await app.runtime.session_store.get_start_command(run_id)
        if command.parent_run_id:
            arrived.add(command.agent_id)
            if len(arrived) == 2:
                ready.set()
            # Require both members to reach loading before either proceeds.
            # A sequential execution would time out and fail this regression.
            await asyncio.wait_for(ready.wait(), timeout=10)
        path = await original(self, value, run_id=run_id, destination=destination)
        if not command.parent_run_id:
            await self._write(path + "/generated.txt", b"shared team work", run_id)
        return path

    monkeypatch.setattr(AutoSyncSkillWorkspace, "materialize", materialize)
    try:
        maker = await app.load_agent(no_skills("maker"))
        outsider = await app.load_agent(no_skills("outsider"))
        agent = await app.load_agent(no_skills("root", ("maker", "outsider")),
                                     subagents={"maker": maker, "outsider": outsider})
        result, events = await run(app, agent, attachments=(
            ATTACHMENT.model_copy(update={"preload": preload}),))
        assert result.state.value == "completed", [
            (event.type, event.data) for event in events if "failed" in event.type]
        assert arrived == {"maker", "outsider"}
        for role in ("root", "maker", "outsider"):
            requests = [request for name, request in models.seen if name == role]
            assert requests, role
            assert any("UNIQUE RUNTIME INSTRUCTIONS" in prompt(request) for request in requests), role
            assert all("skill.workspace_in_use" not in request.model_dump_json() for request in requests)
        assert (tmp_path / "workspace/skills/temporary-guide/generated.txt").read_bytes() == b"shared team work"
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, "d1"])
@pytest.mark.parametrize("real_workspace", [False, True])
async def test_nested_discovery_load_isolation_and_permissions(tmp_path, target, real_workspace):
    plan = plans()
    if target:
        plan.update(root=(delegate("d1", "outsider"),), outsider=())
    app, bindings, models = await open_app(tmp_path, plan, real_workspace=real_workspace)
    try:
        agent = await load_tree(app)
        attachment = ATTACHMENT.model_copy(update={"target_agent_id": target})
        result, events = await run(app, agent, attachments=(attachment,))
        assert result.state.value == "completed", [(event.type, event.data) for event in events if "failed" in event.type]
        policies = {}
        for role in ("root", "d1", "d1.d2", "d1.d2.maker", "outsider"):
            requests = [request for name, request in models.seen if name == role]
            assert requests, role
            available = target is None or role.startswith("d1")
            assert ("<skill_name>temporary-guide</skill_name>" in prompt(requests[0])) == available
            assert "UNIQUE RUNTIME INSTRUCTIONS" not in prompt(requests[0])
            assert any("UNIQUE RUNTIME INSTRUCTIONS" in prompt(request) for request in requests) == available
            for request in requests:
                tools = {tool.name for tool in request.tools}
                assert "execute_shell_command" not in tools
                assert ("file_write" in tools) == (role in {"d1.d2.maker", "outsider"})
                assert "file_read" not in tools or role in {"root", "d1", "d1.d2"}
                configuration = await app.execution_configuration(request.run_id, CONTEXT)
                assert not configuration.policy["process"]["enabled"]
                policies[role] = configuration.policy
        start = len(models.seen)
        models.plans = {"root": (delegate("d1", "outsider"),), "d1": (delegate("d2"),),
                        "d1.d2": (delegate("maker"),)}
        other, _ = await run(app, agent, key="isolated", attachments=())
        assert other.state.value == "completed"
        assert all("temporary-guide" not in prompt(request) for _, request in models.seen[start:])
        for role, request in models.seen[start:]:
            baseline = await app.execution_configuration(request.run_id, CONTEXT)
            assert baseline.policy == policies[role]
        # A new conversational Run does not silently renew a Run-tree grant.
        start = len(models.seen)
        continued, _ = await run(app, agent, key="next", attachments=(), session_id=result.session_id)
        assert continued.state.value == "completed"
        assert all("<available_skills>" not in prompt(request) for _, request in models.seen[start:])
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_explicit_preload_and_host_authorization(tmp_path):
    app, bindings, models = await open_app(tmp_path, {
        "root": (delegate("d1"),), "d1": (delegate("d2"),), "d1.d2": (delegate("maker"),),
    })
    try:
        agent = await load_tree(app)
        result, _ = await run(app, agent, attachments=(ATTACHMENT.model_copy(update={"preload": True}),))
        assert result.state.value == "completed"
        assert {role for role, _ in models.seen} == {"root", "d1", "d1.d2", "d1.d2.maker"}
        assert all("UNIQUE RUNTIME INSTRUCTIONS" in prompt(request) for _, request in models.seen)
    finally:
        await app.close()
        await bindings.close()
    app, bindings, _ = await open_app(tmp_path / "denied", {}, authorized=False)
    try:
        agent = await load_tree(app)
        with pytest.raises(SageV2Error, match="host authorization"):
            await run(app, agent)
        # The existing package whitelist is still enforced separately.
        result, _ = await run(app, agent, attachments=(), key="without-attachment")
        assert result.state.value == "completed"
    finally:
        await app.close()
        await bindings.close()


def test_snapshot_binary_identity_and_tamper_rejection():
    binary = bundle("binary", "x").model_copy(update={"files": {"SKILL.md": b"x", "asset.bin": b"\xff\x00"}})
    from sagents.v2.skill.bundles import files_digest
    binary = binary.model_copy(update={"content_hash": files_digest(binary.files)})
    attachment = RuntimeSkillAttachment.from_bundle(binary)
    assert RuntimeSkillAttachment.model_validate_json(attachment.model_dump_json()).bundle() == binary
    with pytest.raises(ValidationError, match="hash mismatch"):
        RuntimeSkillAttachment.model_validate({**attachment.model_dump(), "content_hash": "sha256:wrong"})


@pytest.mark.asyncio
async def test_conflicting_existing_source_fails_closed(tmp_path):
    app, bindings, models = await open_app(tmp_path, {}, existing=(EXTRA,))
    try:
        agent = await load_tree(app)
        result, _ = await run(app, agent)
        assert result.state.value in {"failed", "suspended"}
        assert not models.seen
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
async def test_cold_restart_retains_source_scope_and_rechecks_host_grant(tmp_path, revoke):
    plan = {"root": (delegate("d1"),), "d1": (delegate("d2"),),
            "d1.d2": (delegate("maker"),), "d1.d2.maker": (LOAD, ("file_write", {
                "file_path": "result.txt", "content": "restored"}))}
    app, bindings, _ = await open_app(tmp_path, plan, approval=True)
    try:
        agent = await load_tree(app)
        result, _ = await run(app, agent, attachments=(ATTACHMENT.model_copy(update={"target_agent_id": "d1"}),))
        assert result.state.value == "suspended"
        run_id = result.run_id
    finally:
        await app.close()
        await bindings.close()
    app, bindings, models = await open_app(tmp_path, plan, authorized=not revoke, approval=True)
    try:
        restored = await app.agent_for_run(run_id, CONTEXT)
        state = await app.runtime.get_run(run_id)
        store = app.runtime.session_store
        suspension = await store.get_suspension(state.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        await app.runtime.reply_interaction(ReplyInteraction(
            run_id=run_id, suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id, expected_revision=state.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once", idempotency_key="approve-restored",
        ), CONTEXT)
        await app.entrypoint().continue_run(run_id, CONTEXT, agent=restored)
        async with asyncio.timeout(60):
            while (await app.runtime.get_run(run_id)).state.value in {"queued", "running", "resuming"}:
                await asyncio.sleep(0.01)
        state = await app.runtime.get_run(run_id)
        assert state.state.value == ("failed" if revoke else "completed")
        assert (tmp_path / "workspace/result.txt").exists() == (not revoke)
        if not revoke:
            assert any("UNIQUE RUNTIME INSTRUCTIONS" in prompt(request)
                       for role, request in models.seen if role == "d1.d2.maker")
            assert all("temporary-guide" not in prompt(request)
                       for role, request in models.seen if role == "root")
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_live_authorization_update_applies_without_rebuild(tmp_path):
    app, bindings, models = await open_app(tmp_path, {"root": (LOAD,)}, authorized=False)
    try:
        agent = await load_tree(app)
        with pytest.raises(SageV2Error, match="host authorization"):
            await run(app, agent, key="before-grant")
        grant = RuntimeSkillAuthorization.from_bundle(EXTRA)
        assert await app.update_runtime_skill_authorizations([grant.model_dump(mode="json")]) == (grant,)
        assert app.runtime_configuration.runtime_skill_authorizations == (grant,)
        # The App ceiling is not part of an Agent revision identity.
        assert (await load_tree(app)).composition_hash == agent.composition_hash
        result, _ = await run(app, agent, key="after-grant")
        assert result.state.value == "completed"
        assert any("UNIQUE RUNTIME INSTRUCTIONS" in prompt(request) for _, request in models.seen)
        await app.update_runtime_skill_authorizations(())
        with pytest.raises(SageV2Error, match="host authorization"):
            await run(app, agent, key="after-revoke")
        with pytest.raises(ValueError, match="update_runtime_skill_authorizations"):
            await app.load_agent(no_skills("maker"), runtime=app.runtime_configuration.model_copy(
                update={"runtime_skill_authorizations": (grant,)}))
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
async def test_live_revocation_rechecks_suspended_run_on_resume(tmp_path, revoke):
    app, bindings, _ = await open_app(tmp_path, {"root": (delegate("d1"),), "d1": (delegate("d2"),),
        "d1.d2": (delegate("maker"),), "d1.d2.maker": (LOAD, ("file_write", {
            "file_path": "live.txt", "content": "resumed"}))}, approval=True)
    try:
        agent = await load_tree(app)
        paused, _ = await run(app, agent, attachments=(ATTACHMENT.model_copy(update={"target_agent_id": "d1"}),))
        assert paused.state.value == "suspended"
        if revoke:
            await app.update_runtime_skill_authorizations(())
        state = await app.runtime.get_run(paused.run_id)
        store = app.runtime.session_store
        suspension = await store.get_suspension(state.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        receipt = await app.runtime.reply_interaction(ReplyInteraction(
            run_id=paused.run_id, suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id, expected_revision=state.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once", idempotency_key="approve-live",
        ), CONTEXT)
        assert receipt.decision.value == "accepted", receipt
        await app.entrypoint().continue_run(paused.run_id, CONTEXT, agent=agent)
        async with asyncio.timeout(60):
            while (await app.runtime.get_run(paused.run_id)).state.value in {"queued", "running", "resuming"}:
                await asyncio.sleep(0.01)
        state = await app.runtime.get_run(paused.run_id)
        assert state.state.value == ("failed" if revoke else "completed")
        assert (tmp_path / "workspace/live.txt").exists() == (not revoke)
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_cancellation_does_not_renew_attachment_in_next_run(tmp_path):
    app, bindings, models = await open_app(tmp_path, {"root": (delegate("d1"),),
        "d1": (delegate("d2"),), "d1.d2": (delegate("maker"),),
        "d1.d2.maker": (LOAD, ("file_write", {"file_path": "cancelled.txt", "content": "x"}))},
        approval=True)
    try:
        agent = await load_tree(app)
        paused, _ = await run(app, agent)
        assert paused.state.value == "suspended"
        receipt = await app.runtime.cancel_run(CancelRun(
            run_id=paused.run_id, expected_revision=paused.revision, idempotency_key="cancel"), CONTEXT)
        assert receipt.decision.value == "accepted"
        models.plans = {}
        start = len(models.seen)
        result, _ = await run(app, agent, key="after-cancel", attachments=(), session_id=paused.session_id)
        assert result.state.value == "completed"
        assert all("<available_skills>" not in prompt(request) for _, request in models.seen[start:])
        assert not (tmp_path / "workspace/cancelled.txt").exists()
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_snapshot_authorization_is_separate_from_actor_load_permission(tmp_path):
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT as no_load_scope
    app, bindings, models = await open_app(tmp_path, {"root": (LOAD,)})
    try:
        agent = await load_tree(app)
        stream = await app.entrypoint().run_stream(StartRun(
            agent_id=agent.id, resolved_spec_hash=agent.composition_hash, input=(),
            idempotency_key="no-scope", config=RunConfig(skill_attachments=(ATTACHMENT,)),
        ), no_load_scope, agent=agent)
        async for _ in stream.events:
            pass
        assert (await stream.wait()).state.value == "completed"
        assert "<skill_name>temporary-guide</skill_name>" in prompt(models.seen[0][1])
        assert all("UNIQUE RUNTIME INSTRUCTIONS" not in prompt(request) for _, request in models.seen)
        assert "skill.load" in models.seen[-1][1].model_dump_json()
    finally:
        await app.close()
        await bindings.close()


def test_inheritance_rejects_scope_widening_or_source_replacement():
    from sagents.v2.skill.runtime import inherit_runtime_skills
    grant = RuntimeSkillAuthorization.from_bundle(EXTRA, target_agent_ids=("d1",))
    parent = StartRun(agent_id="root", resolved_spec_hash="hash", input=(), idempotency_key="parent",
                      config=RunConfig(skill_attachments=(ATTACHMENT.model_copy(update={"target_agent_id": "d1"}),)))
    child = StartRun(agent_id="d1", resolved_spec_hash="hash", input=(), idempotency_key="child")
    inherited = inherit_runtime_skills(child, parent, (grant,))
    assert inherited.config.skill_attachments == parent.config.skill_attachments
    changed = ATTACHMENT.model_copy(update={"target_agent_id": "root"})
    with pytest.raises(SageV2Error, match="duplicate runtime Skill"):
        inherit_runtime_skills(child.model_copy(update={"config": RunConfig(skill_attachments=(changed,))}), parent, (grant,))
    with pytest.raises(SageV2Error, match="host authorization"):
        inherit_runtime_skills(parent, None, (RuntimeSkillAuthorization.from_bundle(
            EXTRA.model_copy(update={"descriptor": EXTRA.descriptor.model_copy(update={"source_id": "other"})})),))
