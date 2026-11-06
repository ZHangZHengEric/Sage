from __future__ import annotations

from types import SimpleNamespace

import pytest

from sagents.v2.contracts.commands import StartRun, RunConfig
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.binding import ExecutionBindingRequest
from sagents.v2.runtime.execution.plugins.cube_binding import (
    CubeExecutionBindingConfig,
    CubeExecutionBindingProvider,
    CubeExecutionPolicy,
)
from sagents.v2.runtime.execution.sandbox import SandboxGrantIssuer
from sagents.v2.runtime.execution.sandbox.plugins.cube import CubeVolumeSandboxProvider


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="alice", tenant_id="alice", principal_type=PrincipalType.USER
    )
)


def test_cube_process_cannot_bypass_partial_file_permissions():
    with pytest.raises(ValueError, match="full operations or read/list"):
        CubeExecutionPolicy().narrow(
            {"filesystem": {"allowed_operations": ["read", "list", "create"]}}
        )


def test_cube_policy_cannot_remove_the_executable_allowlist():
    policy = CubeExecutionPolicy()
    with pytest.raises(ValueError, match="executable"):
        policy.narrow({"process": {"allowed_executables": []}})


class CubeClient:
    def __init__(self):
        self.created = []

    def create_sandbox(self, name, **kwargs):
        sandbox = SimpleNamespace(sandbox_id=f"cube_{len(self.created)}", killed=False)

        def kill():
            sandbox.killed = True

        sandbox.kill = kill
        self.created.append((name, sandbox, kwargs))
        return sandbox


def provider():
    issuer = SandboxGrantIssuer()
    client = CubeClient()
    sandbox = CubeVolumeSandboxProvider(issuer.verification_key, client=client)
    config = CubeExecutionBindingConfig(
        workspace_user_id="alice",
        agent_id="agent",
        api_url="http://cube",
        template_id="python",
        proxy_node_ip="cube",
    )
    return CubeExecutionBindingProvider(
        config, sandbox_provider=sandbox, issuer=issuer
    ), client


