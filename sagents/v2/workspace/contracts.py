"""Replaceable Agent Workspace initialization port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class WorkspaceInitializer(Protocol):
    """Prepare a new-version workspace without importing external state."""

    def initialize(self, root: Path) -> tuple[str, ...]: ...
