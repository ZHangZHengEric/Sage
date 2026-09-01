"""Keep the workspace empty until the Agent or user creates content."""

from __future__ import annotations

from pathlib import Path


class BareWorkspaceInitializer:
    def initialize(self, root: Path) -> tuple[str, ...]:
        root.mkdir(parents=True, exist_ok=True)
        return ()
