"""Replaceable Agent Workspace initialization providers."""

from sagents.v2.workspace.contracts import WorkspaceInitializer
from sagents.v2.workspace.plugins import (
    BareWorkspaceInitializer,
    ClawWorkspaceInitializer,
)

__all__ = [
    "BareWorkspaceInitializer",
    "ClawWorkspaceInitializer",
    "WorkspaceInitializer",
]
