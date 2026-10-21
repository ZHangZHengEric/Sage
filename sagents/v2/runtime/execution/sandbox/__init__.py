"""Sandbox contracts and lazily loaded implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.sandbox.plugins.ephemeral import InMemorySandboxProvider as InMemorySandboxProvider
    from sagents.v2.runtime.execution.sandbox.plugins.local import LocalWorkspaceSandboxProvider as LocalWorkspaceSandboxProvider
    from sagents.v2.runtime.execution.sandbox.plugins.cube import CubeVolumeSandboxProvider as CubeVolumeSandboxProvider
    from sagents.v2.runtime.execution.sandbox.grants import SandboxGrantIssuer as SandboxGrantIssuer


from sagents.v2._lazy import exported_names, resolve_export

from sagents.v2.runtime.execution.sandbox.contracts import (
    FileOperation,
    FileSystemMode,
    FileSystemPolicy,
    IsolationLevel,
    LifecyclePolicy,
    NetworkMode,
    NetworkPolicy,
    NetworkRequest,
    NetworkResult,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ProcessResult,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxCapabilities,
    SandboxCheckpointRef,
    SandboxDurability,
    SandboxGrant,
    SandboxRef,
    SandboxReleaseDisposition,
    SandboxReleaseReceipt,
    SandboxReleaseRequest,
    SandboxSnapshot,
    SandboxState,
)
from sagents.v2.runtime.execution.sandbox.provider import (
    SandboxFileSystem,
    SandboxHandle,
    SandboxNetworkRuntime,
    SandboxProcessRuntime,
    SandboxProcessStream,
    SandboxProvider,
)

_LAZY_EXPORTS = {
    "InMemorySandboxProvider": (
        "sagents.v2.runtime.execution.sandbox.plugins.ephemeral",
        "InMemorySandboxProvider",
    ),
    "LocalWorkspaceSandboxProvider": (
        "sagents.v2.runtime.execution.sandbox.plugins.local",
        "LocalWorkspaceSandboxProvider",
    ),
    "CubeVolumeSandboxProvider": (
        "sagents.v2.runtime.execution.sandbox.plugins.cube",
        "CubeVolumeSandboxProvider",
    ),
    "SandboxGrantIssuer": (
        "sagents.v2.runtime.execution.sandbox.grants",
        "SandboxGrantIssuer",
    ),
}

__all__ = [
    "FileOperation",
    "FileSystemMode",
    "FileSystemPolicy",
    "InMemorySandboxProvider",
    "IsolationLevel",
    "LifecyclePolicy",
    "LocalWorkspaceSandboxProvider",
    "CubeVolumeSandboxProvider",
    "NetworkMode",
    "NetworkPolicy",
    "NetworkRequest",
    "NetworkResult",
    "OperationIntent",
    "ProcessPolicy",
    "ProcessRequest",
    "ProcessResult",
    "ResolvedSandboxSpec",
    "ResourceLimits",
    "SandboxCapabilities",
    "SandboxCheckpointRef",
    "SandboxDurability",
    "SandboxFileSystem",
    "SandboxGrant",
    "SandboxGrantIssuer",
    "SandboxHandle",
    "SandboxNetworkRuntime",
    "SandboxProcessRuntime",
    "SandboxProcessStream",
    "SandboxProvider",
    "SandboxRef",
    "SandboxReleaseDisposition",
    "SandboxReleaseReceipt",
    "SandboxReleaseRequest",
    "SandboxSnapshot",
    "SandboxState",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
