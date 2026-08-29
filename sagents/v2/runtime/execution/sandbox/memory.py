"""Deterministic sandbox semantic model with no operating-system isolation.

This Provider validates grants, paths, process/network policy, quotas, snapshot,
and reconnect behavior for conformance tests. It never makes untrusted host
execution safe and must not advertise process/container/VM isolation.
"""

from __future__ import annotations

import hashlib
import hmac
import asyncio
import ipaddress
import posixpath
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sagents.v2.runtime.execution.sandbox.contracts import (
    FileOperation,
    FileStat,
    FileSystemMode,
    IsolationLevel,
    NetworkMode,
    NetworkRequest,
    NetworkResult,
    OperationIntent,
    ProcessCapabilities,
    ProcessRequest,
    ProcessResult,
    ResolvedSandboxSpec,
    ResourceLimitCapabilities,
    SandboxCapabilities,
    SandboxCheckpointRef,
    SandboxGrant,
    SandboxRef,
    SandboxSnapshot,
    SandboxState,
    TerminateMode,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext


def _grant_payload(grant: SandboxGrant) -> bytes:
    data = grant.model_dump(mode="json", exclude={"signature"})
    import json

    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SandboxGrantIssuer:
    """Runtime-side short-lived grant signer; the key is never serialized."""

    def __init__(
        self,
        key: bytes | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._key = key or secrets.token_bytes(32)
        self._clock = clock

    @property
    def verification_key(self) -> bytes:
        return self._key

    def issue(
        self,
        *,
        ref: SandboxRef,
        intent: OperationIntent,
        allowed_operations: frozenset[str],
        ttl: timedelta = timedelta(minutes=1),
        single_use: bool = True,
    ) -> SandboxGrant:
        now = self._clock()
        unsigned = SandboxGrant(
            grant_id=new_id("grant"),
            run_id=intent.run_id,
            tool_call_id=intent.tool_call_id,
            sandbox_id=ref.sandbox_id,
            tenant_id=ref.tenant_id,
            policy_hash=ref.policy_hash,
            spec_hash=ref.spec_hash,
            operation_digest=intent.digest(),
            allowed_operations=allowed_operations,
            issued_at=now,
            expires_at=now + ttl,
            nonce=new_id("nonce"),
            single_use=single_use,
            signature="unsigned",
        )
        signature = hmac.new(
            self._key, _grant_payload(unsigned), hashlib.sha256
        ).hexdigest()
        return unsigned.model_copy(update={"signature": signature})


@dataclass
class _SandboxRow:
    ref: SandboxRef
    spec: ResolvedSandboxSpec
    state: SandboxState
    revision: int
    created_at: datetime
    updated_at: datetime
    files: dict[str, bytes] = field(default_factory=dict)
    attached_clients: int = 1


class _MemoryFileSystem:
    """Policy-checked virtual filesystem scoped to one sandbox row."""

    def __init__(self, provider: "InMemorySandboxProvider", sandbox_id: str) -> None:
        self._provider = provider
        self._sandbox_id = sandbox_id

    async def read_bytes(self, path, *, intent, grant):
        row, normalized = self._provider._authorize(
            self._sandbox_id, FileOperation.READ, path, intent, grant
        )
        try:
            return row.files[normalized]
        except KeyError as exc:
            raise FileNotFoundError(normalized) from exc

    async def write_bytes(
        self, path, content, *, intent, grant, overwrite=True
    ) -> FileStat:
        current_row = self._provider._row(self._sandbox_id)
        normalized_path = self._provider._normalize_path(
            path,
            current_row.spec.workspace_root,
            current_row.spec.filesystem.allowed_roots,
        )
        operation = (
            FileOperation.WRITE
            if normalized_path in current_row.files
            else FileOperation.CREATE
        )
        row, normalized = self._provider._authorize(
            self._sandbox_id, operation, path, intent, grant
        )
        if not overwrite and normalized in row.files:
            raise FileExistsError(normalized)
        policy = row.spec.filesystem
        if policy.max_file_bytes is not None and len(content) > policy.max_file_bytes:
            raise self._provider._error(
                "sandbox.resource_exhausted",
                ErrorCategory.POLICY_DENIED,
                "file exceeds max_file_bytes",
            )
        previous = len(row.files.get(normalized, b""))
        total = (
            sum(len(value) for value in row.files.values()) - previous + len(content)
        )
        if policy.max_total_bytes is not None and total > policy.max_total_bytes:
            raise self._provider._error(
                "sandbox.resource_exhausted",
                ErrorCategory.POLICY_DENIED,
                "sandbox exceeds max_total_bytes",
            )
        row.files[normalized] = bytes(content)
        row.revision += 1
        row.updated_at = self._provider._clock()
        return self._provider._file_stat(normalized, row.files[normalized])

    async def delete(self, path, *, intent, grant) -> None:
        row, normalized = self._provider._authorize(
            self._sandbox_id, FileOperation.DELETE, path, intent, grant
        )
        try:
            del row.files[normalized]
        except KeyError as exc:
            raise FileNotFoundError(normalized) from exc
        row.revision += 1
        row.updated_at = self._provider._clock()

    async def stat(self, path, *, intent, grant) -> FileStat:
        row, normalized = self._provider._authorize(
            self._sandbox_id, FileOperation.READ, path, intent, grant
        )
        if normalized in row.files:
            return self._provider._file_stat(normalized, row.files[normalized])
        prefix = normalized.rstrip("/") + "/"
        if any(candidate.startswith(prefix) for candidate in row.files):
            return FileStat(path=normalized, size=0, is_file=False, is_directory=True)
        raise FileNotFoundError(normalized)

    async def list_paths(self, path, *, intent, grant) -> tuple[FileStat, ...]:
        row, normalized = self._provider._authorize(
            self._sandbox_id, FileOperation.LIST, path, intent, grant
        )
        prefix = normalized.rstrip("/") + "/"
        return tuple(
            self._provider._file_stat(candidate, content)
            for candidate, content in sorted(row.files.items())
            if candidate.startswith(prefix)
        )


MemoryProcessHandler = Callable[[ProcessRequest], Awaitable[tuple[int, bytes, bytes]]]
MemoryNetworkHandler = Callable[[NetworkRequest], Awaitable[NetworkResult]]


class _MemoryProcessRuntime:
    def __init__(self, provider: "InMemorySandboxProvider", sandbox_id: str) -> None:
        self._provider = provider
        self._sandbox_id = sandbox_id

    async def run(self, request, *, intent, grant) -> ProcessResult:
        row = self._provider._authorize_process(
            self._sandbox_id, request, intent, grant
        )
        handler = self._provider._process_handlers.get(request.argv[0])
        if handler is None:
            raise self._provider._error(
                "sandbox.executable_unavailable",
                ErrorCategory.RESOURCE_LOST,
                f"executable {request.argv[0]!r} has no deterministic handler",
            )
        timeout = request.timeout_seconds or row.spec.process.max_wall_time_seconds
        if (
            request.timeout_seconds is not None
            and row.spec.process.max_wall_time_seconds is not None
            and request.timeout_seconds > row.spec.process.max_wall_time_seconds
        ):
            raise self._provider._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "requested timeout exceeds process policy",
            )
        started = time.monotonic()
        try:
            if timeout is None:
                exit_code, stdout, stderr = await handler(request)
            else:
                exit_code, stdout, stderr = await asyncio.wait_for(
                    handler(request), timeout=timeout
                )
            timed_out = False
        except TimeoutError:
            exit_code, stdout, stderr, timed_out = 124, b"", b"process timed out", True
        limit = row.spec.process.max_output_bytes
        truncated = len(stdout) + len(stderr) > limit
        if truncated:
            stdout_budget = min(len(stdout), limit)
            stdout = stdout[:stdout_budget]
            stderr = stderr[: max(0, limit - stdout_budget)]
        return ProcessResult(
            process_id=new_id("process"),
            argv=request.argv,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=max(0, time.monotonic() - started),
            truncated=truncated,
        )


class _MemoryNetworkRuntime:
    def __init__(self, provider: "InMemorySandboxProvider", sandbox_id: str) -> None:
        self._provider = provider
        self._sandbox_id = sandbox_id

    async def request(self, request, *, intent, grant) -> NetworkResult:
        row, host, port = self._provider._authorize_network(
            self._sandbox_id, request, intent, grant
        )
        handler = self._provider._network_handlers.get(host)
        if handler is None:
            raise self._provider._error(
                "sandbox.network_unavailable",
                ErrorCategory.RESOURCE_LOST,
                f"host {host!r} has no deterministic network handler",
            )
        timeout = request.timeout_seconds or row.spec.network.max_wall_time_seconds
        if (
            request.timeout_seconds
            and request.timeout_seconds > row.spec.network.max_wall_time_seconds
        ):
            raise self._provider._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "requested network timeout exceeds policy",
            )
        try:
            result = await asyncio.wait_for(handler(request), timeout=timeout)
        except TimeoutError as exc:
            raise self._provider._error(
                "sandbox.network_timeout",
                ErrorCategory.PROVIDER_TRANSIENT,
                "network request exceeded its wall-time limit",
            ) from exc
        final_host, final_port, _ = self._provider._network_target(
            result.final_url, row.spec.network
        )
        if not self._provider._host_allowed(final_host, row.spec.network.allowed_hosts):
            raise self._provider._error(
                "sandbox.redirect_denied",
                ErrorCategory.POLICY_DENIED,
                "redirect target host is outside network policy",
            )
        if (
            row.spec.network.allowed_ports
            and final_port not in row.spec.network.allowed_ports
        ):
            raise self._provider._error(
                "sandbox.redirect_denied",
                ErrorCategory.POLICY_DENIED,
                "redirect target port is outside network policy",
            )
        if result.redirect_count > row.spec.network.max_redirects:
            raise self._provider._error(
                "sandbox.redirect_limit",
                ErrorCategory.POLICY_DENIED,
                "network response exceeded redirect limit",
            )
        limit = row.spec.network.max_response_bytes
        truncated = result.truncated or len(result.body) > limit
        return result.model_copy(
            update={"body": result.body[:limit], "truncated": truncated}
        )


