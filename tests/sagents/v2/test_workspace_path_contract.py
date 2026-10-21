"""Host-selected path contracts must survive admission, children and recovery."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.sandbox.plugins.local import LocalWorkspaceSandboxProvider

from sagents.v2.contracts.items import JsonBlock

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution import ExecutionBindingRequest
from sagents.v2.runtime.execution.plugins import local_binding
from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider
from sagents.v2.runtime.execution.sandbox import SandboxGrantIssuer
from tests.sagents.v2.test_local_workspace_sandbox_matrix import CONTEXT


@pytest.mark.parametrize("platform,alias,expected", [
    ("linux", None, None), ("linux", "/workspace", "/workspace"),
    ("darwin", None, None), ("darwin", "/workspace", None),
])
def test_host_selects_native_or_mapped_workspace(tmp_path, monkeypatch, platform, alias, expected):
    monkeypatch.setattr(local_binding, "sys", SimpleNamespace(platform=platform))
    provider = LocalWorkspaceExecutionBindingProvider(tmp_path, workspace_alias=alias)
    spec = provider.sandbox_spec()
    assert spec.workspace_root == (expected or str(tmp_path))
    assert spec.filesystem.allowed_roots == (spec.workspace_root,)
    assert spec.metadata["host_workspace"] == str(tmp_path)


async def test_mapping_is_frozen_and_children_use_host_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(local_binding, "sys", SimpleNamespace(platform="linux"))
    interpreter = {"executable": "/trusted/python"}
    monkeypatch.setattr(local_binding, "inspect_isolation_python", lambda *a, **kw: interpreter)
    handles = []
    async def provision(spec, context, *, run_id):
        handle = SimpleNamespace(
            ref=SimpleNamespace(owner_run_id=run_id, model_dump=lambda **kw: {}),
            filesystem=SimpleNamespace(row=SimpleNamespace(root=Path(spec.metadata["host_workspace"]))),
            close=AsyncMock(),
        )
        handles.append(handle)
        return handle
    sandbox = SimpleNamespace(
        provider_id="local", isolation_python="/trusted/python", command_path="/usr/bin", read_paths=(),
        provision=AsyncMock(side_effect=provision),
        capabilities=AsyncMock(return_value=SimpleNamespace(model_dump=lambda **kw: {})),
    )
    provider = LocalWorkspaceExecutionBindingProvider(tmp_path / "tenant/workspace", workspace_alias="/workspace",
                                                      sandbox_provider=cast('LocalWorkspaceSandboxProvider | None', sandbox), issuer=SandboxGrantIssuer())
    command = StartRun(agent_id="agent", resolved_spec_hash="sha256:test", idempotency_key="mapping", input=())
    accepted = await provider.accept_configuration(command, context=CONTEXT)
    snapshot = accepted.config.execution_snapshot
    assert snapshot.workspace_root == str(provider.workspace)  # Durable host identity.
    assert snapshot.tool_environment["workspace_alias"] == "/workspace"
    parent = await provider.acquire(ExecutionBindingRequest(run_id="parent", agent_id="agent", context=CONTEXT, configuration=snapshot))
    assert parent.workspace_root == "/workspace"
    assert parent.host_workspace == str(provider.workspace)
    for relationship in ("read_only_parent", "private_child"):
        child_command = command.model_copy(update={"config": command.config.model_copy(update={
            "metadata": {"workspace_policy": relationship},
        })})
        child = await provider.accept_configuration(child_command, context=CONTEXT, parent_command=accepted)
        binding = await provider.acquire(ExecutionBindingRequest(
            run_id=relationship, agent_id="agent", parent_run_id="parent", context=CONTEXT,
            workspace_policy=relationship, configuration=child.config.execution_snapshot,
        ))
        assert binding.workspace_root == "/workspace"
        spec = sandbox.provision.call_args.args[0]
        assert spec.workspace_root == "/workspace"
        if relationship == "read_only_parent":
            assert spec.metadata["host_workspace"] == str(provider.workspace)
            assert binding.host_workspace is None
        else:
            assert Path(spec.metadata["host_workspace"]).parent == provider.private_workspace_root
    native = LocalWorkspaceExecutionBindingProvider(provider.workspace, sandbox_provider=cast('LocalWorkspaceSandboxProvider | None', sandbox))
    with pytest.raises(SageV2Error, match="mapping changed"):
        await native._restore_configuration(snapshot)
    await provider.close()


async def test_shell_pipeline_failure_is_not_hidden_by_tail(tmp_path):
    from tests.sagents.v2.test_official_tool_provider_matrix import (
        plugin_for,
        call,
        CONTEXT as TOOL_CONTEXT,
    )

    plugin = await plugin_for(tmp_path)
    try:
        result = await plugin.executor.execute(call("execute_shell_command", {
            "command": "printf 'checker failed\\n'; (exit 7) | tail -30", "block_until_ms": 5000,
        }), TOOL_CONTEXT)
        receipt = cast(JsonBlock, result.content[0]).value
        assert receipt["success"] is False
        assert receipt["exit_code"] == 7
    finally:
        await plugin.executor.release_run("run_1")