def command(key="root", **kwargs):
    return StartRun(
        agent_id="agent",
        idempotency_key=key,
        input=(),
        resolved_spec_hash="sha256:test",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_cube_binding_freezes_remote_configuration_without_provisioning():
    binding, client = provider()
    accepted = await binding.accept_configuration(command(), context=CONTEXT)
    snapshot = accepted.config.execution_snapshot
    assert snapshot.provider_id == "sage.sandbox.cube-volume"
    assert snapshot.workspace_root == "/workspace"
    assert not client.created
    run = await binding.acquire(
        ExecutionBindingRequest(
            run_id="run", agent_id="agent", context=CONTEXT, configuration=snapshot
        )
    )
    assert run.host_workspace is None
    assert client.created[0][0].startswith("sage-")
    await run.close()
    assert client.created[0][1].killed
    await binding.close()


@pytest.mark.asyncio
async def test_cube_runs_share_persistent_volume_but_own_their_compute():
    binding, client = provider()
    accepted = await binding.accept_configuration(command(), context=CONTEXT)
    root = await binding.acquire(
        ExecutionBindingRequest(
            run_id="root",
            agent_id="agent",
            context=CONTEXT,
            configuration=accepted.config.execution_snapshot,
        )
    )
    accepted_child = await binding.accept_configuration(
        command("child", parent_run_id="root"), context=CONTEXT, parent_command=accepted
    )
    child = await binding.acquire(
        ExecutionBindingRequest(
            run_id="child",
            agent_id="worker",
            parent_run_id="root",
            context=CONTEXT,
            configuration=accepted_child.config.execution_snapshot,
        )
    )
    assert client.created[0][0] == client.created[1][0]
    await child.close()
    assert client.created[1][1].killed and not client.created[0][1].killed
    await root.close()


@pytest.mark.asyncio
async def test_cube_same_run_resource_handles_release_compute_only_once():
    binding, client = provider()
    accepted = await binding.accept_configuration(command(), context=CONTEXT)
    request = ExecutionBindingRequest(
        run_id="root",
        agent_id="agent",
        context=CONTEXT,
        configuration=accepted.config.execution_snapshot,
    )
    original = await binding.acquire(request)
    borrowed = await binding.acquire(request)
    assert len(client.created) == 1
    await borrowed.close()
    assert not client.created[0][1].killed
    await original.close()
    assert client.created[0][1].killed


@pytest.mark.asyncio
async def test_cube_provider_cleans_other_compute_when_one_vm_cannot_be_released():
    binding, client = provider()
    accepted = await binding.accept_configuration(command(), context=CONTEXT)
    for run_id in ("first", "second"):
        await binding.acquire(
            ExecutionBindingRequest(
                run_id=run_id,
                agent_id="agent",
                context=CONTEXT,
                configuration=accepted.config.execution_snapshot,
            )
        )
    first = client.created[0][1]
    original = first.kill

    def unavailable():
        raise RuntimeError("Cube unavailable")

    first.kill = unavailable
    with pytest.raises(RuntimeError):
        await binding.sandbox_provider.close()
    assert client.created[1][1].killed
    first.kill = original
    await binding.close()


@pytest.mark.asyncio
async def test_cube_old_run_cannot_be_silently_replayed_in_a_new_process():
    old, _ = provider()
    accepted = await old.accept_configuration(command(), context=CONTEXT)
    restarted, client = provider()
    with pytest.raises(SageV2Error, match="configuration"):
        await restarted.acquire(
            ExecutionBindingRequest(
                run_id="old",
                agent_id="agent",
                context=CONTEXT,
                configuration=accepted.config.execution_snapshot,
            )
        )
    assert not client.created
    new = await restarted.accept_configuration(command("new"), context=CONTEXT)
    run = await restarted.acquire(
        ExecutionBindingRequest(
            run_id="new",
            agent_id="agent",
            context=CONTEXT,
            configuration=new.config.execution_snapshot,
        )
    )
    await run.close()


@pytest.mark.asyncio
async def test_cube_binding_rejects_expanded_policy_and_changed_backend():
    binding, _ = provider()
    with pytest.raises(SageV2Error, match="8 MiB|authorization"):
        await binding.accept_configuration(
            command(
                config=RunConfig(
                    execution_policy={"filesystem": {"max_file_bytes": 32 << 20}}
                )
            ),
            context=CONTEXT,
        )
    accepted = await binding.accept_configuration(command(), context=CONTEXT)
    other, _ = provider()
    other.config = other.config.model_copy(update={"template_id": "different"})
    with pytest.raises(SageV2Error, match="configuration"):
        await other.acquire(
            ExecutionBindingRequest(
                run_id="run",
                agent_id="agent",
                context=CONTEXT,
                configuration=accepted.config.execution_snapshot,
            )
        )


@pytest.mark.asyncio
async def test_cube_private_children_and_readonly_mounts_preserve_parent_workspace():
    binding, client = provider()
    parent = await binding.accept_configuration(command(), context=CONTEXT)
    child = await binding.accept_configuration(
        command(
            "private",
            parent_run_id="parent",
            config=RunConfig(metadata={"workspace_policy": "private_child"}),
        ),
        context=CONTEXT,
        parent_command=parent,
    )
    readonly = await binding.accept_configuration(
        command(
            "read",
            parent_run_id="parent",
            config=RunConfig(metadata={"workspace_policy": "read_only_parent"}),
        ),
        context=CONTEXT,
        parent_command=parent,
    )
    for run_id, accepted in (
        ("parent", parent),
        ("private", child),
        ("read", readonly),
    ):
        await binding.acquire(
            ExecutionBindingRequest(
                run_id=run_id,
                agent_id="agent",
                context=CONTEXT,
                parent_run_id=None if run_id == "parent" else "parent",
                workspace_policy=accepted.config.execution_snapshot.workspace_policy,
                configuration=accepted.config.execution_snapshot,
            )
        )
    assert client.created[0][0] != client.created[1][0]
    assert client.created[0][0] == client.created[2][0]
    assert client.created[2][2]["read_only"] is True
    await binding.close()
    assert all(row[1].killed for row in client.created)