class _MemoryHandle:
    def __init__(self, provider: "InMemorySandboxProvider", ref: SandboxRef) -> None:
        self._provider = provider
        self.ref = ref
        self.filesystem = _MemoryFileSystem(provider, ref.sandbox_id)
        self.process = _MemoryProcessRuntime(provider, ref.sandbox_id)
        self.network = _MemoryNetworkRuntime(provider, ref.sandbox_id)
        self._closed = False

    async def status(self) -> SandboxSnapshot:
        return await self._provider.inspect(self.ref)

    async def suspend(self) -> SandboxCheckpointRef:
        return await self._provider.snapshot(self.ref)

    async def close(self) -> None:
        if not self._closed:
            row = self._provider._row(self.ref.sandbox_id)
            row.attached_clients = max(0, row.attached_clients - 1)
            self._closed = True

    async def destroy(self) -> None:
        await self._provider.terminate(self.ref, TerminateMode.FORCE)
        self._closed = True


class InMemorySandboxProvider:
    """Provide deterministic conformance isolation, never an OS security boundary."""

    provider_id = "sage.sandbox.memory"
    provider_version = "2.0.0"

    def __init__(
        self,
        verification_key: bytes,
        *,
        process_handlers: Mapping[str, MemoryProcessHandler] | None = None,
        network_handlers: Mapping[str, MemoryNetworkHandler] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._verification_key = verification_key
        self._clock = clock
        self._process_handlers = dict(process_handlers or {})
        self._network_handlers = {
            self._normalize_host(host): handler
            for host, handler in (network_handlers or {}).items()
        }
        self._rows: dict[str, _SandboxRow] = {}
        self._checkpoints: dict[str, tuple[SandboxCheckpointRef, dict[str, bytes]]] = {}
        self._used_nonces: set[str] = set()

    async def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            isolation_level=IsolationLevel.NONE,
            os="memory",
            architectures=("portable",),
            filesystem_modes=frozenset(
                {FileSystemMode.WORKSPACE, FileSystemMode.SNAPSHOT}
            ),
            network_modes=frozenset(
                {NetworkMode.NONE, NetworkMode.ALLOWLIST}
                if self._network_handlers
                else {NetworkMode.NONE}
            ),
            process=ProcessCapabilities(
                available=bool(self._process_handlers),
                supports_argv=bool(self._process_handlers),
                max_processes=1 if self._process_handlers else None,
            ),
            resources=ResourceLimitCapabilities(disk=True),
            supports_background_jobs=False,
            supports_suspend=True,
            supports_snapshot=True,
            supports_reconnect=True,
            supports_secret_injection=False,
        )

    async def provision(
        self, spec: ResolvedSandboxSpec, context: RequestContext, *, run_id: str
    ) -> _MemoryHandle:
        caps = await self.capabilities()
        if spec.architecture not in caps.architectures:
            raise self._error(
                "sandbox.capability_unsupported",
                ErrorCategory.VALIDATION,
                "architecture is unsupported",
            )
        if spec.filesystem_mode not in caps.filesystem_modes:
            raise self._error(
                "sandbox.capability_unsupported",
                ErrorCategory.VALIDATION,
                "filesystem mode is unsupported",
            )
        if spec.network.mode not in caps.network_modes:
            raise self._error(
                "sandbox.capability_unsupported",
                ErrorCategory.VALIDATION,
                "network mode is unsupported",
            )
        if spec.process.enabled and not self._process_handlers:
            raise self._error(
                "sandbox.capability_unsupported",
                ErrorCategory.VALIDATION,
                "process runtime is unsupported",
            )
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
        self._rows[ref.sandbox_id] = _SandboxRow(
            ref=ref,
            spec=spec,
            state=SandboxState.READY,
            revision=0,
            created_at=now,
            updated_at=now,
        )
        return _MemoryHandle(self, ref)

    async def attach(self, ref: SandboxRef, context: RequestContext) -> _MemoryHandle:
        row = self._validate_ref(ref)
        if row.state == SandboxState.TERMINATED:
            raise self._error(
                "sandbox.lost", ErrorCategory.RESOURCE_LOST, "sandbox is terminated"
            )
        if row.ref.tenant_id != context.actor.tenant_id:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.AUTHORIZATION,
                "tenant does not own sandbox",
            )
        row.attached_clients += 1
        return _MemoryHandle(self, ref)

    async def inspect(self, ref: SandboxRef) -> SandboxSnapshot:
        row = self._validate_ref(ref)
        return SandboxSnapshot(
            ref=row.ref,
            state=row.state,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
            attached_clients=row.attached_clients,
            file_count=len(row.files),
            total_file_bytes=sum(len(value) for value in row.files.values()),
        )

    async def snapshot(self, ref: SandboxRef) -> SandboxCheckpointRef:
        row = self._validate_ref(ref)
        if row.state != SandboxState.READY:
            raise self._error(
                "sandbox.invalid_state", ErrorCategory.CONFLICT, "sandbox is not ready"
            )
        now = self._clock()
        checkpoint = SandboxCheckpointRef(
            checkpoint_id=new_id("sandbox_checkpoint"),
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            tenant_id=ref.tenant_id,
            sandbox_id=ref.sandbox_id,
            snapshot_ref=new_id("snapshot"),
            state_revision=row.revision,
            spec_hash=ref.spec_hash,
            policy_hash=ref.policy_hash,
            created_at=now,
        )
        self._checkpoints[checkpoint.checkpoint_id] = (checkpoint, dict(row.files))
        row.state = SandboxState.SUSPENDED
        row.revision += 1
        row.updated_at = now
        return checkpoint

    async def restore(
        self, checkpoint: SandboxCheckpointRef, context: RequestContext
    ) -> _MemoryHandle:
        record = self._checkpoints.get(checkpoint.checkpoint_id)
        if record is None or record[0] != checkpoint:
            raise self._error(
                "sandbox.snapshot_incompatible",
                ErrorCategory.RESOURCE_LOST,
                "checkpoint is unavailable or does not match",
            )
        if checkpoint.tenant_id != context.actor.tenant_id:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.AUTHORIZATION,
                "tenant does not own checkpoint",
            )
        row = self._row(checkpoint.sandbox_id)
        if (
            row.ref.spec_hash != checkpoint.spec_hash
            or row.ref.policy_hash != checkpoint.policy_hash
        ):
            raise self._error(
                "sandbox.policy_stale",
                ErrorCategory.CONFLICT,
                "checkpoint policy/spec no longer matches",
            )
        row.files = dict(record[1])
        row.state = SandboxState.READY
        row.revision += 1
        row.updated_at = self._clock()
        row.attached_clients += 1
        return _MemoryHandle(self, row.ref)

    async def terminate(self, ref: SandboxRef, mode: TerminateMode) -> None:
        row = self._validate_ref(ref)
        if row.state != SandboxState.TERMINATED:
            row.state = SandboxState.TERMINATED
            row.revision += 1
            row.updated_at = self._clock()
            row.attached_clients = 0

    def _authorize(self, sandbox_id, operation, path, intent, grant):
        """Verify grant identity and exact operation intent at enforcement time.

        A prior policy decision cannot be reused with a changed sandbox, path,
        operation, or request digest.
        """

        row = self._row(sandbox_id)
        if row.state != SandboxState.READY:
            raise self._error(
                "sandbox.unavailable",
                ErrorCategory.RESOURCE_LOST,
                "sandbox is not ready",
            )
        normalized = self._normalize_path(
            path, row.spec.workspace_root, row.spec.filesystem.allowed_roots
        )
        if intent.path != path or intent.sandbox_id != sandbox_id:
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "operation intent does not match request",
            )
        if intent.operation != operation.value:
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "operation intent kind does not match request",
            )
        if operation not in row.spec.filesystem.allowed_operations:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "filesystem operation is outside policy",
            )
        if operation.value not in grant.allowed_operations:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.AUTHORIZATION,
                "grant does not allow operation",
            )
        if grant.run_id != row.ref.owner_run_id or grant.sandbox_id != sandbox_id:
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "grant owner does not match sandbox",
            )
        if (
            grant.tool_call_id != intent.tool_call_id
            or grant.operation_digest != intent.digest()
        ):
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "grant does not match operation digest",
            )
        if (
            grant.policy_hash != row.ref.policy_hash
            or grant.spec_hash != row.ref.spec_hash
        ):
            raise self._error(
                "sandbox.policy_stale",
                ErrorCategory.CONFLICT,
                "grant policy/spec is stale",
            )
        if grant.expires_at <= self._clock():
            raise self._error(
                "sandbox.grant_expired",
                ErrorCategory.AUTHORIZATION,
                "grant has expired",
            )
        expected = hmac.new(
            self._verification_key, _grant_payload(grant), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise self._error(
                "sandbox.grant_invalid",
                ErrorCategory.AUTHORIZATION,
                "grant signature is invalid",
            )
        if grant.single_use:
            if grant.nonce in self._used_nonces:
                raise self._error(
                    "sandbox.grant_replayed",
                    ErrorCategory.AUTHORIZATION,
                    "single-use grant was already consumed",
                )
            self._used_nonces.add(grant.nonce)
        return row, normalized

    def _authorize_process(self, sandbox_id, request, intent, grant):
        row = self._row(sandbox_id)
        if row.state != SandboxState.READY:
            raise self._error(
                "sandbox.unavailable",
                ErrorCategory.RESOURCE_LOST,
                "sandbox is not ready",
            )
        policy = row.spec.process
        if not policy.enabled:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "process execution is disabled",
            )
        executable = request.argv[0]
        if executable not in policy.allowed_executables:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"executable {executable!r} is outside process policy",
            )
        unexpected_env = set(request.env) - set(policy.allowed_env_names)
        if unexpected_env:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"environment names are outside policy: {sorted(unexpected_env)}",
            )
        self._normalize_path(
            request.cwd,
            row.spec.workspace_root,
            row.spec.filesystem.allowed_roots,
        )
        if (
            intent.operation != "process.run"
            or intent.sandbox_id != sandbox_id
            or intent.executable != executable
            or intent.argv != request.argv
            or intent.path != request.cwd
        ):
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "process intent does not match request",
            )
        if "process.run" not in grant.allowed_operations:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.AUTHORIZATION,
                "grant does not allow process.run",
            )
        self._verify_grant(row, intent, grant)
        return row

    def _authorize_network(self, sandbox_id, request, intent, grant):
        row = self._row(sandbox_id)
        if row.state != SandboxState.READY:
            raise self._error(
                "sandbox.unavailable",
                ErrorCategory.RESOURCE_LOST,
                "sandbox is not ready",
            )
        policy = row.spec.network
        if policy.mode == NetworkMode.NONE:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "network access is disabled",
            )
        method = request.method.upper()
        if method not in {value.upper() for value in policy.allowed_methods}:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"network method {method!r} is outside policy",
            )
        unexpected_headers = {name.lower() for name in request.headers} - {
            name.lower() for name in policy.allowed_request_headers
        }
        if unexpected_headers:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"network request headers are outside policy: {sorted(unexpected_headers)}",
            )
        if (
            request.body is not None
            and len(request.body) > policy.max_request_body_bytes
        ):
            raise self._error(
                "sandbox.resource_exhausted",
                ErrorCategory.POLICY_DENIED,
                "network request body exceeds policy",
            )
        host, port, _ = self._network_target(request.url, policy)
        if not self._host_allowed(host, policy.allowed_hosts):
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"network host {host!r} is outside policy",
            )
        if policy.allowed_ports and port not in policy.allowed_ports:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"network port {port} is outside policy",
            )
        if (
            intent.operation != "network.request"
            or intent.sandbox_id != sandbox_id
            or intent.network_host != host
            or intent.network_port != port
            or intent.metadata.get("method", "").upper() != method
            or intent.metadata.get("url") != request.url
        ):
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "network intent does not match request",
            )
        if "network.request" not in grant.allowed_operations:
            raise self._error(
                "sandbox.permission_denied",
                ErrorCategory.AUTHORIZATION,
                "grant does not allow network.request",
            )
        self._verify_grant(row, intent, grant)
        return row, host, port

    @classmethod
    def _network_target(cls, url, policy):
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in policy.allowed_schemes:
            raise cls._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                f"network scheme {scheme!r} is outside policy",
            )
        if parsed.username is not None or parsed.password is not None:
            raise cls._error(
                "sandbox.permission_denied",
                ErrorCategory.POLICY_DENIED,
                "URL userinfo is not permitted",
            )
        if parsed.hostname is None:
            raise cls._error(
                "sandbox.network_url_invalid",
                ErrorCategory.VALIDATION,
                "network URL requires a host",
            )
        host = cls._normalize_host(parsed.hostname)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (
            policy.deny_private_networks
            and address is not None
            and not address.is_global
        ):
            raise cls._error(
                "sandbox.private_network_denied",
                ErrorCategory.POLICY_DENIED,
                "private, loopback, link-local, and reserved addresses are denied",
            )
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise cls._error(
                "sandbox.network_url_invalid",
                ErrorCategory.VALIDATION,
                "network URL has an invalid port",
            ) from exc
        return host, port, scheme

    @staticmethod
    def _normalize_host(host):
        return host.rstrip(".").encode("idna").decode("ascii").lower()

    @staticmethod
    def _host_allowed(host, patterns):
        for pattern in patterns:
            normalized = pattern.rstrip(".").encode("idna").decode("ascii").lower()
            if normalized.startswith("*."):
                suffix = normalized[1:]
                if host.endswith(suffix) and host != suffix[1:]:
                    return True
            elif host == normalized:
                return True
        return False

    def _verify_grant(self, row, intent, grant):
        if (
            grant.run_id != row.ref.owner_run_id
            or grant.sandbox_id != row.ref.sandbox_id
        ):
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "grant owner does not match sandbox",
            )
        if (
            grant.tool_call_id != intent.tool_call_id
            or grant.operation_digest != intent.digest()
        ):
            raise self._error(
                "sandbox.grant_mismatch",
                ErrorCategory.AUTHORIZATION,
                "grant does not match operation digest",
            )
        if (
            grant.policy_hash != row.ref.policy_hash
            or grant.spec_hash != row.ref.spec_hash
        ):
            raise self._error(
                "sandbox.policy_stale",
                ErrorCategory.CONFLICT,
                "grant policy/spec is stale",
            )
        if grant.expires_at <= self._clock():
            raise self._error(
                "sandbox.grant_expired",
                ErrorCategory.AUTHORIZATION,
                "grant has expired",
            )
        expected = hmac.new(
            self._verification_key, _grant_payload(grant), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise self._error(
                "sandbox.grant_invalid",
                ErrorCategory.AUTHORIZATION,
                "grant signature is invalid",
            )
        if grant.single_use:
            if grant.nonce in self._used_nonces:
                raise self._error(
                    "sandbox.grant_replayed",
                    ErrorCategory.AUTHORIZATION,
                    "single-use grant was already consumed",
                )
            self._used_nonces.add(grant.nonce)

    @staticmethod
    def _normalize_path(
        path: str, workspace_root: str, allowed_roots: tuple[str, ...]
    ) -> str:
        normalized_input = unicodedata.normalize("NFC", path).replace("\\", "/")
        if "\x00" in normalized_input:
            raise PermissionError("NUL is not allowed in sandbox paths")
        candidate = (
            normalized_input
            if normalized_input.startswith("/")
            else posixpath.join(workspace_root, normalized_input)
        )
        normalized = posixpath.normpath(candidate)
        root = posixpath.normpath(workspace_root)
        if normalized != root and not normalized.startswith(root.rstrip("/") + "/"):
            raise PermissionError("path is outside sandbox workspace")
        normalized_roots = tuple(posixpath.normpath(value) for value in allowed_roots)
        if not any(
            normalized == allowed or normalized.startswith(allowed.rstrip("/") + "/")
            for allowed in normalized_roots
        ):
            raise PermissionError("path is outside allowed filesystem roots")
        return normalized

    def _validate_ref(self, ref: SandboxRef) -> _SandboxRow:
        row = self._row(ref.sandbox_id)
        if row.ref != ref:
            raise self._error(
                "sandbox.ref_mismatch",
                ErrorCategory.AUTHORIZATION,
                "sandbox reference does not match",
            )
        return row

    def _row(self, sandbox_id: str) -> _SandboxRow:
        try:
            return self._rows[sandbox_id]
        except KeyError as exc:
            raise self._error(
                "sandbox.lost", ErrorCategory.RESOURCE_LOST, "sandbox does not exist"
            ) from exc

    @staticmethod
    def _file_stat(path: str, content: bytes) -> FileStat:
        return FileStat(
            path=path,
            size=len(content),
            is_file=True,
            is_directory=False,
            content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        )

    @staticmethod
    def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                safe_to_resume=True,
            )
        )
