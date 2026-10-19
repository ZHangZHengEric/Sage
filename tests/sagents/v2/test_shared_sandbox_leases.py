from __future__ import annotations
from tests.sagents.v2.sdk_fixture import build_registered_app

import asyncio
import sys

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
    SandboxState,
)
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT


async def provision(root, *, max_processes=4):
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key, read_paths=(sys.prefix,))
    handle = await provider.provision(
        ResolvedSandboxSpec(
            spec_hash="sha256:shared",
            policy_hash="sha256:shared-policy",
            architecture="native",
            workspace_root=str(root),
            metadata={"host_workspace": str(root)},
            resources=ResourceLimits(require_hard_limits=False),
            filesystem=FileSystemPolicy(
                allowed_operations=frozenset(FileOperation), allowed_roots=(str(root),)
            ),
            process=ProcessPolicy(
                enabled=True,
                max_processes=max_processes,
                max_wall_time_seconds=20,
                allowed_executables=("sh",),
                allow_shell=True,
            ),
        ),
        CONTEXT,
        run_id="parent",
    )
    return provider, issuer, handle


def authorize(issuer, handle, operation, *, path=".", request=None):
    fields = {}
    if request is not None:
        fields = {
            "argv": request.argv,
            "executable": request.argv[0],
            "metadata": {"process_request_digest": request.digest()},
        }
        path = request.cwd
    intent = OperationIntent(
        operation=operation,
        sandbox_id=handle.ref.sandbox_id,
        run_id=handle.ref.owner_run_id,
        tool_call_id="call",
        path=path,
        **fields,
    )
    return {
        "intent": intent,
        "grant": issuer.issue(
            ref=handle.ref, intent=intent, allowed_operations=frozenset({operation})
        ),
    }


@pytest.mark.asyncio
async def test_shared_leases_preserve_identity_authorization_and_survivors(tmp_path):
    provider, issuer, parent = await provision(tmp_path)
    child = await parent.share(run_id="child", context=CONTEXT)
    sibling = await provider.share_run("parent", CONTEXT, run_id="sibling")
    try:
        assert parent.ref.sandbox_id == child.ref.sandbox_id == sibling.ref.sandbox_id
        assert child.ref.owner_run_id == "child"
        assert (
            parent.process.row.boundary
            is child.process.row.boundary
            is sibling.process.row.boundary
        )
        assert parent.process.row.process_slots is child.process.row.process_slots
        signed = authorize(issuer, child, "create", path="value.txt")
        with pytest.raises(PermissionError):
            await parent.filesystem.write_bytes("value.txt", b"wrong owner", **signed)
        await child.filesystem.write_bytes("value.txt", b"shared", **signed)
        assert (
            await parent.filesystem.read_bytes(
                "value.txt", **authorize(issuer, parent, "read", path="value.txt")
            )
            == b"shared"
        )
        await asyncio.gather(child.close(), child.close())
        assert (await child.status()).state == SandboxState.TERMINATED
        assert (
            (await parent.status()).state
            == (await sibling.status()).state
            == SandboxState.READY
        )
        with pytest.raises(SageV2Error, match="lease.*released"):
            await child.filesystem.read_bytes(
                "value.txt", **authorize(issuer, child, "read", path="value.txt")
            )
        await provider.purge_terminated(child.ref)
        with pytest.raises(ValueError, match="already has a lease"):
            await parent.share(run_id="child", context=CONTEXT)
        assert (await parent.status()).state == SandboxState.READY
        await parent.destroy()
        await provider.purge_terminated(parent.ref)
        assert (await sibling.status()).state == SandboxState.READY
        await sibling.filesystem.write_bytes(
            "after-parent.txt",
            b"alive",
            **authorize(issuer, sibling, "create", path="after-parent.txt"),
        )
    finally:
        await child.close()
        await parent.close()
        await sibling.close()
    assert provider._rows[parent.ref.sandbox_id].state == SandboxState.TERMINATED
    await provider.purge_terminated(sibling.ref)
    assert not provider._rows


@pytest.mark.asyncio
async def test_attached_handle_does_not_revoke_lease_until_last_close(tmp_path):
    provider, _, parent = await provision(tmp_path)
    child = await parent.share(run_id="child", context=CONTEXT)
    attached = await provider.attach(child.ref, CONTEXT)
    await child.close()
    assert (await attached.status()).state == SandboxState.READY
    await attached.close()
    assert (await parent.status()).state == SandboxState.READY
    await parent.close()


