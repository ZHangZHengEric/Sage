"""Admission, binding, and recovery through registered standard SDK capabilities."""
import asyncio
import os
import sys

import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.agent.policy import DefaultToolPolicy, ApprovalStrategy
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.model.contracts import ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.package.manifest import SageManifest
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from tests.sagents.v2.model_fixture import TEST_MODELS

CONTEXT = RequestContext(actor=ActorRef(principal_id="owner", principal_type="user", tenant_id="one"))


@pytest.mark.parametrize(("disk_mb", "filesystem_limit", "expected_mb"), [
    (None, None, 4096),
    (1, None, 1),
    (32768, None, 32768),
    (32768, 2048 * 1024**2, 2048),
    (1024, 2048 * 1024**2, 1024),
])
def test_effective_file_capacity_inherits_explicit_disk_quota(disk_mb, filesystem_limit, expected_mb):
    from sagents.v2.runtime.execution.plugins.local_binding.registration import LocalExecutionBindingConfig

    values = {"workspace": "/workspace", "policy": {}}
    if disk_mb is not None:
        values["policy"]["resources"] = {"disk_mb": disk_mb, "require_hard_limits": False}
    if filesystem_limit is not None:
        values["policy"]["filesystem"] = {
            "max_total_bytes": filesystem_limit,
            "allowed_operations": ["read", "list", "write", "create", "delete", "rename"],
        }
    config = LocalExecutionBindingConfig.model_validate(values)
    assert config.policy.filesystem.max_total_bytes == expected_mb * 1024**2
    # Admission persists the effective value. Restoring serialized parameters
    # must neither reinstate the old default nor discard an explicit ceiling.
    restored = LocalExecutionBindingConfig.model_validate(config.model_dump(mode="json"))
    assert restored.policy.filesystem.max_total_bytes == expected_mb * 1024**2


def registration(plugin, capability, value, *, ownership="borrowed"):
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=plugin, name=plugin, version="1.0.0",
            provides=(CapabilityOffer(capability=capability, api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema={"type": "object", "additionalProperties": False},
        ), factory=lambda context, deps: value, ownership=ownership,
    )


def runtime(root, *, file_limit=128 * 1024**2, duration=7200):
    return RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(root / "state")}},
        "execution.binding": {"plugin": "sage.execution.binding.local-workspace", "config": {
            "workspace": str(root / "workspace"),
            "isolation_python": sys.executable,
            "command_path": os.defpath,
            "policy": {"filesystem": {"allowed_operations": ["read", "list", "write", "create", "delete", "rename"],
                                      "max_file_bytes": file_limit},
                       "process": {"enabled": True, "allow_shell": True, "allowed_executables": ["bash", "sh", "python3"],
                                   "max_wall_time_seconds": duration}},
        }},
        "model.provider": {"plugin": "test.standard.model"},
        "agent.tool-policy": {"plugin": "test.standard.policy"},
        "tool.provider": {"plugin": "sage.tool.official"},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
    }})


def package():
    return SageManifest.model_validate({
        "schema_version": "sage/v2", "kind": "agent-package",
        "metadata": {"id": "test.standard.execution", "version": "1", "name": "Standard"},
        "agents": {"main": {"name": "Main", "models": {"primary": "primary"},
                            "instructions": {"inline": "Use the tools."},
                            "tools": ["file_write", "file_read", "execute_shell_command"]}},
        "entrypoint": {"agent": "main"},
    })


def response(*calls, text="Done"):
    return ScriptedModelStep(events=(ModelStreamEvent(kind="completed", response=ModelResponse(
        response_id="reply", text="" if calls else text, finish_reason="tool_calls" if calls else "stop",
        tool_calls=calls,
    )),))


async def build(root, model, *, config=None):
    builder = SAgentBuilder()
    builder.register(registration("test.standard.model", "model.provider", model))
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)))
    return await builder.build(runtime=config or runtime(root), models=TEST_MODELS)


