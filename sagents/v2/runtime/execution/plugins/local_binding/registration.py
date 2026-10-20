"""Standard, serializable registration for local Run execution bindings."""

from __future__ import annotations

from typing import Literal
from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
)
from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy


class LocalExecutionBindingConfig(StrictModel):
    workspace: str
    # Linux Server uses a stable mount; native Desktop leaves this unset.
    workspace_alias: Literal["/workspace"] | None = None
    private_workspace_root: str | None = None
    policy: LocalExecutionPolicy = Field(default_factory=LocalExecutionPolicy)
    command_path: str | None = None
    read_paths: tuple[str, ...] = ()
    isolation_python: str | None = None
    child_workspace_policy: Literal["shared_parent", "private_child", "read_only_parent"] = "shared_parent"
    linux_cgroup_root: str | None = None
    linux_quota_mount: str | None = None
    linux_execution_uid: int | None = None
    linux_execution_gid: int | None = None


def local_execution_binding_registration() -> ExtensionRegistration:
    def create(context, dependencies):
        from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider
        from sagents.v2.runtime.execution.sandbox import (
            LocalWorkspaceSandboxProvider,
            SandboxGrantIssuer,
        )

        config = LocalExecutionBindingConfig.model_validate(context.config)
        issuer = SandboxGrantIssuer()
        sandbox = LocalWorkspaceSandboxProvider(
            issuer.verification_key,
            command_path=config.command_path,
            read_paths=config.read_paths,
            isolation_python=config.isolation_python,
            linux_cgroup_root=config.linux_cgroup_root,
            linux_quota_mount=config.linux_quota_mount,
            linux_execution_uid=config.linux_execution_uid,
            linux_execution_gid=config.linux_execution_gid,
        )
        return LocalWorkspaceExecutionBindingProvider(
            config.workspace, issuer=issuer, sandbox_provider=sandbox,
            workspace_alias=config.workspace_alias,
            private_workspace_root=config.private_workspace_root,
            policy=config.policy,
            child_workspace_policy=config.child_workspace_policy,
        )

    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="sage.execution.binding.local-workspace",
            name="Local workspace execution binding",
            description="Run-owned sandbox leases with admitted execution policy.",
            version="1.0.0",
            provides=(CapabilityOffer(capability="execution.binding", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema=LocalExecutionBindingConfig.model_json_schema(),
            built_in=True,
        ),
        factory=create,
        config_model=LocalExecutionBindingConfig,
    )
