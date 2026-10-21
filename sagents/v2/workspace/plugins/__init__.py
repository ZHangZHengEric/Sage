"""Workspace plugins exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.workspace.plugins.bare import BareWorkspaceInitializer as BareWorkspaceInitializer
    from sagents.v2.workspace.plugins.claw import ClawWorkspaceInitializer as ClawWorkspaceInitializer


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "BareWorkspaceInitializer": (
        "sagents.v2.workspace.plugins.bare",
        "BareWorkspaceInitializer",
    ),
    "ClawWorkspaceInitializer": (
        "sagents.v2.workspace.plugins.claw",
        "ClawWorkspaceInitializer",
    ),
}

__all__ = [
    "BareWorkspaceInitializer",
    "ClawWorkspaceInitializer",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