def command(agent, key, *, config=None, parent=None):
    return StartRun(agent_id=agent.id, resolved_spec_hash=agent.composition_hash,
                    input=(InputItem(role="user", content=(TextBlock(text="Do the work"),)),),
                    config=config or RunConfig(), idempotency_key=key, parent_run_id=parent)


async def run(app, agent, key, *, config=None, context=CONTEXT):
    stream = await app.entrypoint().run_stream(command(agent, key, config=config), context, agent=agent)
    async with asyncio.timeout(60):
        events = [event async for event in stream.events]
        result = await stream.wait()
    return result, events


@pytest.mark.asyncio
@pytest.mark.parametrize("disk_mb", [4096, 32768])
async def test_registered_standard_driver_uses_accepted_policy_and_real_resources(tmp_path, disk_mb):
    model = ScriptedModelProvider((response(ModelToolCall(tool_call_id="write", name="file_write",
                                                         arguments={"file_path": "result.txt", "content": "hello"})), response()))
    config = runtime(tmp_path).model_dump(mode="json")
    config["capabilities"]["execution.binding"]["config"]["policy"]["resources"] = {
        "disk_mb": disk_mb, "require_hard_limits": False,
    }
    if disk_mb > 4096:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Logical quota accounting must accept a workspace already above the
        # former default; sparse media avoids allocating five physical GiB.
        with (workspace / "existing-video.mp4").open("wb") as artifact:
            artifact.truncate(5 * 1024**3)
    app = await build(tmp_path, model, config=RuntimeConfig.model_validate(config))
    try:
        agent = await app.load_agent(package())
        result, _ = await run(app, agent, "write")
        assert result.state.value == "completed", result
        assert (tmp_path / "workspace/result.txt").read_text() == "hello"
        snapshot = await app.execution_configuration(result.run_id, CONTEXT)
        assert snapshot.policy["filesystem"]["max_file_bytes"] == 128 * 1024**2
        assert snapshot.policy["process"]["max_wall_time_seconds"] == 7200
        assert snapshot.policy["filesystem"]["max_total_bytes"] == disk_mb * 1024**2
        facts = await app.execution_diagnostics(result.run_id, CONTEXT)
        assert facts["configuration_id"] == snapshot.configuration_id
        assert facts["sandbox"]["owner_run_id"] == result.run_id
        assert facts["interpreter"]["executable"] != ""
        assert facts["capabilities"]["resources"]["memory"] is False
        assert "sandbox_environment" in str(model.requests[0].messages)
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_concurrent_apps_keep_models_workspaces_and_snapshots_separate(tmp_path):
    models = [ScriptedModelProvider((response(ModelToolCall(
        tool_call_id=f"write-{name}", name="file_write",
        arguments={"file_path": "result.txt", "content": name},
    )), response(text=name), response(text="Still running")))
        for name in ("desktop", "server")]
    roots = [tmp_path / name for name in ("desktop", "server")]
    apps = []
    try:
        for index, root in enumerate(roots):
            config = runtime(root, file_limit=(index + 1) * 1024)
            apps.append(await build(root, models[index], config=config))
        agents = await asyncio.gather(*(app.load_agent(package()) for app in apps))
        results = await asyncio.gather(*(
            run(app, agent, "same-product-idempotency-key")
            for app, agent in zip(apps, agents, strict=True)
        ))
        identities = []
        for index, (app, (result, _)) in enumerate(zip(apps, results, strict=True)):
            assert result.state.value == "completed", result
            assert (roots[index] / "workspace/result.txt").read_text() == roots[index].name
            snapshot = await app.execution_configuration(result.run_id, CONTEXT)
            assert snapshot.policy["filesystem"]["max_file_bytes"] == (index + 1) * 1024
            identities.append(snapshot.configuration_id)
            # Inspection must not hand out references into durable or in-memory
            # accepted commands, including the nested dictionaries of frozen models.
            snapshot.policy["filesystem"]["max_file_bytes"] = 999999
            saved = await app.execution_configuration(result.run_id, CONTEXT)
            assert saved.policy["filesystem"]["max_file_bytes"] == (index + 1) * 1024
            facts = await app.execution_diagnostics(result.run_id, CONTEXT)
            facts["sandbox"]["owner_run_id"] = "another-run"
            saved_facts = await app.execution_diagnostics(result.run_id, CONTEXT)
            assert saved_facts["sandbox"]["owner_run_id"] == result.run_id
        assert len(set(identities)) == 2
        with pytest.raises(ValueError, match="different application"):
            await run(apps[0], agents[1], "foreign-agent")
        # Closing one host must leave the other host's standard execution usable.
        await apps[0].close()
        result, _ = await run(apps[1], agents[1], "second-server-run")
        assert result.state.value == "completed", result
    finally:
        for app in reversed(apps):
            await app.close()


