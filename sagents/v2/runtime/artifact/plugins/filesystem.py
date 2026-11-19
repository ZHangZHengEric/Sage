"""Immutable binary snapshots published atomically in a host-owned directory."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


_CHUNK_BYTES = 1024 * 1024


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

    def _open(self, artifact_id):
        try:
            descriptor = os.open(
                self._path(artifact_id), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
            return os.fdopen(descriptor, "rb")
        except FileNotFoundError as exc:
            raise self._error("artifact.not_found", artifact_id) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise self._error("artifact.integrity_failed", artifact_id) from exc
            raise

    async def put(self, *, artifact_id, media_type, content, metadata=None):
        # The on-disk header needs the digest and final length. Spool the body
        # to disk so neither concurrent writers nor retries hold whole blobs.
        payload = tempfile.TemporaryFile(dir=self.root)
        try:
            size, digest = 0, hashlib.sha256()
            async for chunk in content:
                await asyncio.to_thread(payload.write, chunk)
                size += len(chunk)
                digest.update(chunk)
            reference = ArtifactRef(
                artifact_id=artifact_id,
                media_type=media_type,
                size_bytes=size,
                digest=f"sha256:{digest.hexdigest()}",
                metadata=metadata or {},
            )
        except BaseException:
            payload.close()
            raise
        return await asyncio.to_thread(self._publish, payload, reference)

    def _publish(self, payload, reference):
        with payload:
            payload.seek(0)
            header = json.dumps(
                reference.model_dump(mode="json"), sort_keys=True
            ).encode()
            descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.root)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(header + b"\n")
                    shutil.copyfileobj(payload, stream, _CHUNK_BYTES)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Hard links publish atomically and never replace a snapshot.
                try:
                    os.link(temporary, self._path(reference.artifact_id))
                except FileExistsError:
                    with (
                        self._open(reference.artifact_id) as existing,
                        temporary.open("rb") as candidate,
                    ):
                        while True:
                            chunk = candidate.read(_CHUNK_BYTES)
                            if existing.read(_CHUNK_BYTES) != chunk:
                                raise self._error(
                                    "artifact.id_conflict",
                                    reference.artifact_id,
                                    ErrorCategory.CONFLICT,
                                )
                            if not chunk:
                                break
                self._sync_root()
            finally:
                temporary.unlink(missing_ok=True)
        return reference

    def _validated_file(self, artifact_id):
        source = self._open(artifact_id)
        try:
            header = source.readline()
            if not header.endswith(b"\n"):
                raise self._error("artifact.integrity_failed", artifact_id)
            try:
                reference = ArtifactRef.model_validate_json(header)
            except ValueError as exc:
                raise self._error("artifact.integrity_failed", artifact_id) from exc
            offset = source.tell()
            size, digest = 0, hashlib.sha256()
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                size += len(chunk)
                digest.update(chunk)
            if (
                reference.artifact_id != artifact_id
                or reference.size_bytes != size
                or reference.digest != f"sha256:{digest.hexdigest()}"
            ):
                raise self._error("artifact.integrity_failed", artifact_id)
            source.seek(offset)
        except BaseException:
            source.close()
            raise
        return reference, source

    async def get(self, artifact_id):
        reference, source = await asyncio.to_thread(self._validated_file, artifact_id)

        async def stream():
            with source:
                # Enter the context before handing the stream to the caller
                # so aclose() also closes a stream that has not been read.
                yield b""
                while chunk := await asyncio.to_thread(source.read, _CHUNK_BYTES):
                    yield chunk

        content = stream()
        await anext(content)
        return reference, content

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
