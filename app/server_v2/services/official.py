"""Desktop Official runtime: local-workspace sandbox + official file/shell tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sagents.v2.contracts.commands import StartRun
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemMode,
    FileSystemPolicy,
    LifecyclePolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxReleaseDisposition,
)
from sagents.v2.runtime.extensions import ExtensionScope, ExtensionScopeContext
from sagents.v2.tool.official import OfficialToolRuntime
from sagents.v2.tool.plugins.official import (
    OfficialToolPlugin,
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


def install_sandbox(service) -> None:
    """One issuer and one local-workspace provider for the process."""

    if getattr(service, "_sandbox_grant_issuer", None) is not None:
        return
    issuer = SandboxGrantIssuer()
    service._sandbox_grant_issuer = issuer
    service._sandbox_provider = LocalWorkspaceSandboxProvider(issuer.verification_key)


def resolve_agent_tools(
    configured: tuple[str, ...] | list[str], *, has_skills: bool
) -> tuple[str, ...]:
    selected = [name for name in configured if str(name).strip()]
    if not selected:
        selected = list(DEFAULT_OFFICIAL_TOOLS)
    if has_skills and "load_skill" not in selected:
        selected.append("load_skill")
    return tuple(selected)


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


def workspace_sandbox_spec(host_workspace: Path) -> ResolvedSandboxSpec:
    root = str(Path(host_workspace).resolve())
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "plugin": LocalWorkspaceSandboxProvider.plugin_id,
                "host_workspace": root,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    digest = f"sha256:{fingerprint}"
    return ResolvedSandboxSpec(
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
        process=ProcessPolicy(
            enabled=True,
            allowed_executables=("bash", "sh", "python", "python3", "rg", "git"),
            allowed_env_names=("PATH", "PYTHONPATH"),
            max_wall_time_seconds=300,
            max_output_bytes=4 * 1024 * 1024,
        ),
        network=NetworkPolicy(),
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.DURABLE_EXTERNAL,
            safe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
            unsafe_pause_behavior=SandboxReleaseDisposition.DETACH,
        ),
        policy_hash=digest,
        metadata={"host_workspace": root},
    )


async def attach_official_tools(service, command: StartRun, *, user_id: str):
    """Provision a host-mapped sandbox and wrap it as OfficialToolPlugin."""

    install_sandbox(service)
    host_workspace = service.paths.workspace_dir(user_id)
    handle = await service._sandbox_provider.provision(
        workspace_sandbox_spec(host_workspace),
        service.request_context(user_id),
        run_id=command.idempotency_key,
    )
    runtime = OfficialToolRuntime(handle, service._sandbox_grant_issuer)
    plugin = OfficialToolPlugin(
        ExtensionScopeContext(
            scope=ExtensionScope.RUN,
            scope_id=command.idempotency_key,
            config={"runtime": runtime},
        )
    )
    return plugin, runtime, handle