@pytest.mark.asyncio
async def test_runtime_updates_apply_to_new_revisions_and_preserve_accepted_runs(tmp_path):
    app = await build(tmp_path, ScriptedModelProvider((response(), response())))
    try:
        original_agent = await app.load_agent(package())
        accepted = await app.runtime.start_run(command(original_agent, "before-update"), CONTEXT)
        original = await app.execution_configuration(accepted.run_id, CONTEXT)
        await app.update_runtime(runtime(tmp_path, file_limit=2048, duration=12))
        updated_agent = await app.load_agent(package())
        assert updated_agent.composition_hash != original_agent.composition_hash
        assert await app.execution_configuration(accepted.run_id, CONTEXT) == original
        result, _ = await run(app, updated_agent, "after-update")
        assert result.state.value == "completed", result
        current = await app.execution_configuration(result.run_id, CONTEXT)
        assert current.policy["filesystem"]["max_file_bytes"] == 2048
        assert current.policy["process"]["max_wall_time_seconds"] == 12
        assert (await app.agent_for_run(accepted.run_id, CONTEXT)).composition_hash == original_agent.composition_hash
        with pytest.raises(ValueError, match="App identity"):
            await app.update_runtime(runtime(tmp_path / "different-database"))
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_snapshot_used_after_restart_and_changed_defaults(tmp_path):
    app = await build(tmp_path, ScriptedModelProvider(()))
    first = await app.load_agent(package())
    pending = await app.runtime.start_run(command(first, "pending"), CONTEXT)
    original = await app.execution_configuration(pending.run_id, CONTEXT)
    await app.close()
    reopened = await build(tmp_path, ScriptedModelProvider((response(), response())),
                           config=runtime(tmp_path, file_limit=1024, duration=2))
    try:
        # Historical runtime selection belongs to the saved Agent revision.
        # New process defaults must not be substituted into its resource binding.
        await reopened.load_agent(package())
        old_agent = await reopened.agent_for_run(pending.run_id, CONTEXT)
        assert old_agent.composition_hash == first.composition_hash
        async with asyncio.timeout(60):
            while (await reopened.runtime.get_run(pending.run_id)).state.value not in {"completed", "failed"}:
                await asyncio.sleep(.02)
        result = await reopened.runtime.get_run(pending.run_id)
        assert result.state.value == "completed", result
        assert await reopened.execution_configuration(result.run_id, CONTEXT) == original
        facts = await reopened.execution_diagnostics(result.run_id, CONTEXT)
        assert facts["configuration_id"] == original.configuration_id
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_child_inherits_original_and_cannot_expand_authorization(tmp_path):
    app = await build(tmp_path, ScriptedModelProvider(()))
    try:
        agent = await app.load_agent(package())
        parent = await app.runtime.start_run(command(agent, "parent", config=RunConfig(
            execution_policy={"filesystem": {"max_file_bytes": 4096}},
        )), CONTEXT)
        child = await app.runtime.start_run(command(agent, "child", parent=parent.run_id), CONTEXT)
        assert await app.execution_configuration(child.run_id, CONTEXT) == await app.execution_configuration(parent.run_id, CONTEXT)
        stranger = RequestContext(actor=ActorRef(principal_id="stranger", principal_type="user", tenant_id="two"))
        with pytest.raises(SageV2Error):
            await app.runtime.start_run(command(agent, "cross-project", parent=parent.run_id), stranger)
        with pytest.raises(SageV2Error):
            await app.execution_configuration(parent.run_id, stranger)
        with pytest.raises(SageV2Error, match="exceeds authorization"):
            await app.runtime.start_run(command(agent, "wider", parent=parent.run_id, config=RunConfig(
                execution_policy={"filesystem": {"max_file_bytes": 8192}},
            )), CONTEXT)
    finally:
        await app.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership", ["owned", "borrowed"])
