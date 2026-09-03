"""Sandbox contracts and lazily loaded implementations."""

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
    "SandboxGrantIssuer": (
        "sagents.v2.runtime.execution.sandbox.plugins.ephemeral",
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
    "NetworkMode",
    "NetworkPolicy",
    "NetworkRequest",
    "NetworkResult",
    "OperationIntent",
    "ProcessPolicy",
    "ProcessRequest",
    "ProcessResult",
    "ResolvedSandboxSpec",
    "SandboxCapabilities",
    "SandboxCheckpointRef",
    "SandboxDurability",
    "SandboxFileSystem",
    "SandboxGrant",
    "SandboxGrantIssuer",
    "SandboxHandle",
    "SandboxNetworkRuntime",
    "SandboxProcessRuntime",
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
