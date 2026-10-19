"""Materialize standard Skill bundles through the Run's signed sandbox grants."""

from __future__ import annotations

import asyncio

from sagents.v2.runtime.execution.sandbox import FileOperation, OperationIntent


class SandboxSkillWorkspace:
    def __init__(self, sandbox, issuer):
        self.sandbox, self.issuer = sandbox, issuer
        self._lock = asyncio.Lock()
        self._sequence = 0

    def _authorization(self, operation, path, run_id):
        self._sequence += 1
        intent = OperationIntent(
            operation=operation.value, run_id=run_id,
            sandbox_id=self.sandbox.ref.sandbox_id,
            tool_call_id=f"skill_materialize_{self._sequence}", path=path,
        )
        return {"intent": intent, "grant": self.issuer.issue(
            ref=self.sandbox.ref, intent=intent,
            allowed_operations=frozenset({operation.value}),
        )}

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