@pytest.mark.asyncio
async def test_child_cleanup_cancels_only_its_processes(tmp_path):
    provider, issuer, parent = await provision(tmp_path)
    child = await parent.share(run_id="child", context=CONTEXT)
    sibling = await parent.share(run_id="sibling", context=CONTEXT)
    tasks = []
    try:
        for handle in (parent, child, sibling):
            request = ProcessRequest(
                argv=("sh", "-c", "sleep 15"), cwd=str(tmp_path)
            )
            tasks.append(
                asyncio.create_task(
                    handle.process.run(
                        request,
                        **authorize(issuer, handle, "process.run", request=request),
                    )
                )
            )
        async with asyncio.timeout(5):
            while len(parent.process.row.boundary._root_processes) != 3:
                await asyncio.sleep(0.01)
        await child.destroy()
        assert tasks[1].cancelled()
        assert not tasks[0].done() and not tasks[2].done()
        assert len(parent.process.row.boundary._root_processes) == 2
        assert (
            (await parent.status()).state
            == (await sibling.status()).state
            == SandboxState.READY
        )
    finally:
        await asyncio.gather(parent.close(), child.close(), sibling.close())
        await asyncio.gather(*tasks, return_exceptions=True)
    assert provider._rows[parent.ref.sandbox_id].state == SandboxState.TERMINATED


