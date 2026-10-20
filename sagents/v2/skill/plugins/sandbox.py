"""Materialize standard Skill bundles through the Run's signed sandbox grants."""

from __future__ import annotations

from sagents.v2.runtime.execution.sandbox import FileOperation
from sagents.v2.skill.workspace import SandboxSkillWorkspaceBase


class SandboxSkillWorkspace(SandboxSkillWorkspaceBase):
    async def materialize(self, bundle, *, run_id, destination):
        destination = self.sandbox.filesystem.normalize_path(destination)
        async with self._lock:
            missing = []
            for relative, content in bundle.files.items():
                path = destination.rstrip("/") + "/" + relative
                try:
                    current = await self.sandbox.filesystem.read_bytes(
                        path, **self._authorization(FileOperation.READ, path, run_id),
                    )
                except FileNotFoundError:
                    missing.append((path, content))
                else:
                    if current != content:
                        raise PermissionError(f"skill workspace conflicts with {path!r}")
            for path, content in missing:
                try:
                    await self.sandbox.filesystem.write_bytes(
                        path, content, overwrite=False,
                        **self._authorization(FileOperation.CREATE, path, run_id),
                    )
                except FileExistsError:
                    # A sibling Run can materialize the same immutable bundle
                    # between our read and create. Never overwrite its bytes.
                    current = await self.sandbox.filesystem.read_bytes(
                        path, **self._authorization(FileOperation.READ, path, run_id),
                    )
                    if current != content:
                        raise PermissionError(f"skill workspace conflicts with {path!r}") from None
        return destination
