"""Server Official runtime: local-workspace sandbox + official file/shell tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemMode,
    FileSystemPolicy,
    LifecyclePolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    NetworkMode,
    ProcessPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxReleaseDisposition,
)
from sagents.v2.tool.plugins.official import (
    official_tool_categories,
    official_tool_definitions,
)

DEFAULT_OFFICIAL_TOOLS = (
    "file_read",
    "file_write",
    "file_update",
    "apply_patch",
    "list_dir",
    "glob",
    "grep",
    "execute_shell_command",
    "await_shell",
    "kill_shell",
    "todo_write",
    "todo_read",
)


def install_sandbox(execution, settings=None) -> None:
    """One issuer and one local-workspace provider for the process."""

    if execution.sandbox_grant_issuer is not None:
        return
    issuer = SandboxGrantIssuer()
    execution.sandbox_provider = LocalWorkspaceSandboxProvider(
        issuer.verification_key,
        linux_execution_uid=settings.linux_execution_uid if settings else None,
        linux_execution_gid=settings.linux_execution_gid if settings else None,
    )
    execution.sandbox_grant_issuer = issuer


async def provision_workspace(
    execution,
    workspace: Path,
    context,
    *,
    run_id: str,
    network: NetworkPolicy | None = None,
):
    """Map this user's workspace into one Run's sandbox."""

    return await execution.sandbox_provider.provision(
        workspace_sandbox_spec(workspace, network=network), context, run_id=run_id
    )


def default_agent_tools() -> list[str]:
    """Initial Package configuration; execution never expands an empty list."""
    return list(DEFAULT_OFFICIAL_TOOLS)


def official_tool_catalog() -> list[dict[str, object]]:
    defaults = set(DEFAULT_OFFICIAL_TOOLS)
    categories = official_tool_categories()
    return [
        {
            "name": item.name,
            "category": categories.get(item.name, ""),
            "source": "official",
            "default": item.name in defaults,
        }
        for item in official_tool_definitions()
    ]


def workspace_sandbox_spec(
    host_workspace: Path,
    *,
    resources: ResourceLimits | None = None,
    network: NetworkPolicy | None = None,
) -> ResolvedSandboxSpec:
    # Kernel hard limits come from a delegated cgroup subtree and an XFS
    # project mount that an administrator prepares and hands to the provider.
    # This host does not take that configuration, so it never asserts limits it
    # has no way to obtain; the sandbox still isolates, and meters by sampling.
    resources = resources or ResourceLimits(require_hard_limits=False)
    network = network or NetworkPolicy()
    root = str(Path(host_workspace).resolve())
    process = ProcessPolicy(
        enabled=True,
        allow_shell=True,
        allowed_executables=("bash", "sh", "python", "python3", "rg", "git", "node", "sage-frontend-test"),
        allowed_env_names=(
            "PATH", "PYTHONPATH", "NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "FONTCONFIG_FILE",
            "npm_config_offline", "npm_config_update_notifier",
        ),
        max_wall_time_seconds=300,
        max_output_bytes=4 * 1024 * 1024,
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "plugin": LocalWorkspaceSandboxProvider.plugin_id,
                "host_workspace": root,
                "resources": resources.model_dump(mode="json"),
                "process": process.model_dump(mode="json"),
                "network": network.model_dump(mode="json"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    digest = f"sha256:{fingerprint}"
    return ResolvedSandboxSpec(
        resources=resources,
        spec_hash=digest,
        workspace_root="/workspace",
        architecture="native",
        filesystem_mode=FileSystemMode.WORKSPACE,
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset(FileOperation),
            allowed_roots=("/workspace",),
            max_file_bytes=64 * 1024 * 1024,
            max_total_bytes=4 * 1024 * 1024 * 1024,
        ),
        process=process,
        network=network,
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.DURABLE_EXTERNAL,
            safe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
            unsafe_pause_behavior=SandboxReleaseDisposition.DETACH,
        ),
        policy_hash=digest,
        metadata={"host_workspace": root},
    )


def agent_network_policy(sandbox, settings, *, live=None):
    mode = NetworkMode.UNRESTRICTED if (
        sandbox.network == settings.sandbox_network_mode == "unrestricted"
        and (live is None or live.network == "unrestricted")
    ) else NetworkMode.NONE
    return NetworkPolicy(mode=mode, deny_private_networks=mode != NetworkMode.UNRESTRICTED)


class OwnedWorkspaceSandbox:
    """End per-drive compute on suspension too; preserve the user's files."""

    def __init__(self, handle, provider):
        self.handle = handle
        self.provider = provider
        self.closed = False

    async def close(self):
        if self.closed:
            return
        await self.handle.destroy()
        await self.provider.purge_terminated(self.handle.ref)
        self.closed = True


class BoundWorkspaceHandle:
    """Keep provider operations intact; release per-drive compute on close."""

    def __init__(self, handle, provider):
        self._handle = handle
        self._owner = OwnedWorkspaceSandbox(handle, provider)

    def __getattr__(self, name):
        return getattr(self._handle, name)

    async def close(self):
        await self._owner.close()