async def test_registered_process_ownership_shared_across_agent_revisions(tmp_path, ownership):
    class Closable(ScriptedModelProvider):
        closes = 0

        async def close(self):
            self.closes += 1

    value = Closable(())
    creates = []
    def factory(context, deps):
        creates.append(context)
        return value
    base = registration("test.standard.model", "model.provider", value, ownership=ownership)
    from dataclasses import replace
    selected = replace(base, factory=factory, descriptor=base.descriptor.model_copy(update={
        "supported_scopes": frozenset({ExtensionScope.PROCESS}),
    }))
    config = runtime(tmp_path)
    config = config.model_copy(update={"capabilities": {
        **config.capabilities,
        "model.provider": config.capabilities["model.provider"].model_copy(update={"scope": ExtensionScope.PROCESS}),
    }})
    builder = SAgentBuilder()
    builder.register(selected)
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    app = await builder.build(runtime=config, models=TEST_MODELS)
    try:
        first = await app.load_agent(package())
        changed = package().model_copy(update={"metadata": package().metadata.model_copy(update={"version": "2"})})
        await app.update_agent(agent=first, package=changed)
        assert len(creates) == 1
        assert value.closes == 0
    finally:
        await app.close()
    assert value.closes == (1 if ownership == "owned" else 0)
    await app.close()
    assert value.closes == (1 if ownership == "owned" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership", ["owned", "borrowed"])
async def test_registered_object_creation_failure_rolls_back_only_owned_resources(tmp_path, ownership):
    class Closable(ScriptedModelProvider):
        closes = 0

        async def close(self):
            self.closes += 1

    model = Closable(())
    config = runtime(tmp_path)
    config = config.model_copy(update={"capabilities": {
        **config.capabilities, "tool.selection-policy": CapabilitySelection(plugin="test.failing.selection"),
    }})
    builder = SAgentBuilder()
    from dataclasses import replace
    def fail(context, dependencies):
        raise SageV2Error(RuntimeErrorInfo(code="test.factory_failed", category=ErrorCategory.INTERNAL,
                                          message="selection factory failed"))
    failing = registration("test.failing.selection", "tool.selection-policy", None)
    builder.register(replace(failing, factory=fail))
    builder.register(registration("test.standard.model", "model.provider", model, ownership=ownership))
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    app = await builder.build(runtime=config, models=TEST_MODELS, tenant_id="one")
    try:
        with pytest.raises(SageV2Error, match="selection factory failed"):
            await app.load_agent(package())
        assert model.closes == (1 if ownership == "owned" else 0)
    finally:
        await app.close()


def test_writable_workspace_interpreter_is_rejected_before_launch(tmp_path):
    from sagents.v2.runtime.execution.sandbox.plugins.local.support.interpreter import inspect_isolation_python
    marker = tmp_path / "untrusted-ran"
    executable = tmp_path / "workspace" / "python"
    executable.parent.mkdir()
    executable.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    executable.chmod(0o755)
    with pytest.raises(ValueError, match="outside writable workspaces"):
        inspect_isolation_python(str(executable), forbidden_roots=(executable.parent,))
    assert not marker.exists()
