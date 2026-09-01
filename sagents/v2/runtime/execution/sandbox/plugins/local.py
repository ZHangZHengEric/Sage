"""Native local-workspace sandbox provider for trusted Desktop execution.

This provider enforces signed v2 operation grants, path containment, file
limits, argv-only process execution, environment allowlists, timeouts, and
output limits.  It reports `IsolationLevel.NONE` honestly: policy enforcement
is useful, but a subprocess on the host is not an OS sandbox boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import signal
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.runtime.execution.sandbox.contracts import (
    FileOperation,
    FileStat,
    FileSystemMode,
    IsolationLevel,
    NetworkMode,
    ProcessCapabilities,
    ProcessRequest,
    ProcessResult,
    ResolvedSandboxSpec,
    ResourceLimitCapabilities,
    SandboxCapabilities,
    SandboxCheckpointRef,
    SandboxGrant,
    SandboxRef,
    SandboxReleaseDisposition,
    SandboxReleaseReceipt,
    SandboxReleaseRequest,
    SandboxSnapshot,
    SandboxState,
    TerminateMode,
)


def _grant_payload(grant: SandboxGrant) -> bytes:
    return json.dumps(
        grant.model_dump(mode="json", exclude={"signature"}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


@dataclass
class _LocalRow:
    ref: SandboxRef
    spec: ResolvedSandboxSpec
    root: Path
    state: SandboxState
    created_at: object
    updated_at: object
    revision: int = 0
    attached_clients: int = 1
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    process_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(1)
    )


class _LocalFileSystem:
    def __init__(self, provider: "LocalWorkspaceSandboxProvider", row: _LocalRow):
        self.provider = provider
        self.row = row

    def normalize_path(self, path: str) -> str:
        return self.provider._wire_path(self.row, path)

    async def read_bytes(self, path, *, intent, grant):
        candidate = self.provider._authorize(
            self.row, FileOperation.READ, path, intent, grant
        )
        return await asyncio.to_thread(candidate.read_bytes)

    async def write_bytes(self, path, content, *, intent, grant, overwrite=True):
        operation = (
            FileOperation.WRITE
            if self.provider._path(self.row, path).exists()
            else FileOperation.CREATE
        )
        candidate = self.provider._authorize(self.row, operation, path, intent, grant)
        if candidate.exists() and not overwrite:
            raise FileExistsError(path)
        policy = self.row.spec.filesystem
        if policy.max_file_bytes is not None and len(content) > policy.max_file_bytes:
            raise ValueError("file exceeds max_file_bytes")
        async with self.row.mutation_lock:
            previous_size = candidate.stat().st_size if candidate.is_file() else 0
            if policy.max_total_bytes is not None:
                total = await asyncio.to_thread(
                    self.provider._total_file_bytes, self.row
                )
                if total - previous_size + len(content) > policy.max_total_bytes:
                    raise ValueError("workspace exceeds max_total_bytes")
            candidate.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(candidate.write_bytes, bytes(content))
            self.row.revision += 1
            self.row.updated_at = utc_now()
        return self.provider._stat(self.row, candidate)

    async def delete(self, path, *, intent, grant):
        candidate = self.provider._authorize(
            self.row, FileOperation.DELETE, path, intent, grant
        )
        if candidate.is_dir():
            raise IsADirectoryError(path)
        async with self.row.mutation_lock:
            await asyncio.to_thread(candidate.unlink)
            self.row.revision += 1
            self.row.updated_at = utc_now()

    async def stat(self, path, *, intent, grant):
        candidate = self.provider._authorize(
            self.row, FileOperation.READ, path, intent, grant
        )
        return self.provider._stat(self.row, candidate)

    async def list_paths(self, path, *, intent, grant):
        candidate = self.provider._authorize(
            self.row, FileOperation.LIST, path, intent, grant
        )
        if not candidate.is_dir():
            raise NotADirectoryError(path)
        values = []
        for child in sorted(candidate.rglob("*")):
            if child.is_symlink() or not (child.is_file() or child.is_dir()):
                continue
            values.append(self.provider._stat(self.row, child))
        return tuple(values)


class _LocalProcessRuntime:
    _TERMINATE_GRACE_SECONDS = 2.0
    _PIPE_DRAIN_GRACE_SECONDS = 1.0

    def __init__(self, provider: "LocalWorkspaceSandboxProvider", row: _LocalRow):
        self.provider = provider
        self.row = row

    async def run(self, request: ProcessRequest, *, intent, grant) -> ProcessResult:
        self.provider._verify(self.row, "process.run", intent, grant)
        if (
            intent.executable != request.argv[0]
            or intent.argv != request.argv
            or intent.path != request.cwd
        ):
            raise PermissionError("process request does not match the signed intent")
        policy = self.row.spec.process
        if not policy.enabled:
            raise PermissionError("process execution is disabled")
        if policy.read_only:
            # This provider intentionally reports IsolationLevel.NONE.  A
            # command allowlist cannot make a host shell read-only: shell
            # expansion, symlinks, Git helpers, and executable behavior can
            # all reach outside the mapped workspace.  Fail closed instead of
            # advertising a security boundary that this provider cannot
            # enforce. Providers with a real OS sandbox may implement the
            # read-only ProcessPolicy contract themselves.
            raise PermissionError(
                "read-only process execution requires an isolated sandbox"
            )
        executable = request.argv[0]
        if policy.allowed_executables and executable not in policy.allowed_executables:
            raise PermissionError(f"executable {executable!r} is not allowed")
        resolved_executable = shutil.which(executable)
        if resolved_executable is None:
            raise FileNotFoundError(executable)
        cwd = self.provider._path(self.row, request.cwd)
        if not cwd.is_dir():
            raise NotADirectoryError(request.cwd)
        unknown_env = set(request.env) - set(policy.allowed_env_names)
        if unknown_env:
            raise PermissionError(
                f"environment variables are not allowed: {sorted(unknown_env)}"
            )
        timeout = request.timeout_seconds or policy.max_wall_time_seconds
        if policy.max_wall_time_seconds is not None and (
            timeout is None or timeout > policy.max_wall_time_seconds
        ):
            timeout = policy.max_wall_time_seconds
        inherited_env = {
            name: os.environ[name]
            for name in policy.allowed_env_names
            if name in os.environ
        }
        started = time.monotonic()
        async with self.row.process_slots:
            process = await asyncio.create_subprocess_exec(
                resolved_executable,
                *request.argv[1:],
                cwd=cwd,
                env={**inherited_env, **request.env},
                stdin=asyncio.subprocess.PIPE if request.stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Shell commands commonly spawn npm/node/flutter children.  A
                # dedicated POSIX session lets cancellation terminate the full
                # process group instead of only the immediate bash process.
                start_new_session=os.name == "posix",
            )
            stdout_task = asyncio.create_task(
                self._read_bounded(process.stdout, policy.max_output_bytes)
            )
            stderr_task = asyncio.create_task(
                self._read_bounded(process.stderr, policy.max_output_bytes)
            )
            if process.stdin is not None:
                process.stdin.write(request.stdin or b"")
                await process.stdin.drain()
                process.stdin.close()
            timed_out = False
            try:
                try:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                except TimeoutError:
                    timed_out = True
                    await self._terminate_process_tree(process)

                (
                    (stdout, stdout_overflow),
                    (
                        stderr,
                        stderr_overflow,
                    ),
                ) = await self._finish_pipe_readers(process, stdout_task, stderr_task)
            except asyncio.CancelledError:
                # A child that inherited stdout/stderr can otherwise keep the
                # reader tasks and the single process slot alive indefinitely.
                await self._terminate_process_tree(process)
                await self._cancel_pipe_readers(stdout_task, stderr_task)
                raise
        limit = policy.max_output_bytes
        truncated = (
            stdout_overflow or stderr_overflow or len(stdout) + len(stderr) > limit
        )
        stdout = stdout[:limit]
        stderr = stderr[: max(0, limit - len(stdout))]
        return ProcessResult(
            process_id=new_id("process"),
            argv=request.argv,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=time.monotonic() - started,
            truncated=truncated,
        )

    async def _terminate_process_tree(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Terminate the managed process and its POSIX descendants."""

        if os.name != "posix":
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(
                        process.wait(), timeout=self._TERMINATE_GRACE_SECONDS
                    )
                except TimeoutError:
                    process.kill()
                    await process.wait()
            return

        pgid = process.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        deadline = time.monotonic() + self._TERMINATE_GRACE_SECONDS
        while self._process_group_exists(pgid) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        if self._process_group_exists(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        if process.returncode is None:
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=self._PIPE_DRAIN_GRACE_SECONDS
                )
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _finish_pipe_readers(self, process, stdout_task, stderr_task):
        """Drain process output without allowing inherited pipes to hang."""

        readers = (stdout_task, stderr_task)
        _, pending = await asyncio.wait(readers, timeout=self._PIPE_DRAIN_GRACE_SECONDS)
        if pending:
            # The direct process exited but a descendant still owns a pipe.
            # Background jobs are not supported by this sandbox, so reap the
            # remaining process group before releasing the process slot.
            await self._terminate_process_tree(process)
            _, pending = await asyncio.wait(
                readers, timeout=self._PIPE_DRAIN_GRACE_SECONDS
            )
        if pending:
            for reader in pending:
                reader.cancel()
        results = await asyncio.gather(*readers, return_exceptions=True)
        normalized = []
        for result in results:
            if isinstance(result, tuple):
                normalized.append(result)
            else:
                normalized.append((b"", True))
        return tuple(normalized)

    @staticmethod
    async def _cancel_pipe_readers(*readers) -> None:
        for reader in readers:
            if not reader.done():
                reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    async def _read_bounded(stream, limit: int) -> tuple[bytes, bool]:
        """Drain a process pipe while retaining at most ``limit`` bytes."""

        kept = bytearray()
        overflow = False
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                break
            remaining = limit - len(kept)
            if remaining > 0:
                kept.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow = True
        return bytes(kept), overflow


