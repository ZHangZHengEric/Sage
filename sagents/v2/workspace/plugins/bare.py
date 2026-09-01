"""Keep the workspace empty until the Agent or user creates content."""

from __future__ import annotations

from pathlib import Path


class BareWorkspaceInitializer:
    plugin_id = "sage.workspace.initializer.bare"

    def initialize(self, root: Path) -> tuple[str, ...]:
        root.mkdir(parents=True, exist_ok=True)
        return ()
