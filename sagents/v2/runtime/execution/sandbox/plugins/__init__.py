"""Official Sandbox providers exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.sandbox.plugins.ephemeral import InMemorySandboxProvider as InMemorySandboxProvider
    from sagents.v2.runtime.execution.sandbox.plugins.local import LocalWorkspaceSandboxProvider as LocalWorkspaceSandboxProvider
    from sagents.v2.runtime.execution.sandbox.plugins.cube import CubeVolumeSandboxProvider as CubeVolumeSandboxProvider
    from sagents.v2.runtime.execution.sandbox.grants import SandboxGrantIssuer as SandboxGrantIssuer


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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
    "InMemorySandboxProvider",
    "LocalWorkspaceSandboxProvider",
    "CubeVolumeSandboxProvider",
    "SandboxGrantIssuer",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