class _NoNetwork:
    async def request(self, request, *, intent, grant):
        raise PermissionError("network access is disabled by local-workspace policy")


class _LocalHandle:
    def __init__(self, provider: "LocalWorkspaceSandboxProvider", row: _LocalRow):
        self.provider = provider
        self.ref = row.ref
        self.filesystem = _LocalFileSystem(provider, row)
        self.process = _LocalProcessRuntime(provider, row)
        self.network = _NoNetwork()
        self._closed = False

    async def status(self):
        return await self.provider.inspect(self.ref)

    async def suspend(self):
        return await self.provider.snapshot(self.ref)

    async def close(self):
        if not self._closed:
            row = self.provider._rows.get(self.ref.sandbox_id)
            if row is not None:
                row.attached_clients = max(0, row.attached_clients - 1)
            self._closed = True
            self.provider._sweep_terminated()

    async def destroy(self):
        await self.provider.terminate(self.ref, TerminateMode.FORCE)
        await self.close()


class LocalWorkspaceSandboxProvider:
    """Grant-enforcing host filesystem/process provider without OS isolation."""

    provider_id = "sage.sandbox.local-workspace"
    provider_version = "3.0.0"

    def __init__(
        self,
        verification_key: bytes,
        *,
        clock: Callable[[], datetime] = utc_now,
        terminal_ttl_seconds: int = 86_400,
        max_retained_terminal_items: int = 1024,
    ) -> None:
        if terminal_ttl_seconds < 1:
            raise ValueError("terminal_ttl_seconds must be positive")
        if max_retained_terminal_items < 0:
            raise ValueError("max_retained_terminal_items must be non-negative")
        self.verification_key = verification_key
        self._clock = clock
        self._terminal_ttl = timedelta(seconds=terminal_ttl_seconds)
        self._max_retained_terminal = max_retained_terminal_items
        self._rows: dict[str, _LocalRow] = {}
        self._used_nonces: dict[str, str] = {}
        self._release_receipts: dict[tuple[str, str], SandboxReleaseReceipt] = {}

    async def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            isolation_level=IsolationLevel.NONE,
            os=os.name,
            architectures=("native",),
            filesystem_modes=frozenset({FileSystemMode.WORKSPACE}),
            network_modes=frozenset({NetworkMode.NONE}),
            process=ProcessCapabilities(
                available=True, supports_argv=True, max_processes=1
            ),
            resources=ResourceLimitCapabilities(wall_time=True),
            supports_background_jobs=False,
            supports_suspend=False,
            supports_snapshot=False,
            supports_reconnect=True,
            supports_secret_injection=False,
            supported_release_dispositions=frozenset(
                {
                    SandboxReleaseDisposition.DETACH,
                    SandboxReleaseDisposition.TERMINATE,
                }
            ),
            supports_terminal_purge=True,
            supports_automatic_terminal_retention=True,
            terminal_ttl_seconds=int(self._terminal_ttl.total_seconds()),
            max_retained_terminal_items=self._max_retained_terminal,
        )

    async def provision(self, spec, context, *, run_id):
        self._sweep_terminated()
        root_value = spec.metadata.get("host_workspace")
        if not isinstance(root_value, str):
            raise ValueError("local-workspace requires metadata.host_workspace")
        root = Path(root_value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("host_workspace must be a directory")
        now = self._clock()
        ref = SandboxRef(
            sandbox_id=new_id("sandbox"),
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            tenant_id=context.actor.tenant_id,
            owner_run_id=run_id,
            spec_hash=spec.spec_hash,
            policy_hash=spec.policy_hash,
        )
        row = _LocalRow(
            ref,
            spec,
            root,
            SandboxState.READY,
            now,
            now,
            process_slots=asyncio.Semaphore(spec.process.max_processes),
        )
        self._rows[ref.sandbox_id] = row
        return _LocalHandle(self, row)

    async def attach(self, ref, context):
        row = self._row(ref)
        if row.state == SandboxState.TERMINATED:
            raise RuntimeError("sandbox is terminated")
        if row.ref.tenant_id != context.actor.tenant_id:
            raise PermissionError("tenant does not own sandbox")
        row.attached_clients += 1
        return _LocalHandle(self, row)

    async def inspect(self, ref):
        row = self._row(ref)
        files = [
            value
            for value in row.root.rglob("*")
            if value.is_file() and not value.is_symlink()
        ]
        return SandboxSnapshot(
            ref=row.ref,
            state=row.state,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
            attached_clients=row.attached_clients,
            file_count=len(files),
            total_file_bytes=sum(value.stat().st_size for value in files),
        )

    async def snapshot(self, ref) -> SandboxCheckpointRef:
        raise RuntimeError("local-workspace does not support snapshots")

    async def restore(self, checkpoint, context):
        raise RuntimeError("local-workspace does not support snapshots")

    async def release(self, request: SandboxReleaseRequest, context):
        key = (request.ref.sandbox_id, request.idempotency_key)
        previous = self._release_receipts.get(key)
        if previous is not None:
            return previous.model_copy(update={"duplicate": True})
        row = self._row(request.ref)
        if row.ref.tenant_id != context.actor.tenant_id:
            raise PermissionError("tenant does not own sandbox")
        if row.revision != request.expected_revision:
            raise RuntimeError("sandbox revision does not match release request")
        if request.disposition == SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE:
            raise RuntimeError("local-workspace does not support snapshot release")
        if request.disposition == SandboxReleaseDisposition.TERMINATE:
            await self.terminate(request.ref, TerminateMode.FORCE)
        receipt = SandboxReleaseReceipt(
            ref=request.ref,
            disposition=request.disposition,
            state=row.state,
            compute_released=row.state == SandboxState.TERMINATED,
            released_at=self._clock(),
        )
        self._release_receipts[key] = receipt
        return receipt

    async def terminate(self, ref, mode):
        del mode
        row = self._row(ref)
        if row.state != SandboxState.TERMINATED:
            row.state = SandboxState.TERMINATED
            row.revision += 1
            row.updated_at = self._clock()
        self._sweep_terminated()

    async def purge_terminated(self, ref) -> None:
        row = self._row(ref)
        if row.state != SandboxState.TERMINATED or row.attached_clients != 0:
            raise RuntimeError("only detached terminated sandboxes can be purged")
        self._purge_row(ref.sandbox_id)

    def _sweep_terminated(self) -> int:
        terminal = sorted(
            (
                row
                for row in self._rows.values()
                if row.state == SandboxState.TERMINATED
                and row.attached_clients == 0
            ),
            key=lambda row: (row.updated_at, row.ref.sandbox_id),
        )
        now = self._clock()
        purge_ids = {
            row.ref.sandbox_id
            for row in terminal
            if now - row.updated_at >= self._terminal_ttl
        }
        retained = [row for row in terminal if row.ref.sandbox_id not in purge_ids]
        while len(retained) > self._max_retained_terminal:
            purge_ids.add(retained.pop(0).ref.sandbox_id)
        for sandbox_id in purge_ids:
            self._purge_row(sandbox_id)
        return len(purge_ids)

    def _purge_row(self, sandbox_id: str) -> None:
        # Local workspace contents belong to the host. Retention removes only
        # kernel metadata and consumed grant nonces.
        self._rows.pop(sandbox_id, None)
        self._used_nonces = {
            nonce: owner_sandbox_id
            for nonce, owner_sandbox_id in self._used_nonces.items()
            if owner_sandbox_id != sandbox_id
        }
        self._release_receipts = {
            key: value
            for key, value in self._release_receipts.items()
            if key[0] != sandbox_id
        }

    def _row(self, ref):
        row = self._rows.get(ref.sandbox_id)
        if row is None or row.ref != ref:
            raise ValueError("sandbox reference is unknown")
        return row

    def _path(self, row: _LocalRow, path: str) -> Path:
        relative = path
        if relative == row.spec.workspace_root:
            candidate = row.root
        elif relative.startswith(row.spec.workspace_root.rstrip("/") + "/"):
            relative = relative[len(row.spec.workspace_root.rstrip("/")) + 1 :]
            candidate = (row.root / relative).resolve()
        elif Path(relative).is_absolute():
            candidate = Path(relative).expanduser().resolve()
        else:
            candidate = (row.root / relative).resolve()
        if candidate != row.root and row.root not in candidate.parents:
            raise PermissionError("path is outside the workspace")
        allowed = False
        for configured_root in row.spec.filesystem.allowed_roots:
            policy_relative = configured_root
            if policy_relative == row.spec.workspace_root:
                policy_relative = "."
            elif policy_relative.startswith(row.spec.workspace_root.rstrip("/") + "/"):
                policy_relative = policy_relative[
                    len(row.spec.workspace_root.rstrip("/")) + 1 :
                ]
            elif Path(policy_relative).is_absolute():
                continue
            policy_root = (row.root / policy_relative).resolve()
            if candidate == policy_root or policy_root in candidate.parents:
                allowed = True
                break
        if not allowed:
            raise PermissionError("path is outside the allowed filesystem roots")
        if not row.spec.filesystem.allow_symlinks:
            current = row.root
            for part in candidate.relative_to(row.root).parts:
                current = current / part
                if current.is_symlink():
                    raise PermissionError("symlinks are not allowed")
        return candidate

    def _wire_path(self, row: _LocalRow, path: str) -> str:
        candidate = self._path(row, path)
        relative = candidate.relative_to(row.root).as_posix()
        return row.spec.workspace_root.rstrip("/") + (
            f"/{relative}" if relative != "." else ""
        )

    def _authorize(self, row, operation, path, intent, grant):
        self._verify(row, operation.value, intent, grant)
        if intent.path != path:
            raise PermissionError("file path does not match the signed intent")
        if operation not in row.spec.filesystem.allowed_operations:
            raise PermissionError(f"file operation {operation.value!r} is not allowed")
        candidate = self._path(row, path)
        if (
            operation in {FileOperation.READ, FileOperation.LIST, FileOperation.DELETE}
            and not candidate.exists()
        ):
            raise FileNotFoundError(path)
        return candidate

    def _verify(self, row, operation, intent, grant):
        signature = hmac.new(
            self.verification_key, _grant_payload(grant), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, grant.signature):
            raise PermissionError("sandbox grant signature is invalid")
        if grant.expires_at < utc_now() or grant.nonce in self._used_nonces:
            raise PermissionError("sandbox grant is expired or already used")
        if row.state != SandboxState.READY:
            raise PermissionError("sandbox is not ready")
        if (
            intent.operation != operation
            or intent.sandbox_id != row.ref.sandbox_id
            or intent.run_id != row.ref.owner_run_id
            or grant.run_id != intent.run_id
            or grant.tool_call_id != intent.tool_call_id
            or grant.sandbox_id != row.ref.sandbox_id
            or grant.spec_hash != row.ref.spec_hash
            or grant.policy_hash != row.ref.policy_hash
            or grant.tenant_id != row.ref.tenant_id
            or grant.operation_digest != intent.digest()
        ):
            raise PermissionError("sandbox grant does not match the operation")
        if operation not in grant.allowed_operations:
            raise PermissionError("sandbox grant does not allow this operation")
        if grant.single_use:
            self._used_nonces[grant.nonce] = row.ref.sandbox_id

    @staticmethod
    def _total_file_bytes(row: _LocalRow) -> int:
        return sum(
            value.stat().st_size
            for value in row.root.rglob("*")
            if value.is_file() and not value.is_symlink()
        )

    @staticmethod
    def _stat(row: _LocalRow, candidate: Path) -> FileStat:
        relative = candidate.relative_to(row.root).as_posix()
        wire_path = row.spec.workspace_root.rstrip("/") + (
            f"/{relative}" if relative != "." else ""
        )
        content_hash = None
        if candidate.is_file():
            content_hash = (
                f"sha256:{hashlib.sha256(candidate.read_bytes()).hexdigest()}"
            )
        return FileStat(
            path=wire_path,
            size=candidate.stat().st_size if candidate.is_file() else 0,
            is_file=candidate.is_file(),
            is_directory=candidate.is_dir(),
            content_hash=content_hash,
        )
