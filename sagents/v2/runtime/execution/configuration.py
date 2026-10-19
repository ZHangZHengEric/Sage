"""Validated local execution policy; hosts configure data, not a driver."""

from __future__ import annotations

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.runtime.execution.sandbox import (
    FileOperation, FileSystemPolicy, NetworkPolicy, ProcessPolicy, ResourceLimits,
)


DEFAULT_ALLOWED_EXECUTABLES = (
    "git", "rg", "python", "python3", "pytest", "flutter", "dart", "npm",
    "node", "bash", "sh",
)
DEFAULT_ALLOWED_ENV_NAMES = ("PATH", "PYTHONPATH")


class LocalExecutionPolicy(StrictModel):
    """Host authorization ceiling and defaults for newly admitted Runs.

    Workspace roots are assigned by Sage. File/process/resource/network fields
    use the same public policy contracts as sandbox admission.
    """

    filesystem: FileSystemPolicy = Field(default_factory=lambda: FileSystemPolicy(
        allowed_operations=frozenset(FileOperation),
        max_file_bytes=64 * 1024**2,
    ))
    process: ProcessPolicy = Field(default_factory=lambda: ProcessPolicy(
        enabled=True, allowed_executables=DEFAULT_ALLOWED_EXECUTABLES,
        allow_shell=True, allowed_env_names=DEFAULT_ALLOWED_ENV_NAMES,
        max_wall_time_seconds=300, max_output_bytes=4 * 1024**2,
    ))
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits(
        require_hard_limits=False,
    ))
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    @model_validator(mode="after")
    def validate_workspace_policy(self):
        if self.filesystem.allowed_roots != ("/workspace",):
            raise ValueError("workspace roots are assigned by Sage, not execution_policy")
        if self.filesystem.allow_symlinks:
            raise ValueError("local workspaces do not support symlink authorization")
        if self.process.allow_background_jobs:
            raise ValueError("use managed Shell jobs instead of detached processes")
        # The process provider rejects writable launches when protected paths
        # exist. Read-only process execution remains enforceable and file API
        # operations can still use their independently configured permissions.
        if self.process.enabled and self.filesystem.allowed_operations not in {
            frozenset(FileOperation), frozenset({FileOperation.READ, FileOperation.LIST}),
        }:
            raise ValueError("native processes require full operations or read/list only")
        if self.filesystem.allowed_operations <= {FileOperation.READ, FileOperation.LIST}:
            object.__setattr__(self, "process", self.process.model_copy(update={"read_only": True}))
        # An omitted filesystem quota inherits the selected disk quota. Keeping
        # a second fixed default here would silently cap larger media workspaces.
        # An explicitly smaller filesystem quota remains a separate ceiling.
        effective_total = min(
            self.filesystem.max_total_bytes or self.resources.disk_mb * 1024**2,
            self.resources.disk_mb * 1024**2,
        )
        object.__setattr__(self, "filesystem", self.filesystem.model_copy(update={
            "max_total_bytes": effective_total,
        }))
        return self

    def narrow(self, overrides: dict | None) -> LocalExecutionPolicy:
        if not overrides:
            return self.model_copy(deep=True)
        source = self.model_dump(mode="json")
        for key, value in overrides.items():
            if key not in source or not isinstance(value, dict):
                raise ValueError(f"unknown execution policy section: {key}")
            source[key] = {**source[key], **value}
        selected = LocalExecutionPolicy.model_validate(source)
        _require_narrower(self.model_dump(mode="json"), selected.model_dump(mode="json"))
        return selected


def _require_narrower(ceiling: dict, selected: dict) -> None:
    """Fail closed for unknown changes; authorization is never inferred."""
    permissions = {
        "enabled", "allow_shell", "allow_background_jobs", "allow_listen",
        "allow_symlinks",
    }
    requirements = {"read_only", "require_hard_limits", "deny_private_networks"}
    sets = {
        "allowed_operations", "allowed_executables", "allowed_env_names",
        "allowed_hosts", "allowed_ports", "allowed_schemes", "allowed_methods",
        "allowed_request_headers",
    }
    for section, values in ceiling.items():
        for name, upper in values.items():
            lower = selected[section][name]
            valid = lower == upper
            if isinstance(upper, bool):
                if name in permissions:
                    valid = not lower or upper
                elif name in requirements:
                    valid = lower or not upper
            elif name in sets:
                valid = set(lower).issubset(upper)
                # Empty host/port allowlists mean unrestricted in unrestricted mode;
                # don't infer a relaxation through an empty list.
                if name in {"allowed_hosts", "allowed_ports"} and upper and not lower:
                    valid = False
            elif name == "protected_paths":
                valid = set(upper).issubset(lower)
            elif isinstance(upper, (float, int)) or upper is None:
                valid = upper is None or (lower is not None and lower <= upper)
            elif name == "mode" and section == "network":
                valid = lower == upper or lower == "none"
            if not valid:
                raise ValueError(f"execution policy exceeds authorization: {section}.{name}")
