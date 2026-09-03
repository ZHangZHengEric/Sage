"""Official Sandbox providers exposed without eager sibling imports."""

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
    "SandboxGrantIssuer": (
        "sagents.v2.runtime.execution.sandbox.plugins.ephemeral",
        "SandboxGrantIssuer",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
