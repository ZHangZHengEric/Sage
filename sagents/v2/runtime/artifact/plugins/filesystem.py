"""Immutable binary snapshots published atomically in a host-owned directory."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import tempfile
from pathlib import Path

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


class FilesystemArtifactStore:
    plugin_id = "sage.artifact.filesystem"
    name = "Filesystem ArtifactStore"
    description = "Immutable binary artifact files with local restart durability."

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def capabilities(self):
        return {"durable_across_process_restart": True, "shared_across_processes": True}

    def _path(self, artifact_id: str) -> Path:
        return self.root / (
            hashlib.sha256(artifact_id.encode()).hexdigest() + ".artifact"
        )

    def _sync_root(self):
        if os.name == "posix":
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _read(self, artifact_id):
        try:
            descriptor = os.open(
                self._path(artifact_id), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(descriptor, "rb") as stream:
                return stream.read()
        except FileNotFoundError as exc:
            raise self._error("artifact.not_found", artifact_id) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise self._error("artifact.integrity_failed", artifact_id) from exc
            raise

    async def put(self, *, artifact_id, media_type, content, metadata=None):
        payload = b"".join([chunk async for chunk in content])
        reference = ArtifactRef(
            artifact_id=artifact_id,
            media_type=media_type,
            size_bytes=len(payload),
            digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            metadata=metadata or {},
        )
        header = json.dumps(reference.model_dump(mode="json"), sort_keys=True).encode()
        snapshot = header + b"\n" + payload

        def save():
            descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.root)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(snapshot)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Publishing a hard link is atomic and never replaces an existing
                # snapshot. Readers cannot observe partially written envelopes.
                try:
                    os.link(temporary, self._path(artifact_id))
                except FileExistsError:
                    if self._read(artifact_id) != snapshot:
                        raise self._error(
                            "artifact.id_conflict", artifact_id, ErrorCategory.CONFLICT
                        )
                self._sync_root()
            finally:
                temporary.unlink(missing_ok=True)
            return reference

        return await asyncio.to_thread(save)

    async def get(self, artifact_id):
        def load():
            snapshot = self._read(artifact_id)
            header, separator, payload = snapshot.partition(b"\n")
            try:
                reference = ArtifactRef.model_validate_json(header)
            except ValueError as exc:
                raise self._error("artifact.integrity_failed", artifact_id) from exc
            if (
                not separator
                or reference.artifact_id != artifact_id
                or reference.size_bytes != len(payload)
                or reference.digest != f"sha256:{hashlib.sha256(payload).hexdigest()}"
            ):
                raise self._error("artifact.integrity_failed", artifact_id)
            return reference, payload

        reference, payload = await asyncio.to_thread(load)

        async def stream():
            yield payload

        return reference, stream()

    async def delete(self, artifact_id):
        def remove():
            try:
                self._path(artifact_id).unlink()
            except FileNotFoundError:
                return False
            self._sync_root()
            return True

        return await asyncio.to_thread(remove)

    @staticmethod
    def _error(code, artifact_id, category=ErrorCategory.VALIDATION):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=f"{code}: {artifact_id!r}",
                safe_to_resume=True,
            )
        )