@pytest.mark.asyncio
async def test_standard_builder_team_uses_one_sandbox_and_parent_survives_child(
    tmp_path,
):
    from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
    from sagents.v2.contracts.commands import InputItem, StartRun
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
        ModelToolCall,
    )
    from sagents.v2.package.presets import BuiltinPackageFactory
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    from sagents.v2.runtime.execution import LocalWorkspaceExecutionBindingProvider
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )
    from tests.sagents.v2.model_fixture import TEST_MODELS
    from sagents.v2.composition.defaults import default_runtime

    def step(tool=None, arguments=None, index=0):
        calls = (
            (
                ModelToolCall(
                    tool_call_id=f"call-{index}", name=tool, arguments=arguments
                ),
            )
            if tool
            else ()
        )
        return ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id=f"response-{index}",
                        text="done" if not tool else "",
                        tool_calls=calls,
                        finish_reason="tool_calls" if tool else "stop",
                    ),
                ),
            )
        )

    parent_model = ScriptedModelProvider(
        (
            step(
                "sys_team_delegate_task",
                {"tasks": [{"agent_id": "worker", "content": "write shared.txt"}]},
                1,
            ),
            step("file_read", {"file_path": "shared.txt"}, 2),
            step(index=3),
        )
    )
    child_model = ScriptedModelProvider(
        (
            step(
                "file_write", {"file_path": "shared.txt", "content": "child result"}, 4
            ),
            step(index=5),
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bindings = LocalWorkspaceExecutionBindingProvider(workspace, process_enabled=False)
    runtime_config = default_runtime(tmp_path / "sessions")
    runtime_config = runtime_config.model_copy(
        update={
            "capabilities": {
                **runtime_config.capabilities,
                "tool.catalog": CapabilitySelection(plugin="sage.tool.official"),
                "agent.continuation-policy": CapabilitySelection(
                    plugin="sage.agent.continuation.deterministic"
                ),
                "tool.selection-policy": CapabilitySelection(
                    plugin="sage.tool-selection.direct"
                ),
            }
        }
    )
    app = await (
        build_registered_app(tmp_path / 'sessions', models=TEST_MODELS, model_factory=lambda context, deps: parent_model if context.agent_configuration['execution_agent_id'] == 'assistant' else child_model, runtime=runtime_config, providers={'execution.binding': bindings, 'agent.tool-policy': DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)})
    )
    try:
        child_package = BuiltinPackageFactory.create(
            "assistant", package_id="shared.worker"
        )
        child_package = child_package.model_copy(
            update={
                "agents": {
                    "assistant": child_package.agents["assistant"].model_copy(
                        update={"tools": ("file_write",)}
                    )
                },
                "runtime": child_package.runtime.model_copy(
                    update={
                        "capabilities": {
                            "tool.catalog": CapabilitySelection(
                                plugin="sage.tool.official"
                            )
                        }
                    }
                ),
            }
        )
        worker = await app.load_agent(child_package)
        parent_package = BuiltinPackageFactory.create(
            "assistant", package_id="shared.parent"
        )
        parent_package = parent_package.model_copy(
            update={
                "agents": {
                    "assistant": parent_package.agents["assistant"].model_copy(
                        update={
                            "mode": "team",
                            "subagents": ("worker",),
                            "tools": ("file_read",),
                        }
                    )
                },
                "runtime": parent_package.runtime.model_copy(
                    update={
                        "capabilities": {
                            "tool.catalog": CapabilitySelection(
                                plugin="sage.tool.official"
                            )
                        }
                    }
                ),
            }
        )
        team = await app.load_agent(parent_package, subagents={"worker": worker})
        stream = await app.entrypoint().run_stream(
            StartRun(
                agent_id=team.id,
                resolved_spec_hash=team.composition_hash,
                input=(
                    InputItem(
                        role="user", content=(TextBlock(text="delegate then read"),)
                    ),
                ),
                idempotency_key="shared-team",
            ),
            CONTEXT,
            agent=team,
        )
        result = await stream.wait()
        assert result.state == RunState.COMPLETED
        assert len(parent_model.requests) == 3
        assert len(child_model.requests) == 2
        assert (workspace / "shared.txt").read_text() == "child result"
        assert len(bindings.sandbox_provider._rows) == 1
        resource = next(iter(bindings.sandbox_provider._rows.values()))
        assert len(resource.members) == 2
        assert all(member.lease_terminated for member in resource.members.values())
        assert resource.state == SandboxState.TERMINATED
    finally:
        await app.close()
        await bindings.close()


@pytest.mark.asyncio
async def test_closing_queued_member_never_runs_its_command(tmp_path):
    provider, issuer, parent = await provision(tmp_path, max_processes=1)
    child = await parent.share(run_id="queued-child", context=CONTEXT)
    tasks = []
    try:
        parent_request = ProcessRequest(
            argv=("sh", "-c", "sleep 15"), cwd=str(tmp_path)
        )
        tasks.append(
            asyncio.create_task(
                parent.process.run(
                    parent_request,
                    **authorize(issuer, parent, "process.run", request=parent_request),
                )
            )
        )
        async with asyncio.timeout(5):
            while not parent.process.row.boundary._root_processes:
                await asyncio.sleep(0.01)
        request = ProcessRequest(
            argv=(
                "sh",
                "-c",
                ": > must-not-exist",
            ),
            cwd=str(tmp_path),
        )
        tasks.append(
            asyncio.create_task(
                child.process.run(
                    request, **authorize(issuer, child, "process.run", request=request)
                )
            )
        )
        async with asyncio.timeout(5):
            while not child.process.row.queued_tasks:
                await asyncio.sleep(0.01)
        await child.close()
        assert tasks[1].cancelled()
        assert not tasks[0].done()
        assert not (tmp_path / "must-not-exist").exists()
    finally:
        await asyncio.gather(parent.close(), child.close())
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_last_lease_cleanup_can_retry_without_resurrecting_authorization(
    tmp_path, monkeypatch
):
    provider, issuer, parent = await provision(tmp_path)
    original = parent.process.row.boundary.terminate
    attempts = []

    async def fail_once():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient cleanup failure")
        await original()

    monkeypatch.setattr(parent.process.row.boundary, "terminate", fail_once)
    with pytest.raises(RuntimeError, match="transient cleanup failure"):
        await parent.close()
    with pytest.raises(SageV2Error, match="lease.*released"):
        await parent.filesystem.read_bytes(
            "x", **authorize(issuer, parent, "read", path="x")
        )
    await parent.close()
    assert len(attempts) == 2
    assert provider._rows[parent.ref.sandbox_id].state == SandboxState.TERMINATED


@pytest.mark.asyncio
async def test_release_idempotency_is_scoped_to_each_member(tmp_path):
    from sagents.v2.runtime.execution.sandbox import (
        SandboxReleaseRequest,
        SandboxReleaseDisposition,
    )

    provider, _, parent = await provision(tmp_path)
    child = await parent.share(run_id="child", context=CONTEXT)
    try:
        receipts = []
        for handle in (parent, child):
            request = SandboxReleaseRequest(
                ref=handle.ref,
                disposition=SandboxReleaseDisposition.TERMINATE,
                reason="finished",
                expected_revision=(await handle.status()).revision,
                idempotency_key="same-member-final-key",
            )
            receipt = await provider.release(request, CONTEXT)
            receipts.append(receipt)
            duplicate = await provider.release(request, CONTEXT)
            assert duplicate.duplicate
            assert receipt.ref.owner_run_id == handle.ref.owner_run_id
        assert not receipts[0].compute_released
        assert receipts[1].compute_released
    finally:
        await parent.close()
        await child.close()


@pytest.mark.asyncio
async def test_intermediate_team_lease_close_preserves_grandchild_and_sibling(tmp_path):
    provider, issuer, root = await provision(tmp_path)
    director = await root.share(run_id="director", context=CONTEXT)
    maker = await director.share(run_id="maker", context=CONTEXT)
    sibling = await root.share(run_id="sibling", context=CONTEXT)
    try:
        await director.close()
        assert (await director.status()).state == SandboxState.TERMINATED
        for handle in (root, maker, sibling):
            assert (await handle.status()).state == SandboxState.READY
            await handle.filesystem.write_bytes(
                handle.ref.owner_run_id + ".txt", b"alive",
                **authorize(issuer, handle, "create", path=handle.ref.owner_run_id + ".txt"),
            )
        assert len({h.ref.sandbox_id for h in (root, director, maker, sibling)}) == 1
    finally:
        await asyncio.gather(root.close(), director.close(), maker.close(), sibling.close())
    assert provider._rows[root.ref.sandbox_id].state == SandboxState.TERMINATED
